from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.models.test import TestCase as Case, TestCaseCategory as Category, TestPlan as Plan
from backend.app.agents.base import AgentExecutionContext
from backend.app.agents.test_executor import TestExecutorAgent as ExecutorAgent
from backend.app.models.agent import AgentRole
from backend.app.repositories.testing import InMemoryTestingRepository
from backend.app.sandbox.base import BaseSandboxDriver
from backend.app.sandbox.types import SandboxCommand, SandboxExecutionResult, SandboxLimits
from backend.app.services.testing_service import TestArchitectService as Architect, TestExecutorService as Executor


class FakeSandbox(BaseSandboxDriver):
    def __init__(self, exit_code=0):
        self.commands = []
        self.exit_code = exit_code

    async def create_sandbox(self, workspace_id, staging_root_path, limits):
        return "sandbox"

    async def execute_command(self, sandbox_id, command: SandboxCommand):
        self.commands.append(command.cmd)
        return SandboxExecutionResult(exit_code=self.exit_code, stdout="ok", stderr="failed" if self.exit_code else "", duration_ms=1)

    async def stream_command_output(self, sandbox_id, command):
        yield ""

    async def destroy_sandbox(self, sandbox_id):
        pass


@pytest.mark.asyncio
async def test_architect_reads_existing_plan_and_executor_runs_baseline_before_cases():
    repository = InMemoryTestingRepository()
    now = datetime.now(timezone.utc)
    plan = Plan(
        id=uuid4(), task_id=uuid4(), agent_run_id=uuid4(), plan_summary="existing",
        created_at=now, test_cases=[Case(
            id=uuid4(), test_plan_id=uuid4(), category=Category.FUNCTIONAL,
            title="smoke", description="smoke", expected_result="ok", test_code="pytest tests",
            created_at=now,
        )],
    )
    # Keep the foreign key-shaped test_case reference aligned with the plan.
    plan.test_cases[0].test_plan_id = plan.id
    await repository.add_plan(plan)
    assert await Architect(repository).get_plan(plan.task_id) == plan

    sandbox = FakeSandbox()
    execution = await Executor(repository, sandbox).execute(
        plan.task_id, uuid4(), uuid4(), "staging"
    )
    assert execution.all_passed
    assert execution.total_tests == 1
    assert len(execution.baseline_results) == 6
    assert all(result.status.value == "not_applicable" for result in execution.baseline_results)
    assert sandbox.commands[-1] == "pytest tests"


@pytest.mark.asyncio
async def test_executor_fails_closed_without_sandbox_or_staging():
    repository = InMemoryTestingRepository()
    now = datetime.now(timezone.utc)
    plan = Plan(
        id=uuid4(), task_id=uuid4(), agent_run_id=uuid4(), plan_summary="existing",
        created_at=now,
    )
    await repository.add_plan(plan)
    with pytest.raises(RuntimeError, match="isolated sandbox"):
        await Executor(repository, None).execute(plan.task_id, uuid4(), uuid4(), "staging")
    assert len(repository.executions) == 1
    assert next(iter(repository.executions.values())).failure_report is not None

    agent = ExecutorAgent(repository=repository, sandbox=FakeSandbox())
    context = AgentExecutionContext(
        task_id=uuid4(), agent_run_id=uuid4(), role=AgentRole.TEST_EXECUTOR,
        workspace_root="approved", user_prompt="run tests",
    )
    with pytest.raises(RuntimeError, match="staging workspace"):
        await agent.execute(context)


@pytest.mark.asyncio
async def test_baseline_failure_blocks_custom_tests_and_reports_repair_data():
    repository = InMemoryTestingRepository()
    now = datetime.now(timezone.utc)
    plan = Plan(
        id=uuid4(), task_id=uuid4(), agent_run_id=uuid4(), plan_summary="existing",
        created_at=now, test_cases=[Case(
            id=uuid4(), test_plan_id=uuid4(), category=Category.FUNCTIONAL,
            title="must not run", description="case", expected_result="ok",
            test_code="custom-test", created_at=now,
        )],
    )
    plan.test_cases[0].test_plan_id = plan.id
    await repository.add_plan(plan)
    sandbox = FakeSandbox(exit_code=1)
    execution = await Executor(
        repository, sandbox, baseline_commands={next(iter(Executor.BASELINE_CHECKS)): "baseline"}
    ).execute(plan.task_id, uuid4(), uuid4(), "staging")
    assert not execution.all_passed
    assert execution.failed_tests == 0
    assert sandbox.commands == ["baseline"]
    assert execution.failure_report and execution.failure_report.failed_baseline_checks
