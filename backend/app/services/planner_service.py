"""Planner orchestration: context, gateway call, validation, and persistence."""

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from backend.app.ai.gateway import AIGateway, AIRequest
from backend.app.ai.groq import GroqGateway
from backend.app.agents.base import AgentExecutionContext
from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.planner import ImplementationPlan, PersistedPlan
from backend.app.services.planner_context import PlannerContextBuilder
from backend.app.services.task_service import workflow_engine
from backend.app.workflow.states import WorkflowState


class PlannerExecutionError(RuntimeError):
    pass


class PlannerService:
    def __init__(self, gateway: Optional[AIGateway] = None, context_builder=None, gateway_resolver=None,
                 runtime_resolver=None, workflow=None):
        self.gateway = gateway or GroqGateway()
        self.gateway_resolver = gateway_resolver
        self.runtime_resolver = runtime_resolver
        self.workflow = workflow
        self.context_builder = context_builder or PlannerContextBuilder(
            workspace_service=(self.workflow or workflow_engine).workspace_service
        )

    async def execute(self, task_id: UUID, user_id: UUID, revision_feedback: Optional[str] = None) -> PersistedPlan:
        workflow = self.workflow or workflow_engine
        task = await workflow.get_task(task_id, user_id)
        if task.status == WorkflowState.PLAN_REVIEW and not revision_feedback:
            existing_plans = await workflow.list_plans(task_id, user_id)
            if existing_plans:
                return existing_plans[-1]
        if task.status.value != "planning":
            raise PlannerExecutionError("Task must be in PLANNING before Planner execution.")
        try:
            if self.runtime_resolver and getattr(self.runtime_resolver, "repository", None):
                await self.runtime_resolver.hydrate()
            runtime = (self.runtime_resolver.resolve(
                user_id, task.workspace_id, task.id, AgentRole.PLANNER.value
            ) if self.runtime_resolver else None)
        except (LookupError, PermissionError) as exc:
            raise PlannerExecutionError(str(exc)) from exc
        gateway = runtime.gateway if runtime else (
            self.gateway_resolver(task, user_id) if self.gateway_resolver else self.gateway
        )
        prior_runs = await workflow.list_agent_runs(task_id, user_id)
        prior_plan = (await workflow.list_plans(task_id, user_id))[-1:] if prior_runs else []
        if (
            not revision_feedback
            and any(r.agent_role == AgentRole.PLANNER and r.status == ExecutionStatus.SUCCESS for r in prior_runs)
            and prior_plan
            and datetime.fromisoformat(prior_plan[0].created_at) >= task.updated_at
        ):
            return prior_plan[0]
        run = await workflow.create_agent_run(
            task_id, user_id, AgentRole.PLANNER,
            **(runtime.run_metadata() if runtime else {}),
        )
        await workflow.update_agent_run(run.id, ExecutionStatus.RUNNING)
        try:
            context = await self.context_builder.build(task)
            prompt = json.dumps({"context": context, "revision_feedback": revision_feedback})
            response = await gateway.generate(AIRequest(
                system_prompt=(
                    "You are a read-only software engineering planner. Return only JSON matching "
                    "this schema: " + json.dumps(ImplementationPlan.model_json_schema()) +
                    ". Never propose edits outside the supplied context."
                ),
                user_prompt=prompt,
            ))
            try:
                plan = ImplementationPlan.model_validate_json(response.content)
            except (ValueError, TypeError) as exc:
                raise PlannerExecutionError("Planner returned invalid structured output.") from exc
            existing = await workflow.list_plans(task_id, user_id)
            persisted = PersistedPlan(
                id=uuid4(), task_id=task_id, agent_run_id=run.id,
                revision_number=len(existing) + 1, plan=plan,
                source_snapshot_hash=task.approved_snapshot_hash,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            await workflow.save_plan(persisted)
            await workflow.add_message(
                task_id, "agent", plan.understanding,
                {"agent_role": AgentRole.PLANNER.value, "plan_id": str(persisted.id)},
            )
            await workflow.update_agent_run(
                run.id, ExecutionStatus.SUCCESS,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                metadata=response.metadata,
            )
            return persisted
        except Exception as exc:
            await workflow.update_agent_run(
                run.id, ExecutionStatus.FAILED, metadata={"error": str(exc)}
            )
            if isinstance(exc, PlannerExecutionError):
                raise
            raise PlannerExecutionError("Planner execution failed.") from exc


from backend.app.services.runtime import RuntimeRef
planner_service = RuntimeRef("agents.planner")
