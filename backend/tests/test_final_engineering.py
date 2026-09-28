"""Deterministic acceptance; no external services, credentials, or project shell execution."""
import asyncio
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from backend.app.ai.gateway import AIGatewayError, AIRequest, AIResponse, ProviderGateway
from backend.app.ai.failover import FailoverGateway, TransientProviderError
from backend.app.core.config import get_settings
from backend.app.models.task import ActorType
from backend.app.services.task_service import WorkflowEngine, TaskAccessDeniedError, TaskRateLimitError
from backend.app.services.workspace_service import WorkspaceService, WorkspaceAccessDeniedError
from backend.app.services.staging_service import StagingService
from backend.app.services.job_queue import LocalJobQueue
from backend.app.services.durable_worker import DurableTaskWorker, build_default_worker
from backend.app.services.planner_service import PlannerService
from backend.app.services.coder_service import CoderService
from backend.app.services.reviewer_service import ReviewerService
from backend.app.services.test_orchestrator import TestOrchestrationService as Orchestrator
from backend.app.repositories.testing import InMemoryTestingRepository
from backend.app.storage.local import LocalStorageBackend
from backend.app.workflow.states import WorkflowState as State
from backend.tests.test_hosted_workflow import Gateway
from backend.tests.test_phase6_planner import plan_json
from backend.tests.test_phase8_testing import FakeSandbox


async def setup(tmp_path):
    owner = uuid4()
    storage = LocalStorageBackend(tmp_path)
    workspaces = WorkspaceService(storage)
    workspace = await workspaces.create_workspace(owner, 'Final acceptance')
    workflow = WorkflowEngine(workspace_service=workspaces)
    task = await workflow.create_task(workspace, owner, 'Add', 'Preserve add and introduce subtract(a,b).')
    return owner, storage, workspaces, workspace, workflow, task


@pytest.mark.asyncio
@pytest.mark.parametrize('status,transient', [(429, True), (503, True), (401, False), (400, False)])
async def test_provider_fallback_classification_and_durable_budget(tmp_path, status, transient):
    owner, _, _, _, workflow, task = await setup(tmp_path)
    class Adapter:
        provider_id = 'test'
        async def generate_completion(self, request, credentials):
            response = httpx.Response(status, request=httpx.Request('POST', 'https://provider.invalid'))
            response.raise_for_status()
    primary = ProviderGateway(Adapter(), object(), 'primary-model')
    fallback = Gateway('success')
    async def reserve():
        await workflow.reserve_ai_call(task.id, owner)
    async def record(evidence):
        await workflow.repository.record_provider_call(task.id, evidence)
    gateway = FailoverGateway([({'worker_id': 'primary'}, primary), ({'worker_id': 'fallback'}, fallback)], reserve, record)
    request = AIRequest(system_prompt='test', user_prompt='test')
    if transient:
        response = await gateway.generate(request)
        assert response.content == 'success'
        assert response.metadata['fallback_used'] is True
        assert workflow.repository.ai_calls[task.id] == 2
    else:
        with pytest.raises(AIGatewayError):
            await gateway.generate(request)
        assert fallback.calls == 0
        assert workflow.repository.ai_calls[task.id] == 1
    assert workflow.repository.provider_calls[task.id][0]['outcome'] != 'success'
    # A rebuilt workflow still sees the repository's consumed budget.
    recovered = WorkflowEngine(workflow.workspace_service, workflow.repository)
    workflow.repository.ai_calls[task.id] = get_settings().MAX_AI_CALLS_PER_TASK
    with pytest.raises(AIGatewayError, match='budget'):
        await recovered.reserve_ai_call(task.id, owner)


@pytest.mark.asyncio
async def test_timeout_falls_back_with_unchanged_context():
    class Timeout(Gateway):
        async def generate(self, request):
            raise TransientProviderError('Provider request timed out.')
    class Capture(Gateway):
        async def generate(self, request):
            assert request.user_prompt == 'same context'
            assert request.model is None
            return AIResponse(content='ok')
    gateway = FailoverGateway([({}, Timeout('')), ({}, Capture(''))])
    assert (await gateway.generate(AIRequest(system_prompt='x', user_prompt='same context', model='primary'))).content == 'ok'


