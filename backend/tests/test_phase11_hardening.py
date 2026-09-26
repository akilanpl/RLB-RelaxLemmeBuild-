import io
import json
import zipfile

import pytest
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

from backend.app.services.zip_import import ZipImportService, ZipValidationError
from backend.app.services.orphan_detector import find_orphaned_state
from backend.app.models.agent import ExecutionStatus
from backend.app.services.planner_context import _safe
from backend.app.ai.gateway import AIGatewayError, AIRequest, AIResponse, QuotaGuardedGateway
from backend.app.services.testing_service import TestExecutorService as ExecutorService
from backend.app.repositories.testing import InMemoryTestingRepository
from backend.app.services.task_service import WorkflowEngine, WorkflowConflictError, TaskAccessDeniedError
from backend.app.models.workspace import Workspace
from backend.app.models.task import ActorType
from backend.app.workflow.states import WorkflowState
from backend.app.ai.gateway import ProviderGateway
from backend.app.models.audit import ReviewerReport, ReviewRecommendation
from backend.app.services.workspace_service import WorkspaceService, WorkspaceAccessDeniedError
from backend.app.storage.local import LocalStorageBackend
from backend.app.services.reviewer_service import ReviewerService
from backend.app.models.agent import AgentRole


def test_duplicate_zip_paths_are_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("src/app.py", "one")
        archive.writestr("src/app.py", "two")
    with pytest.raises(ZipValidationError, match="Duplicate"):
        entries = ZipImportService.sanitize_and_inspect_members(
            ZipImportService.validate_zip_stream(buffer.getvalue())
        )
        ZipImportService.extract_entries(
            ZipImportService.validate_zip_stream(buffer.getvalue()), entries
        )


def test_orphan_detector_reports_without_mutating_state():
    run = SimpleNamespace(id="run-1", started_at=datetime.now(timezone.utc),
                          completed_at=None, status=ExecutionStatus.RUNNING)
    report = find_orphaned_state(agent_runs=[run])
    assert report["incomplete_agent_runs"] == [
        {"id": "run-1", "reason": "agent run remains running without completion"}
    ]


def test_orphan_detector_reports_stale_repairing_tasks_only():
    stale = SimpleNamespace(
        id="task-1",
        updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
        status=__import__("backend.app.workflow.states", fromlist=["WorkflowState"]).WorkflowState.REPAIRING,
    )
    fresh = SimpleNamespace(
        id="task-2", updated_at=datetime.now(timezone.utc),
        status=__import__("backend.app.workflow.states", fromlist=["WorkflowState"]).WorkflowState.REPAIRING,
    )
    report = find_orphaned_state(tasks=[stale, fresh])
    assert [item["id"] for item in report["abandoned_tasks"]] == ["task-1"]


def test_context_secret_redaction_marker_is_deterministic():
    value = _safe("sk-test-secret GROQ_TEST_SECRET Bearer token")
    assert "sk-test-secret" not in value
    assert "GROQ_TEST_SECRET" not in value
    assert "Bearer token" not in value


def test_quota_guard_is_safe_before_provider_call():
    class FakeAIGateway:
        calls = 0
        def validate_configuration(self): pass
        async def generate(self, request):
            self.calls += 1
            return AIResponse(content="{}")

    fake = FakeAIGateway()
    gateway = QuotaGuardedGateway(fake, max_calls=1, max_output_tokens=5)
    import asyncio
    asyncio.run(gateway.generate(AIRequest(system_prompt="s", user_prompt="u", max_tokens=1)))
    with pytest.raises(AIGatewayError, match="call limit"):
        asyncio.run(gateway.generate(AIRequest(system_prompt="s", user_prompt="u", max_tokens=1)))
    assert fake.calls == 1


def test_test_executor_has_no_host_execution_fallback():
    repository = InMemoryTestingRepository()
    assert ExecutorService(repository, None).sandbox is None


