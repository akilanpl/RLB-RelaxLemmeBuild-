"""End-to-end application workflow with explicit offline AI and sandbox doubles."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import MockTransport, Request, Response

from backend.app.ai.gateway import AIGateway, AIResponse
from backend.app.services.workspace_service import WorkspaceService
from backend.app.services.staging_service import StagingService
from backend.app.services.task_service import WorkflowEngine, TaskAccessDeniedError
from backend.app.services.planner_service import PlannerService
from backend.app.services.coder_service import CoderService
from backend.app.services.reviewer_service import ReviewerService
from backend.app.services.reviewer_context import ReviewerContextBuilder
from backend.app.services.test_orchestrator import TestOrchestrationService as Orchestrator
from backend.app.services.durable_worker import build_default_worker
from backend.app.services.job_queue import LocalJobQueue
from backend.app.services.supabase_queue import SupabaseQueueAdapter
from backend.app.repositories.testing import InMemoryTestingRepository
from backend.app.storage.local import LocalStorageBackend
from backend.app.storage.supabase_client import SupabaseStorageClient
from backend.app.storage.supabase import SupabaseStorageBackend
from backend.app.storage.base import StorageError
from backend.app.models.task import ActorType
from backend.app.workflow.states import WorkflowState
from backend.tests.test_phase8_testing import FakeSandbox
from backend.tests.test_phase6_planner import plan_json


class Gateway(AIGateway):
    def __init__(self, data):
        self.content = data if isinstance(data, str) else json.dumps(data)
        self.calls = 0
    def validate_configuration(self):
        pass
    async def generate(self, request):
        self.calls += 1
        return AIResponse(content=self.content)


@pytest.mark.asyncio
async def test_complete_workflow_and_revision_keep_approval_boundaries(tmp_path):
    user = uuid4()
    storage = LocalStorageBackend(tmp_path)
    workspaces = WorkspaceService(storage)
    workspace = await workspaces.create_workspace(user, 'Integration')
    await storage.write_file(workspace.canonical_root_path + '/app.py', b'answer = 1\n')
    workspace = await workspaces.sync_canonical_metadata(workspace)
    workflow = WorkflowEngine(workspace_service=workspaces)
    task = await workflow.create_task(workspace, user, 'Change answer', 'Set answer to two')
    planner = PlannerService(Gateway(plan_json()), workflow=workflow)
    coder_gateway = Gateway({'summary': 'Change answer', 'changes': [
        {'path': 'app.py', 'operation': 'modify', 'content': 'answer = 2\n'}]})
    coder = CoderService(coder_gateway, workflow=workflow,
        staging_service=StagingService(workspaces, storage))
    tests = InMemoryTestingRepository()
    test_gateway = Gateway({'test_cases': [{'category': 'functional', 'title': 'Answer',
        'description': 'Verify answer', 'expected_result': 'two',
        'test_code': 'python -c "from app import answer; assert answer == 2"'}]})
    runtime = SimpleNamespace(resolve=lambda *args: SimpleNamespace(gateway=test_gateway, run_metadata=lambda: {}))
    sandbox = FakeSandbox()
    orchestrator = Orchestrator(workflow, tests, sandbox, runtime)
    reviewer = ReviewerService(Gateway({'summary': 'Verified', 'strengths': [], 'concerns': [],
        'security_audit': 'No issue in supplied evidence', 'recommendation': 'ready_to_merge'}),
        workflow=workflow, context_builder=ReviewerContextBuilder(workflow, proposals=coder.proposals, testing=tests))
    queue = LocalJobQueue(workflow)
    worker = build_default_worker(queue, 'test-worker', planner, coder, reviewer, orchestrator)
    await queue.enqueue(task.id, user)
    await worker.run_once()
    assert (await workflow.get_task(task.id, user)).status == WorkflowState.PLAN_REVIEW
    await workflow.record_approval(task.id, user, 'plan', 'approved', None)
    await queue.enqueue(task.id, user)
    await worker.run_once()
    assert (await workflow.get_task(task.id, user)).status == WorkflowState.CODE_REVIEW
    assert await storage.read_file(workspace.canonical_root_path + '/app.py') == b'answer = 1\n'
    proposal = (await coder.proposals.list_by_task(task.id))[0]
    await coder.request_revision(proposal.id, user, 'Double-check the answer')
    await queue.enqueue(task.id, user)
    await worker.run_once()
    assert coder_gateway.calls == 2
    latest = (await coder.proposals.list_by_task(task.id))[0]
    assert latest.id != proposal.id
    await coder.approve_and_apply(latest.id, user)
    await queue.enqueue(task.id, user)
    await worker.run_once()
    completed = await workflow.get_task(task.id, user)
    assert completed.status == WorkflowState.COMPLETED
    assert await storage.read_file(workspace.canonical_root_path + '/app.py') == b'answer = 2\n'
    evidence = await reviewer.context_builder.build(completed)
    assert evidence['proposals'] and evidence['tests']
    assert evidence['tests'][-1]['all_passed'] is True
    assert any('compileall' in cmd for cmd in sandbox.commands)
    assert any('assert answer == 2' in cmd for cmd in sandbox.commands)


@pytest.mark.asyncio
async def test_cross_tenant_task_transition_and_workspace_traversal_are_rejected(tmp_path):
    workspaces = WorkspaceService(LocalStorageBackend(tmp_path))
    owner, other = uuid4(), uuid4()
    workspace = await workspaces.create_workspace(owner, 'Private')
    workflow = WorkflowEngine(workspace_service=workspaces)
    task = await workflow.create_task(workspace, owner, 'Private task', 'test')
    with pytest.raises(TaskAccessDeniedError):
        await workflow.transition(task.id, WorkflowState.PLANNING, ActorType.USER, other, 'attack')
    with pytest.raises(Exception, match='traversal'):
        await workspaces.read_workspace_file(workspace.id, '../../other/canonical/private.txt', owner)


@pytest.mark.asyncio
async def test_supabase_storage_recurses_and_does_not_hide_service_failures():
    def handle(request: Request):
        if request.method == 'POST':
            payload = json.loads(request.content)
            rows = ([{'name': 'src', 'id': None}] if payload['prefix'] == 'workspace'
                    else [{'name': 'app.py', 'id': 'object'}])
            return Response(200, json=rows)
        return Response(503, json={'message': 'service unavailable'})
    client = SupabaseStorageClient('https://example.test', 'test-only', MockTransport(handle))
    assert await client.list('bucket', 'workspace') == ['workspace/src/app.py']
    with pytest.raises(StorageError, match='503'):
        await SupabaseStorageBackend(client).file_exists('workspace/src/app.py')


@pytest.mark.asyncio
async def test_supabase_queue_uses_worker_contract_and_acknowledges_review_pause():
    task_id, user = uuid4(), uuid4()
    class Client:
        acked = []
        async def claim(self, name, worker):
            return {'receipt': 42, 'message': {'task_id': str(task_id)}, 'user_id': user}
        async def ack(self, name, receipt):
            self.acked.append(receipt)
        async def extend(self, *args):
            pass
    client = Client()
    queue = SupabaseQueueAdapter(client, workflow=object())
    job = await queue.claim('worker')
    with pytest.raises(RuntimeError, match='lease'):
        await queue.complete(job.id, 'other')
    await queue.heartbeat(job.id, 'worker')
    await queue.wait_for_approval(job.id, 'worker')
    assert client.acked == [42]


@pytest.mark.asyncio
async def test_daytona_sdk_bridge_applies_limits_and_uploads_snapshot(tmp_path):
    from backend.app.sandbox.daytona_client import DaytonaRuntimeClient
    from backend.app.sandbox.daytona import DaytonaSandboxDriver
    from backend.app.sandbox.types import SandboxLimits, SandboxCommand
    class FS:
        files = {}
        async def create_folder(self, path, mode):
            pass
        async def upload_file(self, content, path):
            self.files[path] = content
    class SDK:
        params = None
        deleted = False
        async def create(self, params, timeout):
            self.params = params
            return SimpleNamespace(id='sandbox', fs=FS(), process=self)
        async def exec(self, cmd, **kwargs):
            assert kwargs['cwd'] == '/workspace'
            return SimpleNamespace(exit_code=0, result='ok')
        async def delete(self, sandbox):
            self.deleted = True
    storage = LocalStorageBackend(tmp_path)
    await storage.write_file('snapshot/src/app.py', b'print(1)')
    sdk = SDK()
    driver = DaytonaSandboxDriver(DaytonaRuntimeClient(sdk, storage, 'debian:12'))
    handle = await driver.create_sandbox(uuid4(), 'snapshot', SandboxLimits())
    assert sdk.params.network_block_all is True
    assert sdk.params.resources.memory == 4
    assert FS.files['/workspace/src/app.py'] == b'print(1)'
    assert (await driver.execute_command(handle, SandboxCommand(cmd='true'))).exit_code == 0
    await driver.destroy_sandbox(handle)
    assert sdk.deleted