@pytest.mark.asyncio
async def test_two_users_cannot_read_mutate_approve_or_promote(tmp_path):
    owner, storage, workspaces, workspace, workflow, task = await setup(tmp_path)
    other = uuid4()
    await storage.write_file(workspace.canonical_root_path + '/app.py', b'answer=1')
    workspace = await workspaces.sync_canonical_metadata(workspace)
    await workflow.transition(task.id, State.PLANNING, ActorType.SYSTEM, None, 'test')
    await workflow.transition(task.id, State.PLAN_REVIEW, ActorType.SYSTEM, None, 'test')
    with pytest.raises(TaskAccessDeniedError):
        await workflow.record_approval(task.id, other, 'plan', 'approved', None)
    await workflow.record_approval(task.id, owner, 'plan', 'approved', None)
    coder = CoderService(Gateway({'summary': 'change', 'changes': [
        {'path': 'app.py', 'operation': 'modify', 'content': 'answer=2'}]}), workflow=workflow)
    proposal = await coder.execute(task.id, owner)
    await workflow.transition(task.id, State.CODE_REVIEW, ActorType.SYSTEM, None, 'review')
    for action in [lambda: workflow.get_task(task.id, other),
                   lambda: workflow.get_history(task.id, other),
                   lambda: workflow.list_agent_runs(task.id, other),
                   lambda: workflow.record_approval(task.id, other, 'code', 'approved', None),
                   lambda: coder.approve_and_apply(proposal.id, other),
                   lambda: coder.request_revision(proposal.id, other, 'attack'),
                   lambda: coder.reject(proposal.id, other),
                   lambda: workspaces.read_workspace_file(workspace.id, 'app.py', other),
                   lambda: coder.staging_service.read_staging_file(proposal.staging_workspace_id, 'app.py', other)]:
        with pytest.raises((TaskAccessDeniedError, WorkspaceAccessDeniedError)):
            await action()
    assert await storage.read_file(workspace.canonical_root_path + '/app.py') == b'answer=1'


@pytest.mark.asyncio
async def test_cancellation_interrupts_running_stage_and_releases_job(tmp_path):
    owner, _, _, _, workflow, task = await setup(tmp_path)
    queue = LocalJobQueue(workflow, lease_seconds=0.03)
    started, stopped = asyncio.Event(), asyncio.Event()
    async def long_stage(job):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    worker = DurableTaskWorker(queue, 'worker', {State.READY: long_stage})
    await queue.enqueue(task.id, owner)
    running = asyncio.create_task(worker.run_once())
    await started.wait()
    await workflow.transition(task.id, State.CANCELLED, ActorType.USER, owner, 'cancel')
    await asyncio.wait_for(running, 1)
    assert stopped.is_set()
    assert (await workflow.get_task(task.id, owner)).status == State.CANCELLED
    assert await queue.claim('other') is None


@pytest.mark.asyncio
async def test_submission_limit_is_per_user(tmp_path, monkeypatch):
    owner, _, workspaces, workspace, workflow, _ = await setup(tmp_path)
    monkeypatch.setattr(get_settings(), 'MAX_TASKS_PER_USER_PER_HOUR', 1)
    with pytest.raises(TaskRateLimitError):
        await workflow.create_task(workspace, owner, 'spam', 'spam')
    other = uuid4()
    other_workspace = await workspaces.create_workspace(other, 'Other')
    assert (await workflow.create_task(other_workspace, other, 'ok', 'ok')).user_id == other


