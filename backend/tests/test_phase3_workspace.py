"""Comprehensive test suite for Phase 3 Workspace Provisioning, ZIP Ingestion, and Staging Isolation."""

import io
import uuid
import zipfile
import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.main import app
from backend.app.services.zip_import import ZipImportService, ZipValidationError
from backend.app.services.workspace_service import WorkspaceService, WorkspaceAccessDeniedError
from backend.app.services.staging_service import StagingService
from backend.app.models.workspace import EnvironmentMode, WorkspaceStatus


def create_mock_zip(files: dict[str, str]) -> bytes:
    """Helper to build an in-memory ZIP archive from a mapping of path -> content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_create_empty_workspace_api():
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/workspaces",
            data={
                "name": "Empty Test Project",
                "description": "A workspace with zero files",
                "environment_mode": "sandboxed",
            },
            headers={"x-user-id": user_id},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Empty Test Project"
        assert data["status"] == "ready"
        assert data["file_count"] == 0
        assert data["environment_mode"] == "sandboxed"


@pytest.mark.asyncio
async def test_create_workspace_with_valid_zip():
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    zip_bytes = create_mock_zip({
        "src/main.py": "print('Hello World')",
        "src/utils/helpers.py": "def add(a, b): return a + b",
        "README.md": "# Sample Project",
    })

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/workspaces",
            data={
                "name": "Python Application",
                "environment_mode": "sandboxed",
            },
            files={"file": ("project.zip", zip_bytes, "application/zip")},
            headers={"x-user-id": user_id},
        )
        assert response.status_code == 201
        ws = response.json()
        ws_id = ws["id"]
        assert ws["file_count"] == 3
        assert ws["status"] == "ready"

        # List files
        files_res = await client.get(
            f"/api/v1/workspaces/{ws_id}/files",
            headers={"x-user-id": user_id},
        )
        assert files_res.status_code == 200
        files = files_res.json()
        paths = [f["relative_path"] for f in files]
        assert "src/main.py" in paths
        assert "src/utils/helpers.py" in paths
        assert "README.md" in paths

        # Read file content
        content_res = await client.get(
            f"/api/v1/workspaces/{ws_id}/files/content",
            params={"path": "src/main.py"},
            headers={"x-user-id": user_id},
        )
        assert content_res.status_code == 200
        assert content_res.json()["content"] == "print('Hello World')"


@pytest.mark.asyncio
async def test_zip_security_path_traversal():
    """Verify that path traversal in ZIP members is strictly blocked."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:::")
    malicious_zip = buf.getvalue()

    with pytest.raises(ZipValidationError, match="Path traversal detected"):
        zf = ZipImportService.validate_zip_stream(malicious_zip)
        ZipImportService.sanitize_and_inspect_members(zf)


@pytest.mark.asyncio
async def test_zip_security_absolute_path():
    """Verify that absolute paths in ZIP members are strictly blocked."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/root/secret.txt", "confidential")
    malicious_zip = buf.getvalue()

    with pytest.raises(ZipValidationError, match="absolute path"):
        zf = ZipImportService.validate_zip_stream(malicious_zip)
        ZipImportService.sanitize_and_inspect_members(zf)


@pytest.mark.asyncio
async def test_zip_malformed_rejected():
    """Verify that corrupted non-ZIP data is rejected."""
    corrupted_data = b"This is not a zip file at all"
    with pytest.raises(ZipValidationError, match="valid ZIP archive"):
        ZipImportService.validate_zip_stream(corrupted_data)


@pytest.mark.asyncio
async def test_staging_workspace_isolation():
    """
    CRITICAL ARCHITECTURAL INVARIANT:
    Staging workspace mutations MUST NEVER modify the Approved Workspace.
    """
    user_id = uuid.uuid4()
    ws_service = WorkspaceService()
    staging_service = StagingService(workspace_service=ws_service)

    # 1. Create approved workspace with initial file
    initial_zip = create_mock_zip({"app.js": "console.log('approved v1');"})
    ws = await ws_service.create_workspace(
        user_id=user_id,
        name="Isolated Test App",
        zip_bytes=initial_zip,
    )

    # 2. Create staging copy
    staging = await staging_service.create_staging_workspace(ws.id, user_id)
    assert staging.is_active is True

    # 3. Read initial file in staging
    staging_bytes = await staging_service.read_staging_file(staging.id, "app.js", user_id)
    assert staging_bytes.decode() == "console.log('approved v1');"

    # 4. Mutate file inside staging workspace
    await staging_service.write_staging_file(
        staging.id, "app.js", b"console.log('staged coder change v2');", user_id
    )

    # 5. Verify staging has the updated content
    updated_staged = await staging_service.read_staging_file(staging.id, "app.js", user_id)
    assert updated_staged.decode() == "console.log('staged coder change v2');"

    # 6. Verify canonical Approved Workspace remains completely UNCHANGED
    approved_bytes = await ws_service.read_workspace_file(ws.id, "app.js", user_id)
    assert approved_bytes.decode() == "console.log('approved v1');"

    # 7. Discard staging
    await staging_service.discard_staging_workspace(staging.id, user_id)
    with pytest.raises(KeyError):
        await staging_service.get_staging_workspace(staging.id, user_id)


@pytest.mark.asyncio
async def test_workspace_ownership_isolation():
    """Verify that User A cannot read or access User B's workspace."""
    transport = ASGITransport(app=app)
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A creates a workspace
        create_res = await client.post(
            "/api/v1/workspaces",
            data={"name": "User A Private Repo"},
            headers={"x-user-id": user_a},
        )
        ws_id = create_res.json()["id"]

        # User B attempts to view User A's workspace -> 403 Forbidden
        denied_res = await client.get(
            f"/api/v1/workspaces/{ws_id}",
            headers={"x-user-id": user_b},
        )
        assert denied_res.status_code == 403

        # User B attempts to list files -> 403 Forbidden
        denied_files = await client.get(
            f"/api/v1/workspaces/{ws_id}/files",
            headers={"x-user-id": user_b},
        )
        assert denied_files.status_code == 403
