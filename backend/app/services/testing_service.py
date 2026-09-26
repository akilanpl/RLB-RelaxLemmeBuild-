"""Phase 8 testing orchestration.

The architect only reads persisted plans.  The executor is deliberately
dependent on BaseSandboxDriver so commands never run on the application host.
"""

from datetime import datetime, timezone
from time import monotonic
from typing import Dict, Iterable, Optional
from uuid import UUID, uuid4

from backend.app.agents.base import AgentExecutionContext
from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.test import (
    BaselineCheckType, BuildResult, FailedCheckDetail, FailureReport,
    TestCase, TestExecution, TestPlan,
)
from backend.app.repositories.testing import InMemoryTestingRepository, TestingRepository
from backend.app.sandbox.base import BaseSandboxDriver
from backend.app.sandbox.types import SandboxCommand, SandboxLimits
from backend.app.core.permissions import AgentPermissionGatekeeper


def _now():
    return datetime.now(timezone.utc)


class TestArchitectService:
    def __init__(self, repository: TestingRepository):
        self.repository = repository

    async def get_plan(self, task_id: UUID) -> Optional[TestPlan]:
        plans = await self.repository.list_plans(task_id)
        return plans[-1] if plans else None

    async def create_plan(
        self, task_id: UUID, agent_run_id: UUID, objective: str,
        affected_files: Iterable[str] = (),
    ) -> TestPlan:
        AgentPermissionGatekeeper.assert_tool_permitted(
            AgentRole.TEST_ARCHITECT, "submit_test_plan"
        )
        plan_id = uuid4()
        now = _now()
        files = list(affected_files)
        cases = [
            ("functional", "Verify the requested behavior", objective, "The requested behavior works as described."),
            ("regression", "Run the existing regression suite", "Run the existing project tests.", "Existing tests continue to pass."),
            ("edge_case", "Validate invalid and boundary inputs", "Exercise invalid, empty, and boundary inputs.", "Invalid inputs are handled safely."),
            ("security", "Verify authorization boundaries", "Attempt unauthorized access and mutation paths.", "Unauthorized operations are rejected."),
        ]
        test_cases = [
            TestCase(
                id=uuid4(), test_plan_id=plan_id, category=category,
                title=title, description=description, expected_result=expected,
                test_code="echo 'manual test case: " + title.replace("'", "") + "'",
                created_at=now,
            )
            for category, title, description, expected in cases
        ]
        plan = TestPlan(
            id=plan_id, task_id=task_id, agent_run_id=agent_run_id,
            plan_summary=f"Test requested behavior and affected files: {', '.join(files) or 'project-wide'}",
            test_cases=test_cases, created_at=now,
        )
        return await self.repository.add_plan(plan)