@pytest.mark.asyncio
@pytest.mark.parametrize('max_repairs', [0, 1])
async def test_golden_import_approval_failure_repair_recovery(tmp_path, monkeypatch, max_repairs):
    monkeypatch.setattr(get_settings(), 'MAX_REPAIR_ATTEMPTS', max_repairs)
    owner, storage, workspaces, workspace, workflow, task = await setup(tmp_path)
    fixture = Path(__file__).parent / 'fixtures' / 'rlb-fixture'
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as zipped:
        for file in sorted(fixture.rglob('*')):
            if file.is_file():
                zipped.writestr(str(file.relative_to(fixture)), file.read_bytes())
    # Use the actual import service contract, not prefilled task/proposal state.
    workspace = await workspaces.import_project_into_empty_workspace(workspace.id, owner, zip_bytes=archive.getvalue())
    workspace = await workspaces.sync_canonical_metadata(workspace)
    assert workspace.file_count >= 3
    planner = PlannerService(Gateway(plan_json()), workflow=workflow)
    coder = CoderService(Gateway({'summary': 'subtract', 'changes': [
        {'path': 'app.py', 'operation': 'modify', 'content': 'def add(a,b): return a+b\ndef subtract(a,b): return a-b\n'}]}),
        workflow=workflow, staging_service=StagingService(workspaces, storage))
    testing = InMemoryTestingRepository()
    test_gateway = Gateway({'test_cases': [{'category': 'functional', 'title': 'subtract',
        'description': 'subtract', 'expected_result': '2', 'test_code': 'python -c "from app import subtract; assert subtract(5,3)==2"'}]})
    resolver = SimpleNamespace(resolve=lambda *args: SimpleNamespace(gateway=test_gateway, run_metadata=lambda: {}))
    sandbox = FakeSandbox(exit_code=1)
    orchestrator = Orchestrator(workflow, testing, sandbox, resolver)
    reviewer = ReviewerService(Gateway({'summary': 'Verified', 'strengths': [], 'concerns': [], 'security_audit': 'Local fixture evidence', 'recommendation': 'ready_to_merge'}), workflow=workflow)
    queue = LocalJobQueue(workflow)
    async def run():
        # Fresh worker instance models reconnect/restart against existing persisted ports.
        await queue.enqueue(task.id, owner)
        await build_default_worker(queue, str(uuid4()), planner, coder, reviewer, orchestrator).run_once()
    await run()
    assert (await workflow.get_task(task.id, owner)).status == State.PLAN_REVIEW
    await workflow.record_approval(task.id, owner, 'plan', 'approved', None, defer_setup=True)
    assert (await workflow.get_task(task.id, owner)).status == State.STAGING_SETUP
    await run()
    await coder.request_promotion((await coder.proposals.list_by_task(task.id))[0].id, owner)
    assert (await workflow.get_task(task.id, owner)).status == State.PROMOTING
    await run()
    if max_repairs == 0:
        assert (await workflow.get_task(task.id, owner)).status == State.FAILED
        return
    assert (await workflow.get_task(task.id, owner)).status == State.CODE_REVIEW
    evidence = (await testing.list_executions(task.id))[0]
    assert evidence.failure_report and evidence.command_results
    assert evidence.command_results[0]['exit_code'] == 1
    assert any(item.new_state == State.REPAIRING for item in await workflow.get_history(task.id, owner))
    sandbox.exit_code = 0
    await coder.request_promotion((await coder.proposals.list_by_task(task.id))[0].id, owner)
    assert (await workflow.get_task(task.id, owner)).status == State.PROMOTING
    await run()
    assert (await workflow.get_task(task.id, owner)).status == State.COMPLETED
    assert len(await testing.list_executions(task.id)) == 2
    states = [item.new_state for item in await workflow.get_history(task.id, owner)]
    assert all(state in states for state in (State.ANALYZING, State.STAGING_SETUP, State.PROMOTING, State.REPAIRING))
    assert (await testing.list_executions(task.id))[-1].command_results[-1]['status'] == 'success'


