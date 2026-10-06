"""V1 local authority, real execution, remote gates, and process reconstruction."""
import asyncio
import base64
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from backend.app.core.config import get_settings
from backend.app.core.auth import AuthenticatedUserContext, get_authenticated_user
from backend.app.models.agent import AgentRole
from backend.app.models.task import ActorType
from backend.app.services import runtime as runtime_module
from backend.app.services.device_connection import DeviceConnectionManager
from backend.app.services.device_control import DeviceControlService, CommandType, CommandStatus
from backend.app.services.remote_command_router import RemoteCommandRouter
from backend.app.services.task_artifacts import TaskArtifactService, InMemoryTaskArtifactRepository
from backend.app.storage.local import LocalStorageBackend
from backend.app.workflow.states import WorkflowState as State
from backend.tests.test_hosted_workflow import Gateway
from backend.tests.test_phase6_planner import plan_json


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    owner = uuid4()
    monkeypatch.setenv("ENVIRONMENT", "desktop")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("RUN_EMBEDDED_WORKER", "true")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RLB_LOCAL_API_TOKEN", "test-local-token")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"a" * 32).decode())
    monkeypatch.setenv("RLB_LOCAL_OWNER_ID", str(owner))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("RLB_DEVICE_TOKEN", "")
    monkeypatch.setenv("RLB_CONTROL_PLANE_URL", "")
    get_settings.cache_clear()
    yield owner
    get_settings.cache_clear()


def wire_gateways(runtime, *, repair=False):
    class CoderGateway:
        calls = 0
        async def generate(self, request):
            self.calls += 1
            answer = 2 if repair and self.calls == 1 else 3
            return await Gateway({"summary": "Set answer", "changes": [
                {"path": "app.py", "operation": "modify", "content": f"answer = {answer}\n"},
            ]}).generate(request)
    coder = CoderGateway()
    gateways = {
        AgentRole.PLANNER.value: Gateway(plan_json()),
        AgentRole.CODER.value: coder,
        AgentRole.TEST_ARCHITECT.value: Gateway({"test_cases": [{
            "category": "functional", "title": "Answer", "description": "Verify answer",
            "expected_result": "three", "test_code": 'python -c "from app import answer; assert answer == 3"',
        }]}),
        AgentRole.REVIEWER.value: Gateway({"summary": "Verified", "strengths": [], "concerns": [],
            "security_audit": "Checked supplied evidence", "recommendation": "ready_to_merge"}),
    }
    runtime.agents.resolver.resolve = lambda user, workspace, task, role: SimpleNamespace(
        gateway=gateways[role], run_metadata=lambda: {},
    )
    return coder


async def create_runtime(monkeypatch, repair=False):
    runtime = runtime_module.build_runtime()
    monkeypatch.setattr(runtime_module, "_runtime", runtime)
    await runtime.start()
    wire_gateways(runtime, repair=repair)
    return runtime