@pytest.mark.asyncio
async def test_deterministic_full_workflow_reconstructs_from_persisted_state():
    user = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)
    workspace = Workspace(
        id=__import__("uuid").uuid4(), user_id=user, name="e2e", slug="e2e",
        canonical_root_path="canonical", created_at=now, updated_at=now,
    )
    engine = WorkflowEngine()
    task = await engine.create_task(workspace, user, "task", "objective")
    path = [
        WorkflowState.PLANNING, WorkflowState.PLAN_REVIEW, WorkflowState.CODING,
        WorkflowState.CODE_REVIEW, WorkflowState.TEST_PLANNING,
        WorkflowState.TEST_EXECUTING, WorkflowState.REVIEWING, WorkflowState.COMPLETED,
    ]
    for state in path:
        task = await engine.transition(task.id, state, ActorType.SYSTEM, None, "deterministic test",
                                        expected_version=task.version)
    restored = await engine.get_task(task.id, user)
    assert restored.status == WorkflowState.COMPLETED
    assert [entry.new_state for entry in await engine.get_history(task.id, user)] == path


@pytest.mark.asyncio
async def test_duplicate_transition_and_cross_user_access_are_rejected():
    user = __import__("uuid").uuid4()
    other = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)
    workspace = Workspace(id=__import__("uuid").uuid4(), user_id=user, name="x", slug="x",
                          canonical_root_path="canonical", created_at=now, updated_at=now)
    engine = WorkflowEngine()
    task = await engine.create_task(workspace, user, "task", "objective")
    await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None, "start",
                            expected_version=task.version)
    with pytest.raises(TaskAccessDeniedError):
        await engine.get_task(task.id, other)
    with pytest.raises(Exception):
        await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None, "duplicate")


@pytest.mark.asyncio
async def test_provider_failures_are_normalized_without_secret_leakage():
    class FailingAdapter:
        provider_id = "fake"
        async def generate_completion(self, request, credentials):
            import httpx
            request = httpx.Request("POST", "https://provider.invalid")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("secret-provider-key", request=request, response=response)

    with pytest.raises(Exception, match="rate limit"):
        await ProviderGateway(FailingAdapter(), object(), "model").generate(
            __import__("backend.app.ai.gateway", fromlist=["AIRequest"]).AIRequest(
                system_prompt="s", user_prompt="u"
            )
        )


@pytest.mark.asyncio
async def test_core_workflow_restart_matrix_and_audit_history():
    user = __import__("uuid").uuid4()
    now = datetime.now(timezone.utc)
    workspace = Workspace(
        id=__import__("uuid").uuid4(), user_id=user, name="core", slug="core",
        canonical_root_path="canonical", created_at=now, updated_at=now,
    )
    from backend.app.repositories.task import InMemoryTaskRepository
    repository = InMemoryTaskRepository()
    engine = WorkflowEngine(repository=repository)
    task = await engine.create_task(workspace, user, "core", "core workflow")
    checkpoints = (
        WorkflowState.PLANNING, WorkflowState.PLAN_REVIEW, WorkflowState.CODING,
        WorkflowState.CODE_REVIEW, WorkflowState.TEST_PLANNING,
        WorkflowState.TEST_EXECUTING, WorkflowState.REPAIRING,
        WorkflowState.CODING, WorkflowState.CODE_REVIEW,
        WorkflowState.TEST_PLANNING, WorkflowState.TEST_EXECUTING,
        WorkflowState.REVIEWING, WorkflowState.COMPLETED,
    )
    for state in checkpoints:
        task = await engine.transition(
            task.id, state, ActorType.SYSTEM, user, f"critical {state.value}",
            expected_version=task.version,
        )
        reconstructed = WorkflowEngine(repository=repository)
        assert (await reconstructed.get_task(task.id, user)).status == state
    history = await engine.get_history(task.id, user)
    assert len(history) == len(checkpoints)
    assert all(item.actor_id == user for item in history)
    assert history[-1].new_state == WorkflowState.COMPLETED