@pytest.mark.asyncio
async def test_transient_worker_failure_retries_with_finite_limit(tmp_path):
    owner, _, _, _, workflow, task = await setup(tmp_path)
    await workflow.transition(task.id, State.PLANNING, ActorType.SYSTEM, None, 'start')
    queue = LocalJobQueue(workflow)
    async def fail(job):
        raise TransientProviderError('Provider request timed out.')
    worker = DurableTaskWorker(queue, 'worker', {State.PLANNING: fail})
    await queue.enqueue(task.id, owner)
    for attempt in range(3):
        with pytest.raises(TransientProviderError):
            await worker.run_once()
        current = await workflow.get_task(task.id, owner)
        assert current.status == (State.FAILED if attempt == 2 else State.PLANNING)
    assert await queue.claim('another') is None


@pytest.mark.asyncio
async def test_http_tenant_isolation_and_credentials():
    from backend.app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
        a, b = {'x-user-id': str(uuid4())}, {'x-user-id': str(uuid4())}
        created = await client.post('/api/v1/workspaces', data={'name': 'Private'}, headers=a)
        assert created.status_code == 201
        workspace = created.json()['id']
        created_task = await client.post('/api/v1/tasks', json={'workspace_id': workspace, 'title': 'Private', 'objective': 'Private'}, headers=a)
        assert created_task.status_code == 201
        task = created_task.json()['id']
        credential = await client.put('/api/v1/providers/credentials', json={'provider_name': 'Groq', 'api_key': 'test-only-not-a-real-key'}, headers=a)
        assert credential.status_code == 200
        assert 'test-only-not-a-real-key' not in credential.text
        assert (await client.get('/api/v1/providers/credentials', headers=b)).json() == []
        for path in [f'/workspaces/{workspace}', f'/workspaces/{workspace}/files',
                     f'/workspaces/{workspace}/files/content?path=app.py', f'/tasks/{task}',
                     f'/tasks/{task}/events', f'/tasks/{task}/workflow', f'/tasks/{task}/agent-runs',
                     f'/tasks/{task}/test-executions', f'/tasks/{task}/code-proposals',
                     f'/providers/workspaces/{workspace}/loadout']:
            response = await client.get('/api/v1' + path, headers=b)
            assert response.status_code in (403, 404), (path, response.text)
        response = await client.post(f'/api/v1/tasks/{task}/approvals',
            json={'approval_type': 'plan', 'status': 'approved'}, headers=b)
        assert response.status_code == 403
        response = await client.post(f'/api/v1/tasks/{task}/transition',
            json={'target_state': 'cancelled', 'reason': 'attack'}, headers=b)
        assert response.status_code == 403
        assert (await client.get(f'/api/v1/tasks/{task}')).status_code == 401


@pytest.mark.asyncio
async def test_cloud_upload_failure_never_opens_pointer_transaction(tmp_path):
    from backend.app.services.cloud_promotion import promote_snapshot
    owner, storage, workspaces, workspace, workflow, task = await setup(tmp_path)
    await storage.write_file(workspace.canonical_root_path + '/keep.txt', b'approved')
    staging = await StagingService(workspaces, storage).create_staging_workspace(workspace.id, owner, task.id)
    class BrokenStorage:
        deleted = []
        async def list_files(self, prefix):
            return await storage.list_files(prefix)
        async def read_file(self, path):
            return await storage.read_file(path)
        async def write_file(self, path, data):
            raise OSError('upload failed')
        async def delete_directory(self, path):
            self.deleted.append(path)
    class Sessions:
        def begin(self):
            raise AssertionError('Database must not be touched after failed upload')
    broken = BrokenStorage()
    with pytest.raises(OSError):
        await promote_snapshot(Sessions(), broken, workspace, staging, SimpleNamespace(), task, owner)
    assert broken.deleted and '/snapshots/' in broken.deleted[0]
    assert await storage.read_file(workspace.canonical_root_path + '/keep.txt') == b'approved'


@pytest.mark.asyncio
async def test_readiness_local_never_claims_cloud_connectivity():
    from backend.app.services.readiness import readiness
    result = await readiness()
    assert result['status'] == 'local'
    assert result['sandbox'] == 'unavailable'


