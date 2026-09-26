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
                 sandbox: BaseSandboxDriver):
        self.workflow = workflow
        self.repository = repository
        self.sandbox = sandbox

    async def plan_and_execute(self, task_id: UUID, user_id: UUID):
        task = await self.workflow.get_task(task_id, user_id)
        if task.status != WorkflowState.TEST_PLANNING:
            raise ValueError("Task must be in TEST_PLANNING before test execution.")
        architect_run = await self.workflow.create_agent_run(
            task_id, user_id, AgentRole.TEST_ARCHITECT
        )
        await self.workflow.update_agent_run(architect_run.id, ExecutionStatus.RUNNING)
        plan = await TestArchitectService(self.repository).create_plan(
            task_id, architect_run.id, task.objective
        )
        await self.workflow.update_agent_run(architect_run.id, ExecutionStatus.SUCCESS)
        task = await self.workflow.transition(
            task_id, WorkflowState.TEST_EXECUTING, ActorType.SYSTEM, None,
            "Test plan generated", {"test_plan_id": str(plan.id)},
            expected_version=task.version,
        )
        executor_run = await self.workflow.create_agent_run(
            task_id, user_id, AgentRole.TEST_EXECUTOR
        )
        await self.workflow.update_agent_run(executor_run.id, ExecutionStatus.RUNNING)
        workspace = await self.workflow.workspace_service.get_workspace(
            task.workspace_id, user_id
        )
        try:
            execution = await TestExecutorService(
                self.repository, self.sandbox
            ).execute(
                task_id, executor_run.id, workspace.id, workspace.canonical_root_path, plan
            )
            status = WorkflowState.REVIEWING if execution.all_passed else WorkflowState.REPAIRING
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
            if current.status == WorkflowState.TEST_EXECUTING:
                await self.workflow.transition(
                    task_id, WorkflowState.REPAIRING, ActorType.SYSTEM, None,
                    "Test execution failed", {"error": str(exc)},
                    expected_version=current.version,
                )
            raise
