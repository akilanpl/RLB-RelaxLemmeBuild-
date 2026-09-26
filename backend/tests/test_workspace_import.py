"""In-workspace project import into empty owned workspaces."""

import io
import uuid
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.app.services.zip_import import ZipImportService, ZipValidationError
from backend.app.services.workspace_service import WorkspaceService


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_import_zip_into_empty_owned_workspace():
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/workspaces",
            data={"name": "Empty Import Target", "environment_mode": "sandboxed"},
            headers={"x-user-id": user_id},
        )
        assert created.status_code == 201
        ws_id = created.json()["id"]
        assert created.json()["file_count"] == 0

        zip_bytes = _zip({"README.md": "# Imported", "src/app.ts": "export const x = 1;"})
        imported = await client.post(
            f"/api/v1/workspaces/{ws_id}/import/zip",
            files={"file": ("project.zip", zip_bytes, "application/zip")},
            headers={"x-user-id": user_id},
        )
        assert imported.status_code == 200, imported.text
        body = imported.json()
        assert body["file_count"] == 2
        assert body["status"] == "ready"

        files = await client.get(
            f"/api/v1/workspaces/{ws_id}/files",
            headers={"x-user-id": user_id},
        )
        paths = {f["relative_path"] for f in files.json()}
        assert paths == {"README.md", "src/app.ts"}


@pytest.mark.asyncio
async def test_import_files_folder_preserves_relative_paths():
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/workspaces",
            data={"name": "Folder Import", "environment_mode": "sandboxed"},
            headers={"x-user-id": user_id},
        )
        ws_id = created.json()["id"]

        response = await client.post(
            f"/api/v1/workspaces/{ws_id}/import/files",
            files=[
                ("files", ("index.js", b"console.log(1)", "application/javascript")),
                ("files", ("util.js", b"export {}", "application/javascript")),
                ("paths", (None, "pkg/index.js")),
                ("paths", (None, "pkg/lib/util.js")),
            ],
            headers={"x-user-id": user_id},
        )
        assert response.status_code == 200, response.text
        files = await client.get(
            f"/api/v1/workspaces/{ws_id}/files",
            headers={"x-user-id": user_id},
        )
        paths = {f["relative_path"] for f in files.json()}
        assert paths == {"pkg/index.js", "pkg/lib/util.js"}


@pytest.mark.asyncio
async def test_import_rejects_non_empty_workspace():
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/workspaces",
            data={"name": "Already Populated"},
            files={"file": ("seed.zip", _zip({"a.txt": "a"}), "application/zip")},
            headers={"x-user-id": user_id},
        )
        ws_id = created.json()["id"]
        assert created.json()["file_count"] == 1

        denied = await client.post(
            f"/api/v1/workspaces/{ws_id}/import/zip",
            files={"file": ("again.zip", _zip({"b.txt": "b"}), "application/zip")},
            headers={"x-user-id": user_id},
        )
        assert denied.status_code == 400
        assert "empty" in denied.json()["detail"].lower()


@pytest.mark.asyncio
async def test_import_path_traversal_and_absolute_rejected():
    service = WorkspaceService()
    user_id = uuid.uuid4()
    ws = await service.create_workspace(user_id=user_id, name="Safe Paths")

    with pytest.raises(ZipValidationError, match="Path traversal"):
        await service.import_project_into_empty_workspace(
            ws.id,
            user_id,
            files=[{"relative_path": "../etc/passwd", "content": b"x"}],
        )

    with pytest.raises(ZipValidationError, match="Absolute"):
        await service.import_project_into_empty_workspace(
            ws.id,
            user_id,
            files=[{"relative_path": "/tmp/evil.txt", "content": b"x"}],
        )


@pytest.mark.asyncio
async def test_import_cross_user_rejected():
    transport = ASGITransport(app=app)
    owner = str(uuid.uuid4())
    other = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/workspaces",
            data={"name": "Owner Empty"},
            headers={"x-user-id": owner},
        )
        ws_id = created.json()["id"]

        denied = await client.post(
            f"/api/v1/workspaces/{ws_id}/import/zip",
            files={"file": ("p.zip", _zip({"x.txt": "x"}), "application/zip")},
            headers={"x-user-id": other},
        )
        assert denied.status_code == 403

        denied_read = await client.get(
            f"/api/v1/workspaces/{ws_id}/files",
            headers={"x-user-id": other},
        )
        assert denied_read.status_code == 403


@pytest.mark.asyncio
async def test_import_file_count_quota():
    service = WorkspaceService()
    user_id = uuid.uuid4()
    ws = await service.create_workspace(user_id=user_id, name="Quota")
    too_many = [
        {"relative_path": f"f{i}.txt", "content": b"x"}
        for i in range(ZipImportService.MAX_FILE_COUNT + 1)
    ]
    with pytest.raises(ZipValidationError, match="file count"):
        await service.import_project_into_empty_workspace(ws.id, user_id, files=too_many)
