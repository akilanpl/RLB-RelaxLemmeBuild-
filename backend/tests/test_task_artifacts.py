from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException

from backend.app.models.workspace import Workspace
from backend.app.repositories.task import InMemoryTaskRepository
from backend.app.services.artifact_cleanup import cleanup_expired_task_artifacts
from backend.app.services.device_control import CommandType, DeviceControlService
from backend.app.services.device_connection import DeviceConnectionManager
from backend.app.services.remote_command_router import RemoteCommandRouter
from backend.app.services.task_artifacts import (
    MAX_ARTIFACT_BYTES,
    InMemoryTaskArtifactRepository,
    TaskArtifactService,
    safe_artifact_name,
    safe_relative_path,
)
from backend.app.api.v1 import devices as device_api
from backend.app.services.task_service import WorkflowEngine
from backend.app.storage.local import LocalStorageBackend


def test_artifact_names_and_source_paths_are_contained():
    assert safe_artifact_name("reports/result-1.txt") == "result-1.txt"
    assert safe_relative_path("reports/result-1.txt") == "reports/result-1.txt"
    for value in ("../secret.txt", r"..\secret.txt", "/absolute.txt", "C:/secret.txt", "folder//file"):
        with pytest.raises(ValueError):
            safe_relative_path(value)
    assert safe_artifact_name("../secret.txt") == "secret.txt"
    for value in ("CON.txt", "two;parts.txt", ""):
        with pytest.raises(ValueError):
            safe_artifact_name(value)


@pytest.mark.asyncio
async def test_artifact_metadata_is_task_user_device_scoped_and_expires(tmp_path):
    storage = LocalStorageBackend(tmp_path / "objects")
    repository = InMemoryTaskArtifactRepository()
    artifacts = TaskArtifactService(storage, repository=repository, retention_days=3)
    owner, device_id, task_id, workspace_id = (uuid4() for _ in range(4))
    metadata = await artifacts.create(
        user_id=owner, device_id=device_id, workspace_id=workspace_id,
        task_id=task_id, name="result.txt", content_type="text/plain", content=b"hello",
    )

    assert metadata["device_id"] == str(device_id)
    assert metadata["workspace_id"] == str(workspace_id)
    assert metadata["task_id"] == str(task_id)
    assert metadata["size_bytes"] == 5
    assert metadata["expires_at"] > metadata["created_at"]
    assert (await artifacts.list_for_task(task_id, owner, device_id))[0]["id"] == metadata["id"]
    assert await artifacts.list_for_task(task_id, uuid4()) == []
    assert await artifacts.get_metadata(
        uuid4(), owner, task_id, device_id,
    ) is None
    assert await artifacts.get_metadata(
        uuid4(), owner, task_id,
    ) is None
    assert await artifacts.read(
        uuid4(), owner, task_id, device_id,
    ) is None
    assert await artifacts.read(
        __import__("uuid").UUID(metadata["id"]), uuid4(), task_id, device_id,
    ) is None
    found, content = await artifacts.read(UUID(metadata["id"]), owner, task_id, device_id)
    assert found["sha256"] == metadata["sha256"]
    assert content == b"hello"

    repository.rows[metadata["id"]]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await artifacts.list_for_task(task_id, owner) == []
    assert await artifacts.read(UUID(metadata["id"]), owner) is None


@pytest.mark.asyncio
async def test_artifact_upload_enforces_cap_and_rolls_back_failed_metadata(tmp_path):
    storage = LocalStorageBackend(tmp_path / "objects")
    service = TaskArtifactService(storage, repository=InMemoryTaskArtifactRepository())
    with pytest.raises(ValueError, match="25 MiB"):
        await service.create(
            user_id=uuid4(), device_id=uuid4(), workspace_id=uuid4(), task_id=uuid4(),
            name="large.bin", content_type="application/octet-stream",
            content=b"x" * (MAX_ARTIFACT_BYTES + 1),
        )

    class BrokenRepository:
        async def create(self, row):
            raise RuntimeError("metadata write failed")

    rollback = TaskArtifactService(storage, repository=BrokenRepository())
    with pytest.raises(RuntimeError, match="metadata write failed"):
        await rollback.create(
            user_id=uuid4(), device_id=uuid4(), workspace_id=uuid4(), task_id=uuid4(),
            name="rollback.txt", content_type="text/plain", content=b"data",
        )
    assert await storage.list_files("task-artifacts") == []