@pytest.mark.asyncio
async def test_hosted_runtime_fails_before_adapter_construction(monkeypatch):
    from backend.app.services.runtime import build_runtime
    settings = get_settings()
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'staging')
    monkeypatch.setattr(settings, 'DATABASE_URL', None)
    with pytest.raises(RuntimeError, match='Missing hosted configuration'):
        build_runtime()


@pytest.mark.asyncio
async def test_zero_exit_timeout_cannot_pass_and_cleanup_runs(tmp_path):
    from datetime import datetime, timezone
    from backend.app.models.test import TestPlan, TestCase
    from backend.app.services.testing_service import TestExecutorService
    from backend.app.sandbox.types import SandboxExecutionResult
    class TimeoutSandbox(FakeSandbox):
        cleaned = False
        async def execute_command(self, sandbox_id, command):
            return SandboxExecutionResult(exit_code=0, timed_out=True, stdout='partial', stderr='timeout', duration_ms=1)
        async def destroy_sandbox(self, sandbox_id):
            self.cleaned = True
    repository = InMemoryTestingRepository()
    task, run, plan_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    plan = TestPlan(id=plan_id, task_id=task, agent_run_id=run, plan_summary='test', created_at=now,
        test_cases=[TestCase(id=uuid4(), test_plan_id=plan_id, category='functional', title='test',
                            description='test', expected_result='pass', test_code='assertion', created_at=now)])
    await repository.add_plan(plan)
    sandbox = TimeoutSandbox()
    execution = await TestExecutorService(repository, sandbox).execute(task, run, uuid4(), 'snapshot', plan)
    assert not execution.all_passed
    assert execution.command_results[0]['status'] == 'timeout'
    assert sandbox.cleaned


@pytest.mark.asyncio
async def test_concurrent_local_approval_promotes_only_once(tmp_path):
    owner, storage, workspaces, workspace, workflow, task = await setup(tmp_path)
    await storage.write_file(workspace.canonical_root_path + '/app.py', b'answer=1')
    workspace = await workspaces.sync_canonical_metadata(workspace)
    old_root = workspace.canonical_root_path
    await workflow.transition(task.id, State.PLANNING, ActorType.SYSTEM, None, 'start')
    await workflow.transition(task.id, State.PLAN_REVIEW, ActorType.SYSTEM, None, 'review')
    await workflow.record_approval(task.id, owner, 'plan', 'approved', None)
    coder = CoderService(Gateway({'summary': 'change', 'changes': [
        {'path': 'app.py', 'operation': 'modify', 'content': 'answer=2'}]}), workflow=workflow)
    proposal = await coder.execute(task.id, owner)
    await workflow.transition(task.id, State.CODE_REVIEW, ActorType.SYSTEM, None, 'review')
    results = await asyncio.gather(coder.approve_and_apply(proposal.id, owner),
                                   coder.approve_and_apply(proposal.id, owner), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    current = await workspaces.get_workspace(workspace.id, owner)
    assert current.canonical_root_path != old_root
    assert await storage.read_file(old_root + '/app.py') == b'answer=1'
    assert await storage.read_file(current.canonical_root_path + '/app.py') == b'answer=2'
    assert (await workflow.get_task(task.id, owner)).approved_snapshot_hash == current.current_snapshot_hash


@pytest.mark.asyncio
async def test_empty_snapshot_has_content_hash_instead_of_previous_hash(tmp_path):
    import hashlib
    owner, storage, workspaces, workspace, _, _ = await setup(tmp_path)
    await storage.write_file(workspace.canonical_root_path + '/last.txt', b'last')
    workspace = await workspaces.sync_canonical_metadata(workspace)
    previous_hash = workspace.current_snapshot_hash
    await storage.delete_file(workspace.canonical_root_path + '/last.txt')
    workspace = await workspaces.sync_canonical_metadata(workspace)
    assert workspace.current_snapshot_hash == hashlib.sha256(b'').hexdigest()
    assert workspace.current_snapshot_hash != previous_hash
