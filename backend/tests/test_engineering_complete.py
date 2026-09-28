"""Focused regressions for retention, ingestion and execution bounds. Offline only."""
import asyncio
import io
import zipfile
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import HTTPException, UploadFile
from backend.app.services.artifact_cleanup import ArtifactCleaner, protected
from backend.app.services.repository_import import archive_url, public_repository_files
from backend.app.services.zip_import import ZipValidationError
from backend.app.api.v1.workspaces import _read_upload
from backend.tests.test_final_engineering import setup
from backend.app.services.durable_worker import DurableTaskWorker
from backend.app.services.job_queue import LocalJobQueue
from backend.app.core.config import get_settings
from backend.app.workflow.states import WorkflowState as State


@pytest.mark.parametrize('kind', ['canonical', 'active', 'audit', 'legacy', 'task_staging', 'invalid'])
def test_retention_protects_live_and_audit_artifacts(kind):
    root = f'workspaces/{uuid4()}/snapshots/{uuid4()}'
    workspace, staging, active, audit, legacy = None, None, False, [], False
    if kind == 'canonical': workspace = {'canonical_root_path': root}
    if kind == 'active': active = True
    if kind == 'audit': audit = [root]
    if kind == 'legacy': legacy = True
    if kind == 'task_staging': staging = {'task_id': uuid4()}
    if kind == 'invalid': root = 'workspaces/../../secret'
    assert protected(root, workspace, staging, active, audit, legacy)
    assert not protected(f'workspaces/{uuid4()}/staging/{uuid4()}', None, None, False, [])


@pytest.mark.asyncio
async def test_cleanup_retry_restart_and_bounded_objects():
    root = f'workspaces/{uuid4()}/staging/{uuid4()}'
    paths = [root + '/' + str(i) for i in range(3)]
    records = []
    class Repository:
        async def candidates(self, limit): return [root][:limit]
        async def retire(self, item): return item == root
        async def objects(self, item, limit): return paths[:limit]
        async def record(self, item, count, error=None, complete=False): records.append((count, error, complete))
    class Storage:
        fail = True
        async def delete_file(self, path):
            if self.fail:
                self.fail = False
                raise RuntimeError('secret value must not be persisted')
            paths.remove(path)
    repository, storage = Repository(), Storage()
    assert await ArtifactCleaner(repository, storage).run_once(objects=2) == 0
    assert records[-1] == (0, 'RuntimeError', False)
    assert await ArtifactCleaner(repository, storage).run_once(objects=2) == 2
    assert len(paths) == 1
    assert await ArtifactCleaner(repository, storage).run_once(objects=2) == 1
    assert records[-1] == (1, None, True)
    assert await ArtifactCleaner(repository, storage).run_once(objects=2) == 0


@pytest.mark.parametrize('url', ['http://github.com/a/b','https://127.0.0.1/a/b',
    'https://github.com.evil.test/a/b','https://user:secret@github.com/a/b',
    'https://github.com:443/a/b','https://github.com/a/b?url=http://localhost',
    'https://github.com/a/b/tree/main','file:///etc/passwd','ssh://github.com/a/b'])
def test_repository_ssrf_and_unsupported_urls(url):
    with pytest.raises(ZipValidationError): archive_url(url)


@pytest.mark.asyncio
async def test_repository_archive_is_validated_and_root_stripped():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z: z.writestr('example-main/app.py', 'answer=42')
    def respond(request):
        assert str(request.url) == 'https://codeload.github.com/owner/example/zip/refs/heads/main'
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=archive.getvalue())
    files = await public_repository_files('https://github.com/owner/example.git', transport=httpx.MockTransport(respond))
    assert files[0]['relative_path'] == 'app.py'
    assert files[0]['content'] == b'answer=42'


@pytest.mark.asyncio
async def test_repository_redirect_never_followed():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={'Location': 'http://169.254.169.254/latest/meta-data/'})
    with pytest.raises(ZipValidationError):
        await public_repository_files('https://github.com/a/b', transport=httpx.MockTransport(respond))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_upload_read_bounded():
    upload = UploadFile(file=io.BytesIO(b'x' * 100))
    with pytest.raises(HTTPException) as error: await _read_upload(upload, 10)
    assert error.value.status_code == 413
    assert upload.file.tell() == 11