class TestExecutorService:
    BASELINE_CHECKS = (
        BaselineCheckType.DEPENDENCY_INSTALL,
        BaselineCheckType.TYPE_CHECK,
        BaselineCheckType.LINT,
        BaselineCheckType.PRODUCTION_BUILD,
        BaselineCheckType.UNIT_INTEGRATION_TESTS,
        BaselineCheckType.HEALTH_CHECK,
    )

    def __init__(self, repository: TestingRepository, sandbox: BaseSandboxDriver,
                 baseline_commands: Optional[Dict[BaselineCheckType, str]] = None,
                 limits: Optional[SandboxLimits] = None):
        self.repository = repository
        self.sandbox = sandbox
        self.baseline_commands = baseline_commands or {}
        self.limits = limits or SandboxLimits()

    async def execute(self, task_id: UUID, agent_run_id: UUID, workspace_id: UUID,
                      staging_root: str, plan: Optional[TestPlan] = None) -> TestExecution:
        AgentPermissionGatekeeper.assert_tool_permitted(
            AgentRole.TEST_EXECUTOR, "run_sandbox_command"
        )
        plan = plan or (await TestArchitectService(self.repository).get_plan(task_id))
        if plan is None:
            raise ValueError("No persisted test plan exists for this task.")
        prior = [
            execution for execution in await self.repository.list_executions(task_id)
            if execution.agent_run_id == agent_run_id
        ]
        if prior:
            return prior[-1]
        started = monotonic()
        execution = TestExecution(id=uuid4(), task_id=task_id, agent_run_id=agent_run_id,
                                  created_at=_now())
        await self.repository.add_execution(execution)
        if self.sandbox is None or not staging_root or not staging_root.strip():
            reason = (
                "Test Executor requires an isolated sandbox driver."
                if self.sandbox is None
                else "Test Executor requires an isolated staging workspace."
            )
            failed = execution.model_copy(update={
                "execution_duration_ms": int((monotonic() - started) * 1000),
                "failure_report": FailureReport(
                    summary=reason,
                    failed_baseline_checks=[FailedCheckDetail(
                        check_name="sandbox_configuration",
                        error_summary=reason,
                        exit_code=-1,
                        traceback_or_logs="No project command was executed.",
                    )],
                ),
            })
            await self.repository.add_execution(failed)
            raise RuntimeError(reason)
        sandbox_id = await self.sandbox.create_sandbox(workspace_id, staging_root, self.limits)
        failures = []
        try:
            baseline_results = []
            for check in self.BASELINE_CHECKS:
                result = await self._run_check(sandbox_id, execution.id, check)
                baseline_results.append(result)
                await self.repository.add_build_result(result)
                if result.status not in (ExecutionStatus.SUCCESS, ExecutionStatus.NOT_APPLICABLE):
                    failures.append(FailedCheckDetail(
                        check_name=check.value, error_summary="Baseline check failed",
                        exit_code=result.exit_code, traceback_or_logs=result.stderr_output or result.stdout_output or "",
                    ))
            passed = failed = 0
            # Do not run authored tests after a mandatory baseline failure. This
            # prevents misleading results and keeps the repair loop deterministic.
            baseline_failed = bool(failures)
            if not baseline_failed:
                for case in plan.test_cases:
                    result = await self.sandbox.execute_command(
                        sandbox_id, SandboxCommand(cmd=case.test_code, timeout_seconds=self.limits.timeout_seconds)
                    )
                    if result.exit_code == 0:
                        passed += 1
                    else:
                        failed += 1
                        failures.append(FailedCheckDetail(
                            check_name=case.title, error_summary="Test case failed",
                            exit_code=result.exit_code, traceback_or_logs=result.stderr or result.stdout,
                        ))
            all_passed = not failures
            final = execution.model_copy(update={
                "all_passed": all_passed, "total_tests": len(plan.test_cases),
                "passed_tests": passed, "failed_tests": failed,
                "execution_duration_ms": int((monotonic() - started) * 1000),
                "baseline_results": baseline_results,
                "failure_report": None if all_passed else FailureReport(
                    summary="Mandatory baseline checks or test cases failed.",
                    failed_baseline_checks=[f for f in failures if f.check_name in {c.value for c in self.BASELINE_CHECKS}],
                    failed_test_cases=[f for f in failures if f.check_name not in {c.value for c in self.BASELINE_CHECKS}],
                ),
            })
            await self.repository.add_execution(final)
            return final
        finally:
            await self.sandbox.destroy_sandbox(sandbox_id)

    async def _run_check(self, sandbox_id: str, execution_id: UUID,
                         check: BaselineCheckType) -> BuildResult:
        command = self.baseline_commands.get(check)
        if not command:
            return BuildResult(id=uuid4(), test_execution_id=execution_id, check_type=check,
                               status=ExecutionStatus.NOT_APPLICABLE, exit_code=0,
                               stdout_output="No command configured for this project.",
                               duration_ms=0, created_at=_now())
        result = await self.sandbox.execute_command(
            sandbox_id, SandboxCommand(cmd=command, timeout_seconds=self.limits.timeout_seconds)
        )
        status = ExecutionStatus.SUCCESS if result.exit_code == 0 else (
            ExecutionStatus.TIMEOUT if result.timed_out else ExecutionStatus.FAILED
        )
        return BuildResult(id=uuid4(), test_execution_id=execution_id, check_type=check,
                           status=status, exit_code=result.exit_code,
                           stdout_output=result.stdout, stderr_output=result.stderr,
                           duration_ms=result.duration_ms, created_at=_now())
