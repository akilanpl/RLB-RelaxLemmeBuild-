"""Orchestration boundary for Phase 8 test planning and execution."""

from typing import Optional
from uuid import UUID

from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.task import ActorType
from backend.app.services.task_service import WorkflowEngine
from backend.app.services.testing_service import TestArchitectService, TestExecutorService
from backend.app.sandbox.base import BaseSandboxDriver
from backend.app.repositories.testing import TestingRepository
from backend.app.workflow.states import WorkflowState


class TestOrchestrationService:
    def __init__(self, workflow: WorkflowEngine, repository: TestingRepository,
                 sandbox: BaseSandboxDriver, runtime_resolver=None, proposals=None):
        self.workflow = workflow
        self.repository = repository
        self.sandbox = sandbox
        self.runtime_resolver = runtime_resolver
        self.proposals = proposals

    async def plan_and_execute(self, task_id: UUID, user_id: UUID):
        task = await self.workflow.get_task(task_id, user_id)
        if self.sandbox is None:
            raise RuntimeError("Configure Daytona to execute tests in an isolated sandbox.")
        if task.status not in {WorkflowState.TEST_PLANNING, WorkflowState.TEST_EXECUTING}:
            raise ValueError("Task must be in test planning or execution.")
        if task.status == WorkflowState.TEST_PLANNING:
            runtime = (self.runtime_resolver.resolve(user_id, task.workspace_id, task.id,
                       AgentRole.TEST_ARCHITECT.value) if self.runtime_resolver else None)
            architect_run = await self.workflow.create_agent_run(
                task_id, user_id, AgentRole.TEST_ARCHITECT,
                **(runtime.run_metadata() if runtime else {}),
            )
            await self.workflow.update_agent_run(architect_run.id, ExecutionStatus.RUNNING)
            try:
                from backend.app.services.planner_context import PlannerContextBuilder
                context = await PlannerContextBuilder(self.workflow.workspace_service).build(task)
                context["approved_plans"] = [p.model_dump(mode="json") for p in
                    await self.workflow.list_plans(task_id, user_id)]
                if self.proposals is not None:
                    proposals = await self.proposals.list_by_task(task_id)
                    context['approved_changes'] = [p.model_dump(mode='json') for p in proposals[:1]]
                plan = await TestArchitectService(self.repository, runtime.gateway if runtime else None).create_plan(
                    task_id, architect_run.id, task.objective, context=context,
                )
                await self.workflow.update_agent_run(architect_run.id, ExecutionStatus.SUCCESS)
            except Exception:
                await self.workflow.update_agent_run(architect_run.id, ExecutionStatus.FAILED,
                    error_message="Test planning failed.")
                raise
            task = await self.workflow.transition(
                task_id, WorkflowState.TEST_EXECUTING, ActorType.SYSTEM, None,
                "Test plan generated", {"test_plan_id": str(plan.id)}, expected_version=task.version,
            )
        else:
            plan = await TestArchitectService(self.repository).get_plan(task_id)
            if plan is None:
                raise ValueError("Persisted test plan missing for resumed execution.")
        executor_run = await self.workflow.create_agent_run(
            task_id, user_id, AgentRole.TEST_EXECUTOR
        )
        await self.workflow.update_agent_run(executor_run.id, ExecutionStatus.RUNNING)
        workspace = await self.workflow.workspace_service.get_workspace(
            task.workspace_id, user_id
        )
        try:
            from backend.app.services.baseline_commands import discover_baseline_commands
            commands = await discover_baseline_commands(
                self.workflow.workspace_service.storage, workspace.canonical_root_path)
            from backend.app.core.config import get_settings
            from backend.app.sandbox.types import SandboxLimits
            execution = await TestExecutorService(
                self.repository, self.sandbox, baseline_commands=commands,
                limits=SandboxLimits(allowed_domains=get_settings().SANDBOX_ALLOWED_DOMAINS)
            ).execute(
                task_id, executor_run.id, workspace.id, workspace.canonical_root_path, plan
            )
            history = await self.workflow.get_history(task_id, user_id)
            repair_count = sum(item.new_state == WorkflowState.REPAIRING for item in history)
            status = (WorkflowState.REVIEWING if execution.all_passed else
                      WorkflowState.FAILED if repair_count >= get_settings().MAX_REPAIR_ATTEMPTS else
                      WorkflowState.REPAIRING)
            await self.workflow.update_agent_run(
                executor_run.id,
                ExecutionStatus.SUCCESS if execution.all_passed else ExecutionStatus.FAILED,
            )
            current = await self.workflow.get_task(task_id, user_id)
            await self.workflow.transition(
                task_id, status, ActorType.SYSTEM, None,
                "Test execution completed",
                {"test_execution_id": str(execution.id), "passed": execution.all_passed},
                expected_version=current.version,
            )
            return execution
        except Exception as exc:
            await self.workflow.update_agent_run(
                executor_run.id, ExecutionStatus.FAILED, error_message=str(exc)
            )
            current = await self.workflow.get_task(task_id, user_id)
            from backend.app.services.durable_worker import _transient
            if current.status == WorkflowState.TEST_EXECUTING and not _transient(exc):
                await self.workflow.transition(
                    task_id, WorkflowState.FAILED, ActorType.SYSTEM, None,
                    "Sandbox execution failed", {"error": str(exc)},
                    expected_version=current.version,
                )
            raise
