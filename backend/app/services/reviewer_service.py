"""Phase 9 final review orchestration."""
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
from backend.app.ai.gateway import AIGateway
from backend.app.ai.groq import GroqGateway
from backend.app.agents.base import AgentExecutionContext
from backend.app.agents.reviewer import ReviewerAgent
from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.audit import ReviewerReport
from backend.app.models.task import ActorType
from backend.app.repositories.reviewer import InMemoryReviewerReportRepository, PostgresReviewerReportRepository
from backend.app.db.session import get_sessionmaker
from backend.app.services.reviewer_context import ReviewerContextBuilder
from backend.app.services.task_service import workflow_engine
from backend.app.workflow.states import WorkflowState


class ReviewerExecutionError(RuntimeError):
    pass


class ReviewerService:
    def __init__(self, gateway: Optional[AIGateway] = None, context_builder=None,
                 repository=None, workflow=None, gateway_resolver=None, runtime_resolver=None):
        self.gateway = gateway or GroqGateway()
        self.gateway_resolver = gateway_resolver
        self.runtime_resolver = runtime_resolver
        self.workflow = workflow or workflow_engine
        self.context_builder = context_builder or ReviewerContextBuilder(self.workflow)
        sessions = get_sessionmaker()
        self.repository = repository or (PostgresReviewerReportRepository(sessions) if sessions
                                         else InMemoryReviewerReportRepository())

    async def execute(self, task_id: UUID, user_id: UUID) -> ReviewerReport:
        task = await self.workflow.get_task(task_id, user_id)
        existing = await self.repository.get_by_task(task_id)
        if existing is not None:
            if task.status == WorkflowState.REVIEWING:
                await self.workflow.transition(task_id, WorkflowState.COMPLETED, ActorType.SYSTEM, None,
                    "Recovered persisted final review", {"reviewer_report_id": str(existing.id)},
                    expected_version=task.version)
            return existing
        if task.status != WorkflowState.REVIEWING:
            raise ReviewerExecutionError("Task must be in REVIEWING before Reviewer execution.")
        try:
            runtime = (self.runtime_resolver.resolve(
                user_id, task.workspace_id, task.id, AgentRole.REVIEWER.value
            ) if self.runtime_resolver else None)
        except (LookupError, PermissionError) as exc:
            raise ReviewerExecutionError(str(exc)) from exc
        run = await self.workflow.create_agent_run(
            task_id, user_id, AgentRole.REVIEWER,
            **(runtime.run_metadata() if runtime else {}),
        )
        gateway = runtime.gateway if runtime else (
            self.gateway_resolver(task, user_id) if self.gateway_resolver else self.gateway
        )
        await self.workflow.update_agent_run(run.id, ExecutionStatus.RUNNING)
        try:
            context = await self.context_builder.build(task)
            agent_result = await ReviewerAgent(gateway).run(AgentExecutionContext(
                task_id=task_id, agent_run_id=run.id, workspace_id=task.workspace_id,
                user_id=user_id, role=AgentRole.REVIEWER, workspace_root="",
                user_prompt=json.dumps(context, default=str),
            ))
            data = agent_result["report"]
            report = ReviewerReport(id=uuid4(), task_id=task_id, agent_run_id=run.id,
                created_at=datetime.now(timezone.utc), **data)
            await self.repository.add(report)
            await self.workflow.update_agent_run(run.id, ExecutionStatus.SUCCESS)
            current = await self.workflow.get_task(task_id, user_id)
            await self.workflow.transition(task_id, WorkflowState.COMPLETED, ActorType.SYSTEM, None,
                "Reviewer submitted final report", {"reviewer_report_id": str(report.id)},
                expected_version=current.version)
            return report
        except Exception as exc:
            await self.workflow.update_agent_run(run.id, ExecutionStatus.FAILED, error_message=str(exc))
            # Deliberately do not transition: failed reviews remain REVIEWING for retry.
            if isinstance(exc, ReviewerExecutionError):
                raise
            raise ReviewerExecutionError("Reviewer execution failed.") from exc