@pytest.mark.asyncio
async def test_critical_idempotency_and_sandbox_fail_closed():
    from backend.app.sandbox.base import BaseSandboxDriver
    from backend.app.sandbox.types import SandboxExecutionResult
    repository = InMemoryTestingRepository()
    task_id, run_id, workspace_id = (__import__("uuid").uuid4() for _ in range(3))
    from backend.app.services.testing_service import TestArchitectService as Architect
    plan = await Architect(repository).create_plan(task_id, run_id, "verify")
    with pytest.raises(RuntimeError, match="isolated sandbox"):
        await ExecutorService(repository, None).execute(
            task_id, run_id, workspace_id, "staging", plan
        )
    executions = await repository.list_executions(task_id)
    assert len(executions) == 1

    class FakeSandbox(BaseSandboxDriver):
        calls = 0
        async def create_sandbox(self, workspace_id, staging_root_path, limits):
            return "sandbox"
        async def execute_command(self, sandbox_id, command):
            self.calls += 1
            return SandboxExecutionResult(exit_code=0, stdout="ok", stderr="", duration_ms=1)
        async def stream_command_output(self, sandbox_id, command):
            if False:
                yield ""
        async def destroy_sandbox(self, sandbox_id):
            return None

    sandbox = FakeSandbox()
    repository = InMemoryTestingRepository()
    plan = await Architect(repository).create_plan(task_id, run_id, "verify")
    executor = ExecutorService(repository, sandbox)
    first = await executor.execute(task_id, run_id, workspace_id, "staging", plan)
    calls = sandbox.calls
    second = await executor.execute(task_id, run_id, workspace_id, "staging", plan)
    assert second.id == first.id
    assert sandbox.calls == calls