@pytest.mark.asyncio
async def test_local_workflow_restart_both_gates_real_tests_repair_and_review(desktop, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    runtime = await create_runtime(monkeypatch, repair=True)
    workspace = await runtime.workspace.register_local_workspace(desktop, "Local", str(project))
    task = await runtime.workflow.create_task(workspace, desktop, "Answer", "Set answer to three")
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("one").run_once()
    assert (await runtime.workflow.get_task(task.id, desktop)).status == State.PLAN_REVIEW
    await runtime.close()

    runtime = await create_runtime(monkeypatch, repair=True)
    plans = await runtime.workflow.list_plans(task.id, desktop)
    await runtime.workflow.record_approval(task.id, desktop, "plan", "approved", None, defer_setup=True)
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("two").run_once()
    assert (await runtime.workflow.get_task(task.id, desktop)).status == State.CODE_REVIEW
    assert (project / "app.py").read_text() == "answer = 1\n"
    proposal = (await runtime.agents.coder.proposals.list_by_task(task.id))[0]
    staging_id = proposal.staging_workspace_id
    await runtime.close()

    runtime = await create_runtime(monkeypatch)
    assert (await runtime.staging.get_staging_workspace(staging_id, desktop)).task_id == task.id
    assert (await runtime.agents.coder.proposals.get(proposal.id)).diffs[0].after_content == "answer = 2\n"
    await runtime.agents.coder.request_promotion(proposal.id, desktop)
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("three").run_once()
    assert (await runtime.workflow.get_task(task.id, desktop)).status == State.CODE_REVIEW
    executions = await runtime.testing.list_executions(task.id)
    assert len(executions) == 1 and not executions[0].all_passed
    assert (project / "app.py").read_text() == "answer = 2\n"
    repair_proposal = (await runtime.agents.coder.proposals.list_by_task(task.id))[0]
    await runtime.close()

    runtime = await create_runtime(monkeypatch)
    assert (await runtime.testing.list_executions(task.id))[0].command_results
    await runtime.agents.coder.request_promotion(repair_proposal.id, desktop)
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("four").run_once()
    assert (await runtime.workflow.get_task(task.id, desktop)).status == State.COMPLETED
    assert (project / "app.py").read_text() == "answer = 3\n"
    assert not (project / "__pycache__").exists()
    await runtime.close()
    runtime = await create_runtime(monkeypatch)
    assert len(await runtime.workflow.list_plans(task.id, desktop)) == len(plans)
    assert (await runtime.agents.reviewer.repository.get_by_task(task.id)).summary == "Verified"
    assert (await runtime.testing.list_executions(task.id))[-1].all_passed
    await runtime.close()


@pytest.mark.asyncio
async def test_cloud_only_observes_and_routes_local_review_approval(desktop, tmp_path, monkeypatch):
    from backend.app.api.v1 import devices as api
    runtime = await create_runtime(monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    workspace = await runtime.workspace.register_local_workspace(desktop, "Local", str(project))
    cloud = DeviceControlService(tmp_path / "cloud.sqlite3")
    await cloud.start()
    pairing = await cloud.create_pairing(desktop)
    device, token = await cloud.pair(pairing["pairing_token"], name="PC", platform="windows",
        architecture="x64", app_version="1", runtime_version="1", capabilities={})
    artifact_service = TaskArtifactService(LocalStorageBackend(tmp_path / "cloud-artifacts"), repository=InMemoryTaskArtifactRepository())
    monkeypatch.setattr(api, "control", cloud)
    monkeypatch.setattr(api, "_artifact_service", lambda: artifact_service)
    cloud_app = FastAPI()
    cloud_app.include_router(api.router, prefix="/api/v1")
    cloud_app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUserContext(desktop)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=cloud_app), base_url="https://cloud.test")
    manager = DeviceConnectionManager("https://cloud.test", token, tmp_path / "receipts.sqlite3",
        RemoteCommandRouter(runtime), client=client, event_source=runtime.workflow.repository, heartbeat_seconds=0)
    runtime.device_connection = manager
    await manager.start()
    await manager.poll_once(**runtime.connection_status())
    command = await cloud.enqueue_command(device.id, desktop, CommandType.START_TASK,
        {"workspace_id": str(workspace.id), "objective": "Set answer", "title": "Remote"}, "start-1")
    await manager.poll_once(**runtime.connection_status())
    result = (await cloud.list_commands(device.id, desktop))[0].result
    task_id = UUID(result["task_id"])
    # There is no cloud workflow task: the PC created and owns it.
    await runtime.worker("local").run_once()
    await manager.poll_once(**runtime.connection_status())
    events = await cloud.list_event_page(device.id, desktop)
    assert any(e["event_type"] == "plan_review" for e in events["events"])
    review_cmd = await cloud.enqueue_command(device.id, desktop, CommandType.REVIEW_TASK, {}, "review-1", task_id)
    await manager.poll_once(**runtime.connection_status())
    review_cmd = next(c for c in await cloud.list_commands(device.id, desktop) if c.id == review_cmd.id)
    assert review_cmd.status == CommandStatus.SUCCEEDED
    artifact_id = UUID(review_cmd.result["artifact"]["id"])
    metadata, content = await artifact_service.read(artifact_id, desktop, task_id, device.id)
    bundle = json.loads(content)
    assert bundle["plans"][0]["plan"]
    decision = {"status": "approved", "expected_version": bundle["task"]["version"], "plan_id": bundle["plans"][-1]["id"]}
    await cloud.enqueue_command(device.id, desktop, CommandType.PLAN_DECISION, decision, "approve-1", task_id)
    await manager.poll_once(**runtime.connection_status())
    await runtime.worker("local").run_once()
    assert (await runtime.workflow.get_task(task_id, desktop)).status == State.CODE_REVIEW
    # A stale, replayed review cannot approve a later gate.
    with pytest.raises(ValueError, match="changed after review"):
        await RemoteCommandRouter(runtime)({"user_id": str(desktop), "command_type": "PLAN_DECISION", "task_id": str(task_id), "payload": decision})
    with pytest.raises(PermissionError):
        await cloud.enqueue_command(device.id, uuid4(), CommandType.STOP_TASK, {}, "foreign", task_id)
    await runtime.close()
    await client.aclose()
    await cloud.close()