@pytest.mark.asyncio
async def test_concurrent_import_only_one_publication_and_failure_preserves_tree(tmp_path):
    owner, storage, service, workspace, _, _ = await setup(tmp_path)
    results = await asyncio.gather(*[service.import_project_into_empty_workspace(workspace.id, owner,
        files=[{'relative_path': 'app.py', 'content': content}]) for content in (b'first', b'second')], return_exceptions=True)
    assert sum(isinstance(result, ZipValidationError) for result in results) == 1
    current = await service.get_workspace(workspace.id, owner)
    assert current.file_count == 1
    assert await storage.read_file(current.canonical_root_path + '/app.py') in (b'first', b'second')
    other = await service.create_workspace(owner, 'failure')
    original = service._persist_workspace
    service._persist_workspace = AsyncMock(side_effect=RuntimeError('db unavailable'))
    with pytest.raises(RuntimeError):
        await service.import_project_into_empty_workspace(other.id, owner, files=[{'relative_path':'a','content':b'data'}])
    service._persist_workspace = original
    assert (await service.get_workspace(other.id, owner)).canonical_root_path == other.canonical_root_path
    assert await storage.list_files(other.canonical_root_path) == []


@pytest.mark.asyncio
async def test_stage_timeout_cancels_work_and_persists_failure(tmp_path, monkeypatch):
    owner, _, _, _, workflow, task = await setup(tmp_path)
    monkeypatch.setattr(get_settings(), 'MAX_WORKFLOW_STAGE_SECONDS', .02)
    stopped = asyncio.Event()
    async def hang(job):
        try: await asyncio.sleep(10)
        finally: stopped.set()
    queue = LocalJobQueue(workflow)
    await queue.enqueue(task.id, owner)
    with pytest.raises(TimeoutError):
        await DurableTaskWorker(queue, 'bounded', {State.READY: hang}).run_once()
    assert stopped.is_set()
    assert (await workflow.get_task(task.id, owner)).status == State.FAILED


@pytest.mark.asyncio
async def test_cleanup_does_not_touch_protected_roots():
    repo = AsyncMock()
    repo.candidates.return_value = ['protected']
    repo.retire.return_value = False
    storage = AsyncMock()
    assert await ArtifactCleaner(repo, storage).run_once() == 0
    repo.objects.assert_not_called()
    storage.delete_file.assert_not_called()


@pytest.mark.asyncio
async def test_task_staging_discard_retains_audit_bytes(tmp_path):
    from backend.app.services.staging_service import StagingService
    owner, storage, workspaces, workspace, _, task = await setup(tmp_path)
    staging = StagingService(workspaces, storage)
    record = await staging.create_staging_workspace(workspace.id, owner, task.id)
    await staging.write_staging_file(record.id, 'evidence.py', b'audit', owner)
    await staging.discard_staging_workspace(record.id, owner)
    assert await storage.read_file(record.staging_root_path + '/evidence.py') == b'audit'
    with pytest.raises(KeyError): await staging.get_staging_workspace(record.id, owner)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', ['traversal', 'submodule', 'oversize'])
async def test_repository_archive_rejects_unsafe_payload(payload, monkeypatch):
    from backend.app.services.zip_import import ZipImportService
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr({'traversal':'repo/../../escape','submodule':'repo/.gitmodules','oversize':'repo/a'}[payload], 'x')
    if payload == 'oversize': monkeypatch.setattr(ZipImportService, 'MAX_ZIP_BYTES', 10)
    with pytest.raises(ZipValidationError):
        await public_repository_files('https://github.com/a/b', transport=httpx.MockTransport(lambda request: httpx.Response(200,content=data.getvalue())))


@pytest.mark.asyncio
async def test_worker_unhandled_stage_error_persists_failure_without_secrets(tmp_path):
    owner, _, _, _, workflow, task = await setup(tmp_path)
    queue = LocalJobQueue(workflow)
    await queue.enqueue(task.id, owner)
    async def fail(job): raise ValueError('password=super-secret')
    with pytest.raises(ValueError): await DurableTaskWorker(queue, 'failing', {State.READY:fail}).run_once()
    assert (await workflow.get_task(task.id, owner)).status == State.FAILED
    assert 'super-secret' not in str(await workflow.get_history(task.id, owner))


@pytest.mark.asyncio
async def test_reclaimed_delivery_stops_after_budget(tmp_path):
    owner, _, _, _, workflow, task = await setup(tmp_path)
    queue = LocalJobQueue(workflow)
    job = await queue.enqueue(task.id, owner)
    job.attempts = 3
    handler = AsyncMock()
    await DurableTaskWorker(queue, 'recovering', {State.READY:handler}).run_once()
    handler.assert_not_called()
    assert (await workflow.get_task(task.id, owner)).status == State.FAILED