class _WorkspaceService:
    def __init__(self, workspace, storage):
        self.workspace = workspace
        self.storage = storage

    async def get_workspace(self, workspace_id, user_id):
        assert workspace_id == self.workspace.id
        assert user_id == self.workspace.user_id
        return self.workspace


@pytest.mark.asyncio
async def test_remote_artifact_upload_and_download_stay_task_scoped(tmp_path):
    user_id, workspace_id = uuid4(), uuid4()
    workspace = Workspace(
        id=workspace_id, user_id=user_id, name="local", slug="local",
        canonical_root_path=f"workspaces/{workspace_id}/canonical",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    storage = LocalStorageBackend(tmp_path / "workspace-storage")
    workspace_service = _WorkspaceService(workspace, storage)
    workflow = WorkflowEngine(workspace_service, InMemoryTaskRepository())
    task = await workflow.create_task(workspace, user_id, "local task", "objective")

    class Connection:
        async def upload_task_artifact(self, task_id, workspace_id, name, content, content_type):
            assert task_id == task.id
            assert workspace_id == workspace.id
            assert name == "report.txt"
            assert content == b"local report"
            assert content_type == "text/plain"
            return {"id": str(uuid4()), "name": name, "size_bytes": len(content)}

        async def download_task_artifact(self, task_id, artifact_id):
            assert task_id == task.id
            return "received.txt", "text/plain", b"cloud report"

    runtime = SimpleNamespace(workflow=workflow, device_connection=Connection())
    router = RemoteCommandRouter(runtime)
    await storage.write_file(
        f"{workspace.canonical_root_path}/reports/report.txt", b"local report",
    )
    uploaded = await router({
        "user_id": str(user_id),
        "command_type": CommandType.REQUEST_ARTIFACT_UPLOAD,
        "task_id": str(task.id),
        "payload": {"relative_path": "reports/report.txt"},
    })
    assert uploaded["artifact"]["size_bytes"] == len(b"local report")

    with pytest.raises(ValueError, match="escapes"):
        await router({
            "user_id": str(user_id),
            "command_type": CommandType.REQUEST_ARTIFACT_UPLOAD,
            "task_id": str(task.id),
            "payload": {"relative_path": "../outside.txt"},
        })

    artifact_id = uuid4()
    downloaded = await router({
        "user_id": str(user_id),
        "command_type": CommandType.DOWNLOAD_ARTIFACT_TO_PC,
        "task_id": str(task.id),
        "payload": {"artifact_id": str(artifact_id)},
    })
    assert downloaded["relative_path"] == f"device-artifacts/{task.id}/{artifact_id}/received.txt"
    assert await storage.read_file(downloaded["relative_path"]) == b"cloud report"


@pytest.mark.asyncio
async def test_artifact_commands_require_device_task_association(tmp_path):
    control = DeviceControlService(tmp_path / "control.sqlite3")
    await control.start()
    user_id, task_id = uuid4(), uuid4()
    pairing = await control.create_pairing(user_id)
    device, secret = await control.pair(
        pairing["pairing_token"], name="Workstation", platform="windows",
        architecture="x64", app_version="1", runtime_version="1", capabilities={},
    )
    with pytest.raises(LookupError, match="not associated"):
        await control.enqueue_command(
            device.id, user_id, CommandType.REQUEST_ARTIFACT_UPLOAD,
            {"relative_path": "report.txt"}, "artifact-upload-0001", task_id,
        )

    await control.heartbeat(
        secret, runtime_state="running", current_task_id=task_id,
        app_version="1", runtime_version="1", capabilities={},
    )
    command = await control.enqueue_command(
        device.id, user_id, CommandType.REQUEST_ARTIFACT_UPLOAD,
        {"relative_path": "report.txt"}, "artifact-upload-0002", task_id,
    )
    assert command.task_id == task_id


@pytest.mark.asyncio
async def test_artifact_api_upload_and_authenticated_retrieval_bind_device_user_task(monkeypatch, tmp_path):
    user_id, device_id, task_id, workspace_id = (uuid4() for _ in range(4))
    storage = LocalStorageBackend(tmp_path / "objects")
    service = TaskArtifactService(storage, repository=InMemoryTaskArtifactRepository())

    class Control:
        async def authenticate_device(self, secret):
            assert secret == "device-secret"
            return SimpleNamespace(id=device_id, user_id=user_id)

        async def authorize_task_for_device(self, requested_device, requested_user, requested_task):
            assert (requested_device, requested_user, requested_task) == (device_id, user_id, task_id)

        async def workspace_for_device_task(self, requested_device, requested_user, requested_task):
            await self.authorize_task_for_device(requested_device, requested_user, requested_task)
            return workspace_id

    monkeypatch.setattr(device_api, "control", Control())
    monkeypatch.setattr(device_api, "_artifact_service", lambda: service)
    mismatched = device_api.UploadFile(file=BytesIO(b"wrong"), filename="wrong.txt")
    with pytest.raises(HTTPException) as denied:
        await device_api.upload_task_artifact(
            task_id, uuid4(), mismatched, "Bearer device-secret",
        )
    assert denied.value.status_code == 403
    upload = device_api.UploadFile(file=BytesIO(b"synced"), filename="result.txt")
    metadata = await device_api.upload_task_artifact(
        task_id, workspace_id, upload, "Bearer device-secret",
    )
    assert metadata["workspace_id"] == str(workspace_id)

    auth = SimpleNamespace(user_id=user_id)
    listing = await device_api.list_device_task_artifacts(device_id, task_id, auth)
    assert [artifact["id"] for artifact in listing] == [metadata["id"]]
    response = await device_api.download_device_task_artifact(
        device_id, task_id, UUID(metadata["id"]), auth,
    )
    assert response.body == b"synced"
    assert response.headers["content-disposition"] == 'attachment; filename="result.txt"'

    device_response = await device_api.download_task_artifact_to_device(
        task_id, UUID(metadata["id"]), "Bearer device-secret",
    )
    assert device_response.body == b"synced"


@pytest.mark.asyncio
async def test_device_connection_transfers_artifacts_only_through_authenticated_routes(tmp_path):
    task_id, workspace_id, artifact_id = uuid4(), uuid4(), uuid4()
    observed = []

    async def respond(request):
        observed.append((request.method, request.url.path, request.headers.get("authorization"), request.content))
        if request.method == "POST":
            return httpx.Response(200, json={"id": str(artifact_id), "name": "report.txt"})
        if request.method == "GET":
            return httpx.Response(
                200, content=b"download", headers={
                    "content-type": "text/plain", "x-artifact-name": "report.txt",
                },
            )
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    manager = DeviceConnectionManager(
        "https://control.example", "device-secret", tmp_path / "connection.sqlite3",
        lambda command: None, client=client,
    )
    uploaded = await manager.upload_task_artifact(
        task_id, workspace_id, "report.txt", b"upload", "text/plain",
    )
    assert uploaded["id"] == str(artifact_id)
    name, content_type, content = await manager.download_task_artifact(task_id, artifact_id)
    assert (name, content_type, content) == ("report.txt", "text/plain", b"download")
    assert len(observed) == 2
    assert all(row[2] == "Bearer device-secret" for row in observed)
    assert str(workspace_id).encode() in observed[0][3]
    assert b"upload" in observed[0][3]
    await manager.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_expired_artifact_cleanup_tombstones_then_deletes_only_safe_object_path():
    artifact_id = uuid4()
    path = f"task-artifacts/{uuid4()}/{uuid4()}/{artifact_id}/result.txt"

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [{"id": artifact_id, "object_path": path}]

    class Connection:
        async def execute(self, statement, params=None):
            if "SELECT id,object_path" in str(statement):
                return Result()
            return Result()

    class Transaction:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return False

    class Engine:
        def begin(self):
            return Transaction()

    class Storage:
        def __init__(self):
            self.removed = []

        async def delete_file(self, object_path):
            self.removed.append(object_path)

    storage = Storage()
    assert await cleanup_expired_task_artifacts(Engine(), storage) == 1
    assert storage.removed == [path]