@pytest.mark.asyncio
async def test_resolver_quota_is_reused_for_duplicate_logical_attempt(monkeypatch):
    from backend.app.models.provider import AgentWorkerMapping, Loadout, Worker
    from backend.app.models.agent import AgentRole
    from backend.app.providers.resolver import RuntimeResolver
    from backend.app.services.credential_service import CredentialService
    from backend.app.providers import resolver as resolver_module

    class FakeAdapter:
        provider_id = "fake"
        async def generate_completion(self, request, credentials):
            from backend.app.providers.types import ChatMessage, CompletionResponse, ModelUsage
            return CompletionResponse(
                id="fake-run", model=request.model,
                message=ChatMessage(role="assistant", content="{}"),
                usage=ModelUsage(), finish_reason="stop",
            )

    class FakeAdapterFactory:
        def __new__(cls, service):
            return FakeAdapter()

    monkeypatch.setitem(resolver_module.ADAPTER_REGISTRY, "fake", FakeAdapterFactory)
    user, workspace, task = (__import__("uuid").uuid4() for _ in range(3))
    credentials = CredentialService(b"a" * 32)
    resolver = RuntimeResolver(credentials, max_calls=1)
    worker = Worker(
        id="worker", provider_id="fake", model_name="model", context_window_tokens=10,
        max_output_tokens=10, created_at=datetime.now(timezone.utc),
    )
    resolver.register_worker(worker)
    resolver.register_credential(user, "fake", credentials.encrypt("secret"))
    loadout = Loadout(
        id=__import__("uuid").uuid4(), user_id=user, name="loadout",
        mappings={AgentRole.PLANNER: AgentWorkerMapping(primary_worker_id="worker")},
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    resolver.register_loadout(user, loadout)
    resolver.switch_loadout(user, workspace, loadout.id)
    assert resolver.audit_records[-1]["event"] == "loadout_switch"
    assert resolver.audit_records[-1]["loadout_id"] == str(loadout.id)
    first = resolver.resolve(user, workspace, task, AgentRole.PLANNER.value)
    second = resolver.resolve(user, workspace, task, AgentRole.PLANNER.value)
    assert first.gateway is second.gateway
    await first.gateway.generate(AIRequest(system_prompt="s", user_prompt="u"))
    with pytest.raises(AIGatewayError, match="call limit"):
        await second.gateway.generate(AIRequest(system_prompt="s", user_prompt="u"))


@pytest.mark.asyncio
async def test_planner_coder_reviewer_services_deduplicate_fake_ai_attempts(tmp_path):
    from backend.app.ai.gateway import AIGateway, QuotaGuardedGateway, AIResponse
    from backend.app.services.planner_service import PlannerService
    from backend.app.services.coder_service import CoderService
    from backend.app.services.staging_service import StagingService
    from backend.app.services.workspace_service import WorkspaceService
    from backend.app.services.reviewer_service import ReviewerService
    from backend.app.repositories.task import InMemoryTaskRepository
    from backend.app.repositories.proposal import InMemoryProposalRepository
    from backend.app.repositories.reviewer import InMemoryReviewerReportRepository

    class Context:
        async def build(self, *args):
            return {"objective": "change", "files": []}

    class FakeGateway(AIGateway):
        def __init__(self):
            self.calls = 0
        def validate_configuration(self):
            return None
        async def generate(self, request):
            self.calls += 1
            if "planner" in request.system_prompt:
                content = json.dumps({
                    "objective": "change", "understanding": "understood",
                    "implementation_steps": [{
                        "order": 1, "description": "change", "rationale": "needed",
                        "candidate_files": ["app.py"],
                    }],
                    "affected_files": ["app.py"], "expected_behavior": "changed",
                })
            elif "Coder" in request.system_prompt:
                content = json.dumps({
                    "summary": "change", "commit_message": "change",
                    "changes": [{"path": "app.py", "operation": "modify", "content": "new\n"}],
                    "impact": {"affected_files": ["app.py"], "risks": [], "tests": []},
                })
            else:
                content = json.dumps({
                    "summary": "complete", "strengths": [], "concerns": [],
                    "security_audit": "none", "recommendation": "ready_to_merge",
                })
            return AIResponse(content=content)

    user = __import__("uuid").uuid4()
    storage = LocalStorageBackend(tmp_path)
    workspaces = WorkspaceService(storage)
    workspace = await workspaces.create_workspace(user, "dedup")
    await storage.write_file(f"{workspace.canonical_root_path}/app.py", b"old\n")
    staging_service = StagingService(workspaces, storage)
    staging = await staging_service.create_staging_workspace(workspace.id, user)
    engine = WorkflowEngine(workspace_service=workspaces, repository=InMemoryTaskRepository())
    task = await engine.create_task(workspace, user, "change", "change")

    fake = FakeGateway()
    planner = PlannerService(
        QuotaGuardedGateway(fake, 2, 100), Context(), workflow=engine
    )
    task = await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None, "plan")
    first_plan = await planner.execute(task.id, user)
    second_plan = await planner.execute(task.id, user)
    assert first_plan.id == second_plan.id
    assert fake.calls == 1

    coder = CoderService(
        QuotaGuardedGateway(fake, 2, 100), staging_service=staging_service,
        context_builder=Context(), workflow=engine,
        proposal_repository=InMemoryProposalRepository(),
    )
    task = await engine.transition(task.id, WorkflowState.PLAN_REVIEW, ActorType.SYSTEM, None, "review")
    task = await engine.record_approval(task.id, user, "plan", "approved", None) and await engine.get_task(task.id, user)
    proposal = await coder.execute(task.id, user, staging.id)
    duplicate_proposal = await coder.execute(task.id, user, staging.id)
    assert proposal.id == duplicate_proposal.id
    assert fake.calls == 2

    for state in (WorkflowState.CODE_REVIEW, WorkflowState.TEST_PLANNING,
                  WorkflowState.TEST_EXECUTING, WorkflowState.REVIEWING):
        task = await engine.transition(task.id, state, ActorType.SYSTEM, None, state.value)
    reviewer = ReviewerService(
        QuotaGuardedGateway(fake, 2, 100), repository=InMemoryReviewerReportRepository(),
        workflow=engine, context_builder=Context(),
    )
    report = await reviewer.execute(task.id, user)
    duplicate_report = await reviewer.execute(task.id, user)
    assert report.id == duplicate_report.id
    assert fake.calls == 3
