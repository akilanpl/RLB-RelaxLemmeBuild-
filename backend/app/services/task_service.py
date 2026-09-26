"""Task and workflow persistence used by the API and agent orchestration layer."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.task import (
    ActorType, AgentRunRecord, AgentStateRecord, ApprovalRecord, TaskRecord,
    TransitionRecord,
)
from backend.app.models.planner import PersistedPlan
from backend.app.models.workspace import Workspace
from backend.app.services.workspace_service import WorkspaceService
from backend.app.workflow.states import WorkflowState
from backend.app.repositories.task import InMemoryTaskRepository, TaskRepository
from backend.app.db.session import get_sessionmaker
from backend.app.core.config import get_settings
from backend.app.repositories.task import PostgresTaskRepository


class TaskNotFoundError(KeyError):
    pass


class TaskAccessDeniedError(PermissionError):
    pass


class WorkflowConflictError(RuntimeError):
    pass


class InvalidWorkflowTransitionError(ValueError):
    pass


TRANSITIONS = {
    WorkflowState.READY: {WorkflowState.PLANNING, WorkflowState.CANCELLED},
    WorkflowState.PLANNING: {WorkflowState.PLAN_REVIEW, WorkflowState.FAILED},
    WorkflowState.PLAN_REVIEW: {WorkflowState.PLANNING, WorkflowState.CODING, WorkflowState.CANCELLED},
    WorkflowState.CODING: {WorkflowState.CODE_REVIEW, WorkflowState.FAILED},
    WorkflowState.CODE_REVIEW: {WorkflowState.CODING, WorkflowState.TEST_PLANNING, WorkflowState.CANCELLED},
    WorkflowState.TEST_PLANNING: {WorkflowState.TEST_EXECUTING, WorkflowState.FAILED},
    WorkflowState.TEST_EXECUTING: {WorkflowState.REPAIRING, WorkflowState.REVIEWING, WorkflowState.FAILED},
    WorkflowState.REPAIRING: {WorkflowState.CODING, WorkflowState.FAILED},
    WorkflowState.REVIEWING: {WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.COMPLETED: {WorkflowState.READY},
}

def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowEngine:
    def __init__(self, workspace_service: Optional[WorkspaceService] = None,
                 repository: Optional[TaskRepository] = None):
        self.workspace_service = workspace_service or WorkspaceService()
        sessionmaker = get_sessionmaker()
        if sessionmaker is None and get_settings().ENVIRONMENT == "production":
            raise RuntimeError("Production orchestration requires DATABASE_URL and PostgreSQL persistence.")
        self.repository = repository or (
            PostgresTaskRepository(sessionmaker) if sessionmaker is not None else InMemoryTaskRepository()
        )

    async def create_task(self, workspace: Workspace, user_id: UUID, title: str, objective: str) -> TaskRecord:
        if workspace.user_id != user_id:
            raise TaskAccessDeniedError("Workspace access denied.")
        now = _now()
        task = TaskRecord(
            id=uuid4(), workspace_id=workspace.id, conversation_id=uuid4(),
            user_id=user_id, title=title, objective=objective, user_prompt=objective,
            approved_snapshot_hash=workspace.current_snapshot_hash,
            created_at=now, updated_at=now,
        )
        return await self.repository.create(task)

    async def get_task(self, task_id: UUID, user_id: UUID) -> TaskRecord:
        task = await self.repository.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        if task.user_id != user_id:
            raise TaskAccessDeniedError("Task access denied.")
        return task

    async def latest_task_for_workspace(self, workspace_id: UUID, user_id: UUID) -> Optional[TaskRecord]:
        tasks = await self.repository.list_for_workspace(workspace_id)
        owned = [task for task in tasks if task.user_id == user_id]
        return owned[0] if owned else None

    async def can_transition(self, task_id: UUID, target: WorkflowState, expected_version: Optional[int] = None) -> bool:
        task = await self.repository.get(task_id)
        if not task or (expected_version is not None and task.version != expected_version):
            return False
        return target in TRANSITIONS.get(task.status, set())

    async def transition(
        self, task_id: UUID, target: WorkflowState, actor_type: ActorType,
        actor_id: Optional[UUID], reason: str, metadata: Optional[Dict[str, Any]] = None,
        expected_version: Optional[int] = None,
    ) -> TaskRecord:
        task = await self.repository.get(task_id)
        if not task:
            raise TaskNotFoundError(task_id)
        if expected_version is not None and task.version != expected_version:
            raise WorkflowConflictError("Task version is stale.")
        if target not in TRANSITIONS.get(task.status, set()):
            raise InvalidWorkflowTransitionError(f"{task.status.value} -> {target.value} is not allowed.")
        before = task.version
        transition = TransitionRecord(
                id=uuid4(), task_id=task_id, previous_state=task.status, new_state=target,
                actor_type=actor_type, actor_id=actor_id, reason=reason,
                metadata=metadata or {}, timestamp=_now(),
                task_version_before=before, task_version_after=before + 1,
            )
        updated = await self.repository.transition(task_id, target, transition, expected_version)
        if not updated:
            raise WorkflowConflictError("Task version is stale.")
        return updated

    async def get_history(self, task_id: UUID, user_id: UUID) -> List[TransitionRecord]:
        await self.get_task(task_id, user_id)
        return await self.repository.history(task_id)

    async def record_approval(self, task_id: UUID, user_id: UUID, approval_type: str, status: str, feedback: Optional[str]) -> ApprovalRecord:
        task = await self.get_task(task_id, user_id)
        if task.status not in (WorkflowState.PLAN_REVIEW, WorkflowState.CODE_REVIEW):
            raise InvalidWorkflowTransitionError("Approvals are only allowed at a review gate.")
        record = ApprovalRecord(id=uuid4(), task_id=task_id, approval_type=approval_type, user_id=user_id, status=status, feedback=feedback, timestamp=_now())
        if status == "approved" and task.status == WorkflowState.PLAN_REVIEW and task.active_staging_workspace_id is None:
            await self._attach_plan_staging(task, user_id)
        target = {"approved": WorkflowState.CODING if task.status == WorkflowState.PLAN_REVIEW else WorkflowState.TEST_PLANNING,
                  "rejected": WorkflowState.CANCELLED,
                  "revision_requested": WorkflowState.PLANNING if task.status == WorkflowState.PLAN_REVIEW else WorkflowState.CODING}[status]
        transition = TransitionRecord(
            id=uuid4(), task_id=task_id, previous_state=task.status, new_state=target,
            actor_type=ActorType.USER, actor_id=user_id,
            reason=f"{status} {approval_type}",
            metadata={"feedback": feedback} if feedback else {},
            timestamp=_now(), task_version_before=task.version,
            task_version_after=task.version + 1,
        )
        if not await self.repository.approve_and_transition(record, target, transition, task.version):
            raise WorkflowConflictError("Task version is stale.")
        return record

    async def _attach_plan_staging(self, task: TaskRecord, user_id: UUID) -> None:
        """Create the coding staging workspace when the parent workspace is available."""
        from backend.app.services.staging_service import StagingService
        from backend.app.services.workspace_service import WorkspaceNotFoundError

        try:
            await self.workspace_service.get_workspace(task.workspace_id, user_id)
        except WorkspaceNotFoundError:
            return
        staging = await StagingService(self.workspace_service).create_staging_workspace(
            task.workspace_id, user_id, task.id
        )
        setter = getattr(self.repository, "set_active_staging", None)
        if setter is not None:
            await setter(task.id, staging.id)

    async def create_agent_run(self, task_id: UUID, user_id: UUID, role: AgentRole, **metadata: Any) -> AgentRunRecord:
        await self.get_task(task_id, user_id)
        run = AgentRunRecord(
            id=uuid4(),
            task_id=task_id,
            agent_role=role,
            loadout_id=metadata.pop("loadout_id", None),
            worker_id=metadata.pop("worker_id", None),
            provider_id=metadata.pop("provider_id", None),
            model_name=metadata.pop("model_name", None),
            metadata=metadata,
        )
        return await self.repository.add_run(run)

    async def update_agent_run(self, run_id: UUID, status: ExecutionStatus, **metadata: Any) -> AgentRunRecord:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise TaskNotFoundError(run_id)
        update = {"status": status, **metadata}
        if status == ExecutionStatus.RUNNING: update["started_at"] = _now()
        if status in (
            ExecutionStatus.SUCCESS,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.RETRYABLE_ERROR,
            ExecutionStatus.BLOCKED,
            ExecutionStatus.RATE_LIMITED,
            ExecutionStatus.CANCELLED,
        ):
            update["completed_at"] = _now()
        run = run.model_copy(update=update)
        return await self.repository.update_run(run)

    async def list_agent_runs(self, task_id: UUID, user_id: UUID) -> List[AgentRunRecord]:
        await self.get_task(task_id, user_id)
        return await self.repository.list_runs(task_id)

    async def save_agent_state(self, task_id: UUID, user_id: UUID, role: AgentRole, payload: Dict[str, Any]) -> AgentStateRecord:
        await self.get_task(task_id, user_id)
        existing = getattr(self.repository, "states", {}).get(task_id, [])
        seq = len([s for s in existing if s.agent_role == role]) + 1
        state = AgentStateRecord(id=uuid4(), task_id=task_id, agent_role=role, state_payload=payload, checkpoint_seq=seq, created_at=_now())
        return await self.repository.add_state(state)

    async def save_plan(self, plan: PersistedPlan) -> PersistedPlan:
        return await self.repository.add_plan(plan)

    async def list_plans(self, task_id: UUID, user_id: UUID) -> List[PersistedPlan]:
        await self.get_task(task_id, user_id)
        return await self.repository.list_plans(task_id)

    async def add_message(self, task_id: UUID, sender_type: str, content: str, metadata: Dict[str, Any]) -> None:
        await self.repository.add_message(task_id, sender_type, content, metadata)


workflow_engine = WorkflowEngine()