@pytest.mark.asyncio
async def test_crash_after_local_publish_resumes_approved_promotion(desktop, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    runtime = await create_runtime(monkeypatch)
    workspace = await runtime.workspace.register_local_workspace(desktop, "Local", str(project))
    task = await runtime.workflow.create_task(workspace, desktop, "Answer", "Set answer")
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("one").run_once()
    await runtime.workflow.record_approval(task.id, desktop, "plan", "approved", None, defer_setup=True)
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("one").run_once()
    proposal = (await runtime.agents.coder.proposals.list_by_task(task.id))[0]
    await runtime.agents.coder.request_promotion(proposal.id, desktop)
    transition = runtime.workflow.transition
    async def crash(*args, **kwargs):
        if args[1] == State.TEST_PLANNING:
            raise asyncio.CancelledError()
        return await transition(*args, **kwargs)
    runtime.workflow.transition = crash
    with pytest.raises(asyncio.CancelledError):
        await runtime.agents.coder.approve_and_apply(proposal.id, desktop, already_approved=True)
    assert (project / "app.py").read_text() == "answer = 3\n"
    await runtime.close()
    runtime = await create_runtime(monkeypatch)
    await runtime.worker("recovered").run_once()
    assert (await runtime.workflow.get_task(task.id, desktop)).status == State.COMPLETED
    assert (await runtime.agents.coder.proposals.get(proposal.id)).status == "applied"
    await runtime.close()


@pytest.mark.asyncio
async def test_desktop_provider_configuration_encrypted_and_usable_after_restart(desktop, tmp_path, monkeypatch):
    from backend.app.api.v1 import providers
    from backend.app.models.provider import AgentWorkerMapping
    from backend.app.services.credential_service import EncryptedSecret
    runtime = runtime_module.build_runtime()
    monkeypatch.setattr(runtime_module, "_runtime", runtime)
    await runtime.start()
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    workspace = await runtime.workspace.register_local_workspace(desktop, "Local", str(project))
    auth = AuthenticatedUserContext(desktop)
    secret = "test-key-must-never-be-plaintext-in-sqlite"
    credential = await providers.save_credential(providers.CredentialInput(provider_name="Groq", api_key=secret), auth)
    worker = await providers.save_worker(providers.WorkerInput(provider_id="groq", model_name="configured-model"), auth)
    loadout = await providers.create_loadout(providers.LoadoutInput(name="Local", mappings={
        role.value: AgentWorkerMapping(primary_worker_id=worker["id"])
        for role in (AgentRole.PLANNER, AgentRole.CODER, AgentRole.TEST_ARCHITECT, AgentRole.REVIEWER)
    }), auth)
    await providers.switch_loadout(workspace.id, loadout["id"], auth)
    task = await runtime.workflow.create_task(workspace, desktop, "Budget", "persist quota")
    await runtime.workflow.reserve_ai_call(task.id, desktop)
    await runtime.workflow.repository.record_provider_call(task.id, {"model_name": "configured-model"})
    await runtime.close()
    assert secret.encode() not in (tmp_path / "data" / "rlb.sqlite3").read_bytes()
    runtime = runtime_module.build_runtime()
    monkeypatch.setattr(runtime_module, "_runtime", runtime)
    await runtime.start()
    resolver = runtime.agents.resolver
    resolved = resolver.resolve(desktop, workspace.id, task.id, AgentRole.PLANNER.value)
    assert resolved.model_name == "configured-model"
    encrypted = resolver.credentials[(desktop, "groq")]
    assert resolver.credential_service.decrypt(EncryptedSecret(encrypted.ciphertext, encrypted.iv, encrypted.tag)) == secret
    assert runtime.workflow.repository.ai_calls[task.id] == 1
    assert runtime.workflow.repository.provider_calls[task.id][0]["model_name"] == "configured-model"
    assert (await providers.list_credentials(auth))[0]["id"] == credential["id"]
    await runtime.close()


@pytest.mark.asyncio
async def test_release_identity_rejects_development_spoofing(desktop):
    from fastapi import HTTPException
    user = await get_authenticated_user(None, str(uuid4()), "test-local-token")
    assert user.user_id == desktop
    with pytest.raises(HTTPException) as error:
        await get_authenticated_user(None, str(desktop), "wrong-token")
    assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        await get_authenticated_user("Bearer a-browser-token", str(desktop), None)


@pytest.mark.parametrize("url", ["http://127.0.0.1.evil.test", "http://127.0.0.1@evil.test", "https://control.test/path", "https://user:secret@control.test"])
def test_control_plane_origin_cannot_bypass_https_boundary(tmp_path, url):
    with pytest.raises(ValueError):
        DeviceConnectionManager(url, "token", tmp_path / "unused.sqlite3", lambda command: None)


@pytest.mark.asyncio
async def test_prompt_arriving_during_planning_is_processed_before_gate(desktop, tmp_path, monkeypatch):
    runtime = await create_runtime(monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    workspace = await runtime.workspace.register_local_workspace(desktop, "Local", str(project))
    task = await runtime.workflow.create_task(workspace, desktop, "Prompt", "Set answer")
    execute = runtime.agents.planner.execute
    feedbacks = []
    async def interrupted(task_id, owner, feedback=None):
        feedbacks.append(feedback)
        if len(feedbacks) == 1:
            await runtime.queue.add_prompt(task_id, owner, "Also handle empty input")
        return await execute(task_id, owner, feedback)
    runtime.agents.planner.execute = interrupted
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("local").run_once()
    assert feedbacks == [None, "Also handle empty input"]
    assert (await runtime.workflow.get_task(task.id, desktop)).status == State.PLAN_REVIEW
    assert await runtime.queue.pending_prompts(task.id) == []
    with pytest.raises(ValueError):
        await runtime.queue.add_prompt(task.id, desktop, "Bypass approval")
    await runtime.close()


@pytest.mark.asyncio
async def test_execution_has_no_runtime_secrets_and_cannot_mutate_approved_files(tmp_path, monkeypatch):
    from backend.app.sandbox.local import LocalWindowsSandboxDriver
    from backend.app.sandbox.types import SandboxCommand, SandboxLimits
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    monkeypatch.setenv("RLB_DEVICE_TOKEN", "secret")
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    driver = LocalWindowsSandboxDriver()
    handle = await driver.create_sandbox(uuid4(), str(project), SandboxLimits())
    command = SandboxCommand(cmd="python -c \"import os; from pathlib import Path; assert not os.getenv('RLB_DEVICE_TOKEN'); assert not os.getenv('GROQ_API_KEY'); Path('app.py').write_text('mutated'); print('x'*100000)\"")
    result = await driver.execute_command(handle, command)
    assert result.exit_code == 0
    assert len(result.stdout) == 64000
    assert (project / "app.py").read_text() == "answer = 1\n"
    await driver.destroy_sandbox(handle)


@pytest.mark.asyncio
async def test_stop_cancels_inflight_local_process_tree(desktop, tmp_path, monkeypatch):
    from backend.app.services.durable_worker import DurableTaskWorker
    from backend.app.sandbox.local import LocalWindowsSandboxDriver
    from backend.app.sandbox.types import SandboxCommand, SandboxLimits
    runtime = await create_runtime(monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    workspace = await runtime.workspace.register_local_workspace(desktop, "Local", str(project))
    task = await runtime.workflow.create_task(workspace, desktop, "Stop", "Stop execution")
    driver = LocalWindowsSandboxDriver()
    handle = await driver.create_sandbox(workspace.id, str(project), SandboxLimits())
    started = asyncio.Event()
    async def long_stage(job):
        started.set()
        await driver.execute_command(handle, SandboxCommand(cmd='python -c "import time; time.sleep(30)"'))
        raise AssertionError("Cancelled process must not finish normally")
    worker = DurableTaskWorker(runtime.queue, "stoppable", {State.READY: long_stage})
    await runtime.queue.enqueue(task.id, desktop)
    running = asyncio.create_task(worker.run_once())
    await started.wait()
    await asyncio.sleep(0.1)
    await RemoteCommandRouter(runtime)({"user_id": str(desktop), "command_type": "STOP_TASK", "task_id": str(task.id), "payload": {}})
    await asyncio.wait_for(running, timeout=3)
    assert (await runtime.workflow.get_task(task.id, desktop)).status == State.CANCELLED
    await driver.destroy_sandbox(handle)
    await runtime.close()

@pytest.mark.asyncio
async def test_control_plane_readiness_does_not_require_hosted_execution_worker(monkeypatch):
    from backend.app.services import readiness as module
    queries = []
    class Connection:
        async def execute(self, statement):
            queries.append(str(statement))
            return SimpleNamespace(scalar=lambda: 8)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
    settings = SimpleNamespace(ENVIRONMENT="production", RLB_CONTROL_PLANE_ONLY=True,
        SUPABASE_URL="https://example.test", SUPABASE_SERVICE_ROLE_KEY="test", SUPABASE_STORAGE_BUCKET="private")
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "get_engine", lambda: SimpleNamespace(connect=lambda: Connection()))
    from backend.app.storage.supabase_client import SupabaseStorageClient
    async def bucket(self, *args): return SimpleNamespace(json=lambda: {"public": False})
    monkeypatch.setattr(SupabaseStorageClient, "_request", bucket)
    result = await module.readiness()
    assert result["status"] == "ready"
    assert result["worker"] == "paired_local_runtime"
    assert not any("worker_heartbeats" in query or "pgmq.list_queues" in query for query in queries)


@pytest.mark.asyncio
async def test_control_only_cloud_rejects_execution_mutation(desktop, monkeypatch):
    from backend.app.main import create_app
    get_settings().RLB_CONTROL_PLANE_ONLY = True
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post('/api/v1/tasks', json={})
    assert response.status_code == 409
    assert "paired PC" in response.json()["detail"]


@pytest.mark.parametrize("path", ["/absolute.py", "C:/Windows/secret.py", "../escape.py", "folder/../escape.py", "file.py:stream", "file.py. "])
def test_coder_paths_cannot_escape_staging_or_use_windows_aliases(path):
    from backend.app.services.staging_service import _safe_relative_path
    with pytest.raises(ValueError):
        _safe_relative_path(path)


@pytest.mark.asyncio
async def test_restart_marks_interrupted_test_evidence_cancelled(desktop, monkeypatch):
    from datetime import datetime, timezone
    from backend.app.models.test import TestExecution as Execution
    from backend.app.models.agent import ExecutionStatus
    runtime = await create_runtime(monkeypatch)
    execution = Execution(id=uuid4(), task_id=uuid4(), agent_run_id=uuid4(),
                          created_at=datetime.now(timezone.utc))
    await runtime.testing.add_execution(execution)
    await runtime.close()
    runtime = await create_runtime(monkeypatch)
    recovered = (await runtime.testing.list_executions(execution.task_id))[0]
    assert recovered.status == ExecutionStatus.CANCELLED
    assert not recovered.all_passed
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [State.CANCELLED, State.FAILED])
@pytest.mark.parametrize("external_edit", [False, True])
async def test_terminal_partial_approved_publication_recovery(desktop, tmp_path, monkeypatch, terminal, external_edit):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("answer = 1\n")
    runtime = await create_runtime(monkeypatch)
    workspace = await runtime.workspace.register_local_workspace(desktop, "Local", str(project))
    task = await runtime.workflow.create_task(workspace, desktop, "Answer", "Set answer")
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("one").run_once()
    await runtime.workflow.record_approval(task.id, desktop, "plan", "approved", None, defer_setup=True)
    await runtime.queue.enqueue(task.id, desktop)
    await runtime.worker("one").run_once()
    proposal = (await runtime.agents.coder.proposals.list_by_task(task.id))[0]
    await runtime.agents.coder.request_promotion(proposal.id, desktop)
    original = runtime.workspace._write_local_snapshot_files
    def crash(*args):
        original(*args)
        raise RuntimeError("simulated process death after selected-folder writes")
    monkeypatch.setattr(runtime.workspace, "_write_local_snapshot_files", crash)
    with pytest.raises(RuntimeError):
        await runtime.agents.coder.approve_and_apply(proposal.id, desktop, already_approved=True)
    await runtime.workflow.transition(task.id, terminal, ActorType.SYSTEM, None, "Interrupted publication")
    if external_edit:
        (project / "app.py").write_text("external edit\n")
    await runtime.close()
    runtime = await create_runtime(monkeypatch)
    assert (await runtime.workflow.get_task(task.id, desktop)).status == terminal
    assert (await runtime.agents.coder.proposals.get(proposal.id)).status == ("ready_for_review" if external_edit else "applied")
    assert not await runtime.testing.list_executions(task.id)
    assert (project / "app.py").read_text() == ("external edit\n" if external_edit else "answer = 3\n")
    if external_edit:
        assert runtime.workflow.repository.messages[task.id][-1]["metadata"]["recovery_conflict"]
    await runtime.close()


@pytest.mark.parametrize("path", ["CON", "folder/aux.txt", "NUL.py", "COM1/log.txt", "file?.py", "file\x00.py"])
def test_windows_device_and_invalid_paths_rejected_before_staging(path):
    from backend.app.services.staging_service import _safe_relative_path
    with pytest.raises(ValueError):
        _safe_relative_path(path)
