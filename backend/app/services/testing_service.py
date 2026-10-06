"""Phase 8 testing orchestration.

The architect only reads persisted plans.  The executor is deliberately
dependent on BaseSandboxDriver so commands never run on the application host.
"""

import json
from datetime import datetime, timezone
from backend.app.ai.gateway import AIRequest
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
    def __init__(self, repository: TestingRepository, gateway=None):
        self.repository = repository
        self.gateway = gateway

    async def get_plan(self, task_id: UUID) -> Optional[TestPlan]:
        plans = await self.repository.list_plans(task_id)
        return plans[-1] if plans else None

    async def create_plan(
        self, task_id: UUID, agent_run_id: UUID, objective: str,
        affected_files: Iterable[str] = (), context=None, execution_platform="posix",
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
        if self.gateway is not None:
            from backend.app.analysis.sanitizer import redact_secrets
            response = await self.gateway.generate(AIRequest(
                system_prompt=("You are a read-only test architect. Return only JSON with a test_cases array. "
                    "Each case must have category (functional, regression, edge_case, security, integration), title, "
                    "description, expected_result, and test_code. test_code must be an executable shell "
                    "command that asserts behavior and exits nonzero on failure. Commands run only in "
                    f"the project working directory using {execution_platform} shell syntax. Do not return echo-only or manual "
                    "checks. Do not assume secrets or external services exist. Use the supplied source "
                    "and approved plan. Never change mandatory baseline checks."),
                user_prompt=redact_secrets(json.dumps({"objective": objective, "context": context or {}}))[:180000],
            ))
            generated = json.loads(response.content)
            raw_cases = generated.get("test_cases", [])
            if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 20:
                raise ValueError("Test architect must produce 1–20 executable tests.")
            test_cases = [TestCase(id=uuid4(), test_plan_id=plan_id, created_at=now, **item)
                          for item in raw_cases]
            if any(not case.test_code.strip() for case in test_cases):
                raise ValueError("Test architect returned an empty command.")
            return await self.repository.add_plan(TestPlan(
                id=plan_id, task_id=task_id, agent_run_id=agent_run_id,
                plan_summary="Executable checks for the approved implementation.",
                test_cases=test_cases, created_at=now,
            ))
        test_cases = [
            TestCase(
                id=uuid4(), test_plan_id=plan_id, category=category,
                title=title, description=description, expected_result=expected,
                test_code="",
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
                "status": ExecutionStatus.UNAVAILABLE,
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
        sandbox_id = None
        self._execution_id = execution.id
        self._task_id = task_id
        self._commands = []
        failures = []
        try:
            sandbox_id = await self.sandbox.create_sandbox(workspace_id, staging_root, self.limits)
            baseline_results = []
            for check in self.BASELINE_CHECKS:
                result = await self._run_check(sandbox_id, execution.id, check)
                baseline_results.append(result)
                await self.repository.add_build_result(result)
                if result.status not in (ExecutionStatus.SUCCESS, ExecutionStatus.NOT_APPLICABLE):
                    failures.append(FailedCheckDetail(
                        check_name=check.value, error_summary="Baseline check failed",
                        exit_code=result.exit_code, traceback_or_logs=result.stderr_output or result.stdout_output or "",
                        command=self.baseline_commands.get(check), stdout=result.stdout_output or "", stderr=result.stderr_output or "", sandbox_id=sandbox_id,
                    ))
            passed = failed = 0
            # Do not run authored tests after a mandatory baseline failure. This
            # prevents misleading results and keeps the repair loop deterministic.
            baseline_failed = bool(failures)
            if not baseline_failed:
                for case in plan.test_cases:
                    if not case.test_code.strip():
                        failed += 1
                        failures.append(FailedCheckDetail(check_name=case.title,
                            error_summary="Test is not executable", exit_code=-1,
                            traceback_or_logs="Configure a test architect worker to generate executable assertions."))
                        continue
                    result = await self._execute_command(
                        sandbox_id, SandboxCommand(cmd=case.test_code, timeout_seconds=self.limits.timeout_seconds)
                    )
                    if result.exit_code == 0 and not result.timed_out:
                        passed += 1
                    else:
                        failed += 1
                        failures.append(FailedCheckDetail(
                            check_name=case.title, error_summary="Test case failed",
                            exit_code=result.exit_code, traceback_or_logs=result.stderr or result.stdout,
                            command=case.test_code, stdout=result.stdout, stderr=result.stderr, sandbox_id=sandbox_id,
                        ))
            if not plan.test_cases:
                failures.append(FailedCheckDetail(check_name='generated_tests', error_summary='No executable test cases',
                    exit_code=-1, traceback_or_logs='Verification cannot pass without generated tests.'))
            all_passed = not failures
            final = execution.model_copy(update={
                "status": ExecutionStatus.SUCCESS if all_passed else ExecutionStatus.FAILED,
                "all_passed": all_passed, "total_tests": len(plan.test_cases),
                "passed_tests": passed, "failed_tests": failed,
                "execution_duration_ms": int((monotonic() - started) * 1000),
                "baseline_results": baseline_results, "command_results": self._commands,
                "failure_report": None if all_passed else FailureReport(
                    summary="Mandatory baseline checks or test cases failed.",
                    execution_id=execution.id, attempt=len(await self.repository.list_executions(task_id)),
                    failed_baseline_checks=[f for f in failures if f.check_name in {c.value for c in self.BASELINE_CHECKS}],
                    failed_test_cases=[f for f in failures if f.check_name not in {c.value for c in self.BASELINE_CHECKS}],
                ),
            })
            await self.repository.add_execution(final)
            return final
        except BaseException as exc:
            import asyncio
            reason = 'Execution cancelled.' if isinstance(exc, asyncio.CancelledError) else 'Sandbox execution unavailable.'
            failed = execution.model_copy(update={'command_results': self._commands,
                'status': ExecutionStatus.CANCELLED if isinstance(exc, asyncio.CancelledError) else ExecutionStatus.UNAVAILABLE,
                'failure_report': FailureReport(summary=reason, execution_id=execution.id),
                'execution_duration_ms': int((monotonic() - started) * 1000)})
            await self.repository.add_execution(failed)
            raise
        finally:
            if sandbox_id is not None:
                await self.sandbox.destroy_sandbox(sandbox_id)

    async def _execute_command(self, sandbox_id, command):
        from backend.app.analysis.sanitizer import redact_secrets
        import asyncio
        started = _now()
        began = monotonic()
        last_flush = began
        output = {'stdout': '', 'stderr': ''}
        evidence = {'command_id': str(uuid4()), 'execution_id': str(self._execution_id),
                    'task_id': str(self._task_id), 'sandbox_id': sandbox_id,
                    'command': redact_secrets(command.cmd)[:16000], 'status': 'running',
                    'exit_code': None, 'stdout': '', 'stderr': '', 'duration_ms': 0,
                    'started_at': started.isoformat(), 'completed_at': None}
        await self.repository.add_command_result(self._execution_id, evidence)
        async def receive(stream, chunk):
            nonlocal last_flush
            if stream not in output:
                return
            output[stream] = (output[stream] + chunk[:64000])[:64000]
            if monotonic() - last_flush >= 1:
                # Incomplete lines wait for completion so split secrets aren't emitted.
                for key, value in output.items():
                    evidence[key] = redact_secrets(value.rsplit('\n', 1)[0] if '\n' in value else '')[:64000]
                evidence['duration_ms'] = int((monotonic()-began)*1000)
                await self.repository.add_command_result(self._execution_id, dict(evidence))
                last_flush = monotonic()
        try:
            result = await self.sandbox.execute_command_observed(sandbox_id, command, receive)
            result = result.model_copy(update={'stdout': redact_secrets(result.stdout)[:64000],
                                              'stderr': redact_secrets(result.stderr)[:64000]})
            evidence.update(status='timeout' if result.timed_out else 'success' if result.exit_code == 0 else 'failed',
                exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr, duration_ms=result.duration_ms)
            return result
        except BaseException as exc:
            evidence.update(status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'unavailable',
                stdout=redact_secrets(output['stdout'])[:64000], stderr=redact_secrets(output['stderr'])[:64000],
                duration_ms=int((monotonic()-began)*1000))
            raise
        finally:
            evidence['completed_at'] = _now().isoformat()
            self._commands.append(dict(evidence))
            await self.repository.add_command_result(self._execution_id, evidence)

    async def _run_check(self, sandbox_id: str, execution_id: UUID,
                         check: BaselineCheckType) -> BuildResult:
        command = self.baseline_commands.get(check)
        if not command:
            return BuildResult(id=uuid4(), test_execution_id=execution_id, check_type=check,
                               status=ExecutionStatus.NOT_APPLICABLE, exit_code=0,
                               stdout_output="No command configured for this project.",
                               duration_ms=0, created_at=_now())
        result = await self._execute_command(
            sandbox_id, SandboxCommand(cmd=command, timeout_seconds=self.limits.timeout_seconds)
        )
        status = ExecutionStatus.SUCCESS if result.exit_code == 0 and not result.timed_out else (
            ExecutionStatus.TIMEOUT if result.timed_out else ExecutionStatus.FAILED
        )
        return BuildResult(id=uuid4(), test_execution_id=execution_id, check_type=check,
                           status=status, exit_code=result.exit_code,
                           stdout_output=result.stdout, stderr_output=result.stderr,
                           duration_ms=result.duration_ms, created_at=_now())
