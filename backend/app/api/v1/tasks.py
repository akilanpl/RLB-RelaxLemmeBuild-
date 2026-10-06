"""Authenticated task and orchestration APIs."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.core.auth import AuthenticatedUserContext, get_authenticated_user
from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.task import ActorType
from backend.app.services.task_service import (
    InvalidWorkflowTransitionError, TaskAccessDeniedError, TaskNotFoundError, TaskRateLimitError,
    WorkflowConflictError, workflow_engine,
)
from backend.app.services.workspace_service import WorkspaceNotFoundError
from backend.app.services.zip_import import ZipValidationError
from backend.app.services.planner_service import PlannerExecutionError, planner_service
from backend.app.services.coder_service import CoderExecutionError, coder_service
from backend.app.workflow.states import WorkflowState
from backend.app.repositories.testing import InMemoryTestingRepository, PostgresTestingRepository
from backend.app.db.session import get_sessionmaker
from backend.app.services.testing_service import TestArchitectService
from backend.app.services.test_orchestrator import TestOrchestrationService
from backend.app.services.reviewer_service import ReviewerExecutionError, ReviewerService
from backend.app.repositories.reviewer import InMemoryReviewerReportRepository, PostgresReviewerReportRepository
from backend.app.services.job_queue import LocalJobQueue
from backend.app.services.supabase_queue import SupabaseQueueAdapter
from backend.app.services.supabase_queue_client import SupabaseQueueClient
from backend.app.db.session import get_engine
from backend.app.core.config import get_settings

router = APIRouter(prefix="/tasks", tags=["tasks"])
from backend.app.services.runtime import RuntimeRef
testing_repository = RuntimeRef("testing")
reviewer_repository = RuntimeRef("agents.reviewer.repository")
reviewer_service = RuntimeRef("agents.reviewer")
job_queue = RuntimeRef("queue")


def configure_agent_services(services) -> None:
    """Replace module-level production services while preserving test injection."""
    global planner_service, coder_service, reviewer_service, reviewer_repository
    planner_service = services.planner
    coder_service = services.coder
    reviewer_service = services.reviewer
    reviewer_repository = services.reviewer.repository
    reviewer_service.context_builder.proposals = services.coder.proposals
    reviewer_service.context_builder.testing = testing_repository


class CreateTaskRequest(BaseModel):
    workspace_id: UUID
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=20000)


class TransitionRequest(BaseModel):
    target_state: WorkflowState
    reason: str = Field(min_length=1)
    expected_version: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    approval_type: str
    status: str
    feedback: Optional[str] = None


class AgentRunRequest(BaseModel):
    agent_role: AgentRole
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlannerRequest(BaseModel):
    revision_feedback: Optional[str] = None


class CoderRequest(BaseModel):
    staging_workspace_id: Optional[UUID] = None
    revision_feedback: Optional[str] = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(request: CreateTaskRequest, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        workspace = await workflow_engine.workspace_service.get_workspace(request.workspace_id, auth.user_id)
        if workspace.local_path:
            workspace = await workflow_engine.workspace_service.refresh_local_workspace(
                workspace.id, auth.user_id
            )
        task = await workflow_engine.create_task(workspace, auth.user_id, request.title, request.objective)
        await job_queue.enqueue(task.id, auth.user_id)
        return task
    except TaskRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "3600"})
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    except (TaskAccessDeniedError, PermissionError):
        raise HTTPException(status_code=403, detail="Workspace access denied.")
    except (OSError, ValueError, ZipValidationError) as exc:
        raise HTTPException(status_code=409, detail=f"Local project is unavailable: {exc}")


async def _get_task_or_error(task_id: UUID, auth: AuthenticatedUserContext):
    try:
        return await workflow_engine.get_task(task_id, auth.user_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.get("/workspace/{workspace_id}/latest")
async def get_latest_workspace_task(
    workspace_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)
):
    task = await workflow_engine.latest_task_for_workspace(workspace_id, auth.user_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@router.get("/{task_id}")
async def get_task(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        return await _get_task_or_error(task_id, auth)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.get("/{task_id}/history")
async def get_history(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        return await workflow_engine.get_history(task_id, auth.user_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.get("/{task_id}/workflow")
async def get_workflow(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    task = await _get_task_or_error(task_id, auth)
    return {"task_id": task.id, "state": task.status, "version": task.version}


@router.post("/{task_id}/revision")
async def revise_task(task_id: UUID, request: TransitionRequest, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    return await transition_task(task_id, request, auth)


@router.post("/{task_id}/transition")
async def transition_task(task_id: UUID, request: TransitionRequest, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await workflow_engine.get_task(task_id, auth.user_id)
        if request.target_state not in {WorkflowState.PLANNING, WorkflowState.CANCELLED}:
            raise HTTPException(status_code=409, detail="This transition is managed by the worker or an approval gate.")
        return await workflow_engine.transition(task_id, request.target_state, ActorType.USER, auth.user_id, request.reason, request.metadata, request.expected_version)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")
    except WorkflowConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InvalidWorkflowTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{task_id}/approvals")
async def record_approval(task_id: UUID, request: ApprovalRequest, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    if request.status not in {"approved", "rejected", "revision_requested"}:
        raise HTTPException(status_code=422, detail="Invalid approval status.")
    try:
        if request.approval_type == "code" and request.status == "approved":
            raise HTTPException(status_code=409, detail="Approve a specific code proposal to apply its reviewed changes.")
        approval = await workflow_engine.record_approval(task_id, auth.user_id, request.approval_type, request.status, request.feedback, defer_setup=True)
        if request.status in {"approved", "revision_requested"}:
            await job_queue.enqueue(task_id, auth.user_id)
        return approval
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")
    except InvalidWorkflowTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{task_id}/agent-runs")
async def get_agent_runs(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        return await workflow_engine.list_agent_runs(task_id, auth.user_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.post("/{task_id}/review")
async def run_reviewer(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    """Run the read-only final review; only orchestration may complete the task."""
    if get_settings().ENVIRONMENT in {"staging", "production", "desktop"}:
        raise HTTPException(status_code=409, detail="Execution is owned by the durable worker. Use the resume endpoint.")
    try:
        return await reviewer_service.execute(task_id, auth.user_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")
    except ReviewerExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{task_id}/review")
async def get_reviewer_report(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await workflow_engine.get_task(task_id, auth.user_id)
        report = await reviewer_repository.get_by_task(task_id)
        if not report:
            raise HTTPException(status_code=404, detail="Reviewer report not found.")
        return report
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.post("/{task_id}/planner")
async def run_planner(task_id: UUID, request: PlannerRequest = PlannerRequest(),
                      auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    if get_settings().ENVIRONMENT in {"staging", "production", "desktop"}:
        raise HTTPException(status_code=409, detail="Execution is owned by the durable worker. Use the resume endpoint.")
    try:
        task = await workflow_engine.get_task(task_id, auth.user_id)
        if task.status == WorkflowState.PLAN_REVIEW and not request.revision_feedback:
            plans = await workflow_engine.list_plans(task_id, auth.user_id)
            if plans:
                return plans[-1]
        if task.status == WorkflowState.READY:
            task = await workflow_engine.transition(
                task_id, WorkflowState.PLANNING, ActorType.SYSTEM, None,
                "Planner execution started", expected_version=task.version,
            )
        result = await planner_service.execute(task_id, auth.user_id, request.revision_feedback)
        current = await workflow_engine.get_task(task_id, auth.user_id)
        if current.status == WorkflowState.PLANNING:
            await workflow_engine.transition(
                task_id, WorkflowState.PLAN_REVIEW, ActorType.SYSTEM, None,
                "Planner produced a structured plan",
                {"plan_id": str(result.id)}, expected_version=current.version,
            )
        return result
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")
    except PlannerExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{task_id}/plans")
async def get_plans(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        return await workflow_engine.list_plans(task_id, auth.user_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.get("/{task_id}/test-plans")
async def get_test_plan(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    """Read the persisted Test Architect output; this endpoint never creates or edits plans."""
    try:
        await workflow_engine.get_task(task_id, auth.user_id)
        plan = await TestArchitectService(testing_repository).get_plan(task_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="Test plan not found.")
        return plan
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.post("/{task_id}/test-plan")
async def create_test_plan(
    task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)
):
    if get_settings().ENVIRONMENT in {"staging", "production", "desktop"}:
        raise HTTPException(status_code=409, detail="Execution is owned by the durable worker. Use the resume endpoint.")
    try:
        task = await workflow_engine.get_task(task_id, auth.user_id)
        if task.status != WorkflowState.TEST_PLANNING:
            raise HTTPException(status_code=409, detail="Task is not in TEST_PLANNING.")
        run = await workflow_engine.create_agent_run(
            task_id, auth.user_id, AgentRole.TEST_ARCHITECT
        )
        await workflow_engine.update_agent_run(run.id, ExecutionStatus.RUNNING)
        plan = await TestArchitectService(testing_repository).create_plan(
            task_id, run.id, task.objective
        )
        await workflow_engine.update_agent_run(run.id, ExecutionStatus.SUCCESS)
        current = await workflow_engine.get_task(task_id, auth.user_id)
        await workflow_engine.transition(
            task_id, WorkflowState.TEST_EXECUTING, ActorType.SYSTEM, None,
            "Test plan generated", {"test_plan_id": str(plan.id)},
            expected_version=current.version,
        )
        return plan
    except (TaskNotFoundError, TaskAccessDeniedError):
        raise HTTPException(status_code=404, detail="Task not found.")
    except WorkflowConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{task_id}/test-execute")
async def execute_tests(
    task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)
):
    await _get_task_or_error(task_id, auth)
    await job_queue.enqueue(task_id, auth.user_id)
    return {"status": "queued", "task_id": task_id}


@router.get("/{task_id}/test-executions")
async def get_test_executions(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await workflow_engine.get_task(task_id, auth.user_id)
        return await testing_repository.list_executions(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.post("/{task_id}/coder")
async def run_coder(task_id: UUID, request: CoderRequest = CoderRequest(),
                    auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    if get_settings().ENVIRONMENT in {"staging", "production", "desktop"}:
        raise HTTPException(status_code=409, detail="Execution is owned by the durable worker. Use the resume endpoint.")
    try:
        proposal = await coder_service.execute(
            task_id, auth.user_id, request.staging_workspace_id, request.revision_feedback
        )
        task = await workflow_engine.get_task(task_id, auth.user_id)
        await workflow_engine.transition(
            task_id, WorkflowState.CODE_REVIEW, ActorType.SYSTEM, None,
            "Coder produced a structured code proposal",
            {"proposal_id": str(proposal.id)}, expected_version=task.version,
        )
        return proposal
    except (TaskNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Task or staging workspace not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")
    except CoderExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/code-proposals/{proposal_id}/approve")
async def approve_code_proposal(
    proposal_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)
):
    try:
        result = await coder_service.request_promotion(proposal_id, auth.user_id)
        proposal = await coder_service.proposals.get(proposal_id)
        await job_queue.enqueue(proposal.task_id, auth.user_id)
        return result
    except CoderExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


async def _proposal_payload(proposal, user_id):
    """Expose review-friendly file contents captured when the proposal was created."""
    task = await workflow_engine.get_task(proposal.task_id, user_id)
    result = proposal.model_dump(mode="json")
    workspace = await workflow_engine.workspace_service.get_workspace(task.workspace_id, user_id)
    result["stale"] = workspace.current_snapshot_hash != proposal.base_snapshot_hash
    return result


@router.get("/{task_id}/code-proposals")
async def get_code_proposals(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await _get_task_or_error(task_id, auth)
        proposals = await coder_service.proposals.list_by_task(task_id)
        return [await _proposal_payload(proposal, auth.user_id) for proposal in proposals]
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskAccessDeniedError:
        raise HTTPException(status_code=403, detail="Task access denied.")


@router.get("/code-proposals/{proposal_id}")
async def get_code_proposal(proposal_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        proposal = await coder_service.proposals.get(proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Code proposal not found.")
        return await _proposal_payload(proposal, auth.user_id)
    except (TaskNotFoundError, TaskAccessDeniedError):
        raise HTTPException(status_code=404, detail="Code proposal not found.")


class CodeRevisionRequest(BaseModel):
    feedback: str = Field(min_length=1)


@router.post("/code-proposals/{proposal_id}/revision")
async def revise_code_proposal(
    proposal_id: UUID, request: CodeRevisionRequest,
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    try:
        proposal = await coder_service.request_revision(proposal_id, auth.user_id, request.feedback)
        await job_queue.enqueue(proposal.task_id, auth.user_id)
        return proposal
    except (CoderExecutionError, TaskNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/code-proposals/{proposal_id}/reject")
async def reject_code_proposal(
    proposal_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)
):
    try:
        return await coder_service.reject(proposal_id, auth.user_id)
    except (CoderExecutionError, TaskNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{task_id}/permissions")
async def get_permissions(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    await _get_task_or_error(task_id, auth)
    from backend.app.core.permissions import AgentPermissionGatekeeper
    return {role.value: sorted(tools) for role, tools in AgentPermissionGatekeeper.ROLE_PERMISSIONS.items()}


@router.post("/{task_id}/resume", status_code=202)
async def resume_task(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        task = await workflow_engine.get_task(task_id, auth.user_id)
        if task.status in {WorkflowState.COMPLETED, WorkflowState.CANCELLED, WorkflowState.PLAN_REVIEW, WorkflowState.CODE_REVIEW}:
            raise HTTPException(status_code=409, detail="Task is terminal or waiting for your review.")
        if task.status == WorkflowState.FAILED:
            raise HTTPException(status_code=409, detail="Create a new task after correcting the reported configuration or provider error.")
        await job_queue.enqueue(task_id, auth.user_id)
        return {"task_id": task_id, "status": "queued"}
    except (TaskNotFoundError, TaskAccessDeniedError):
        raise HTTPException(status_code=404, detail="Task not found.")


@router.get('/{task_id}/events')
async def get_task_events(task_id: UUID, after: int = 0, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    task = await _get_task_or_error(task_id, auth)
    sessions = get_sessionmaker()
    if sessions:
        from sqlalchemy import text
        async with sessions() as session:
            rows = (await session.execute(text("""SELECT * FROM task_events
                WHERE task_id=:task AND sequence > :after ORDER BY sequence LIMIT 200"""),
                {'task': task_id, 'after': max(after, 0)})).mappings().all()
            return [dict(row) for row in rows]
    history = await workflow_engine.get_history(task.id, auth.user_id)
    return [{'sequence': index + 1, 'task_id': task.id, 'workspace_id': task.workspace_id,
             'event_type': 'task.' + item.new_state.value, 'actor_type': item.actor_type,
             'payload': item.metadata, 'created_at': item.timestamp}
            for index, item in enumerate(history) if index + 1 > after][:200]
