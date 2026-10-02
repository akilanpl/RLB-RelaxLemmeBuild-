import uuid
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.app.models.task import ActorType
from backend.app.models.test import TestPlan as PersistedTestPlan
from backend.app.repositories.task import InMemoryTaskRepository
from backend.app.repositories.testing import InMemoryTestingRepository
from backend.app.services.zip_import import ZipValidationError
from backend.app.services.task_service import WorkflowEngine
from backend.app.services.test_orchestrator import TestOrchestrationService as TestRunner
from backend.app.services.workspace_service import WorkspaceService
from backend.app.storage.local import LocalStorageBackend
from backend.app.workflow.states import WorkflowState

TestRunner.__test__ = False


@pytest.fixture
def project_sandbox():
    root = Path(__file__).resolve().parent / f".local-registration-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_local_workspace_persists_and_refreshes_selected_folder(project_sandbox, monkeypatch):
    user_id = uuid.uuid4()
    project = project_sandbox / "project"
    project.mkdir()
    (project / "README.md").write_text("first snapshot")
    outside = project_sandbox / "outside.txt"
    outside.write_text("must not be imported")
    try:
        (project / "escape.txt").symlink_to(outside)
    except OSError:
        pass

    registry = project_sandbox / "runtime.sqlite3"
    storage = LocalStorageBackend(project_sandbox / "workspace-storage")
    service = WorkspaceService(storage, local_registry_path=registry)
    monkeypatch.setattr(
        WorkspaceService,
        "_local_git_metadata",
        staticmethod(lambda root: {
            "git_remote_url": None, "git_branch": None, "git_status": None,
        }),
    )
    workspace = await service.register_local_workspace(
        user_id, "Selected project", str(project), "Local test project"
    )

    assert workspace.local_path == str(project.resolve())
    assert workspace.file_count == 1
    assert "escape.txt" not in {
        item["relative_path"] for item in await service.list_workspace_files(workspace.id, user_id)
    }

    reopened_service = WorkspaceService(
        LocalStorageBackend(project_sandbox / "workspace-storage"),
        local_registry_path=registry,
    )
    reopened = await reopened_service.get_workspace(workspace.id, user_id)
    assert reopened.local_path == str(project.resolve())
    assert reopened.git_branch is None
    assert await reopened_service.read_workspace_file(workspace.id, "README.md", user_id) == b"first snapshot"

    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('latest project')")
    refreshed = await reopened_service.refresh_local_workspace(workspace.id, user_id)
    assert refreshed.id == workspace.id
    assert refreshed.file_count == 2
    assert await reopened_service.read_workspace_file(workspace.id, "src/app.py", user_id) == b"print('latest project')"
    registered_again = await reopened_service.register_local_workspace(
        user_id, "A second label", str(project)
    )
    assert registered_again.id == workspace.id

    task_engine = WorkflowEngine(reopened_service, InMemoryTaskRepository())
    task = await task_engine.create_task(refreshed, user_id, "Use selected project", "Inspect it")
    assert task.workspace_id == workspace.id
    assert task.approved_snapshot_hash == refreshed.current_snapshot_hash


def test_local_git_metadata_detects_remote_branch_and_worktree(monkeypatch, project_sandbox):
    import subprocess

    outputs = {
        "rev-parse": "feature/local",
        "remote": "https://example.test/team/project.git",
        "status": " M src/app.py\n?? notes.txt",
    }

    def fake_run(command, **kwargs):
        response = next(value for key, value in outputs.items() if key in command)
        return SimpleNamespace(returncode=0, stdout=response)

    monkeypatch.setattr(subprocess, "run", fake_run)
    metadata = WorkspaceService._local_git_metadata(project_sandbox)
    assert metadata == {
        "git_remote_url": "https://example.test/team/project.git",
        "git_branch": "feature/local",
        "git_status": "2 uncommitted change(s)",
    }


def test_local_git_metadata_redacts_remote_credentials(monkeypatch, project_sandbox):
    import subprocess

    outputs = {
        "rev-parse": "main",
        "remote": "https://user:secret@example.test/team/project.git?token=private",
        "status": "",
    }

    def fake_run(command, **kwargs):
        response = next(value for key, value in outputs.items() if key in command)
        return SimpleNamespace(returncode=0, stdout=response)

    monkeypatch.setattr(subprocess, "run", fake_run)
    metadata = WorkspaceService._local_git_metadata(project_sandbox)
    assert metadata["git_remote_url"] == "https://example.test/team/project.git"


@pytest.mark.asyncio
async def test_local_folder_registration_and_task_creation_api_use_same_workspace(project_sandbox, monkeypatch):
    from backend.app.services import runtime as runtime_module
    from backend.app.api.v1 import workspaces as workspaces_module
    from backend.app.core.config import Settings

    project = project_sandbox / "api-project"
    project.mkdir()
    (project / "main.py").write_text("print('before')")
    registry = project_sandbox / "api-runtime.sqlite3"
    storage = LocalStorageBackend(project_sandbox / "api-storage")
    service = WorkspaceService(storage, local_registry_path=registry)

    class Queue:
        async def enqueue(self, task_id, user_id):
            self.last = (task_id, user_id)

    queue = Queue()
    monkeypatch.setattr(runtime_module, "_runtime", SimpleNamespace(
        workspace=service,
        workflow=WorkflowEngine(service, InMemoryTaskRepository()),
        queue=queue,
    ))
    monkeypatch.setattr(workspaces_module, "get_settings", lambda: Settings(ENVIRONMENT="test"))
    user_id = str(uuid.uuid4())
    local_token = "test-local-token"
    monkeypatch.setenv("RLB_LOCAL_API_TOKEN", local_token)
    headers = {"x-user-id": user_id, "X-RLB-Local-Token": local_token}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registered = await client.post(
            "/api/v1/workspaces/local",
            json={"name": "API project", "path": str(project)},
            headers=headers,
        )
        assert registered.status_code == 201, registered.text
        workspace_id = registered.json()["id"]
        assert registered.json()["local_path"] == str(project.resolve())

        (project / "main.py").write_text("print('changed before task')")
        (project / "extra.txt").write_text("current")
        created = await client.post(
            "/api/v1/tasks",
            json={"workspace_id": workspace_id, "title": "Inspect exact folder", "objective": "Inspect it"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["workspace_id"] == workspace_id

        files = await client.get(f"/api/v1/workspaces/{workspace_id}/files", headers=headers)
        assert files.status_code == 200
        assert {item["relative_path"] for item in files.json()} == {"main.py", "extra.txt"}
        assert (str(queue.last[0]), str(queue.last[1])) == (created.json()["id"], user_id)


@pytest.mark.asyncio
async def test_local_workspace_refresh_api_is_available_in_test_environment(project_sandbox, monkeypatch):
    from backend.app.services import runtime as runtime_module
    from backend.app.api.v1 import workspaces as workspaces_module
    from backend.app.core.config import Settings

    project = project_sandbox / "refresh-project"
    project.mkdir()
    (project / "main.py").write_text("print('before')")
    service = WorkspaceService(
        LocalStorageBackend(project_sandbox / "refresh-storage"),
        local_registry_path=project_sandbox / "refresh-registry.sqlite3",
    )
    monkeypatch.setattr(
        runtime_module,
        "_runtime",
        SimpleNamespace(workspace=service),
    )
    monkeypatch.setattr(workspaces_module, "get_settings", lambda: Settings(ENVIRONMENT="test"))
    user_id = str(uuid.uuid4())
    local_token = "test-local-token"
    monkeypatch.setenv("RLB_LOCAL_API_TOKEN", local_token)
    headers = {"x-user-id": user_id, "X-RLB-Local-Token": local_token}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registered = await client.post(
            "/api/v1/workspaces/local",
            json={"name": "Refresh project", "path": str(project)},
            headers=headers,
        )
        assert registered.status_code == 201, registered.text
        workspace_id = registered.json()["id"]

        (project / "main.py").write_text("print('after')")
        refreshed = await client.post(
            f"/api/v1/workspaces/{workspace_id}/local/refresh",
            headers=headers,
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["current_snapshot_hash"] != registered.json()["current_snapshot_hash"]
        assert await service.read_workspace_file(
            uuid.UUID(workspace_id), "main.py", uuid.UUID(user_id)
        ) == b"print('after')"


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.asyncio
async def test_local_workspace_endpoints_remain_blocked_in_hosted_environments(
    project_sandbox, monkeypatch, environment
):
    from backend.app.api.v1 import workspaces as workspaces_module
    from backend.app.core.auth import AuthenticatedUserContext, get_authenticated_user
    from backend.app.core.config import Settings

    monkeypatch.setattr(
        workspaces_module, "get_settings", lambda: Settings(ENVIRONMENT=environment)
    )
    auth = AuthenticatedUserContext(uuid.uuid4(), {})
    monkeypatch.setitem(app.dependency_overrides, get_authenticated_user, lambda: auth)
    local_token = "test-local-token"
    monkeypatch.setenv("RLB_LOCAL_API_TOKEN", local_token)
    headers = {"X-RLB-Local-Token": local_token}
    workspace_id = uuid.uuid4()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        registered = await client.post(
            "/api/v1/workspaces/local",
            json={"name": "Blocked project", "path": str(project_sandbox)},
            headers=headers,
        )
        refreshed = await client.post(
            f"/api/v1/workspaces/{workspace_id}/local/refresh",
            headers=headers,
        )

    assert registered.status_code == 404
    assert refreshed.status_code == 404


@pytest.mark.asyncio
async def test_local_workspace_rejects_missing_folder_and_traversal(project_sandbox):
    service = WorkspaceService(
        LocalStorageBackend(project_sandbox / "storage"),
        local_registry_path=project_sandbox / "registry.sqlite3",
    )
    user_id = uuid.uuid4()
    with pytest.raises(ValueError, match="unavailable"):
        await service.register_local_workspace(user_id, "Missing", str(project_sandbox / "missing"))

    project = project_sandbox / "project"
    project.mkdir()
    (project / "nested").mkdir()
    with pytest.raises(ZipValidationError, match="Path traversal"):
        service._normalize_import_path("nested/../../outside.txt")


@pytest.mark.asyncio
async def test_approved_local_snapshot_is_contained_and_refuses_external_changes(
    project_sandbox, monkeypatch
):
    project = project_sandbox / "project"
    project.mkdir()
    (project / "app.py").write_text("original")
    service = WorkspaceService(
        LocalStorageBackend(project_sandbox / "storage"),
        local_registry_path=project_sandbox / "registry.sqlite3",
    )
    monkeypatch.setattr(
        WorkspaceService,
        "_local_git_metadata",
        staticmethod(lambda root: {
            "git_remote_url": None, "git_branch": None, "git_status": None,
        }),
    )
    user_id = uuid.uuid4()
    workspace = await service.register_local_workspace(user_id, "Project", str(project))
    previous_records = await service.list_workspace_files(workspace.id, user_id)

    with pytest.raises(ZipValidationError, match="Path traversal"):
        await service._publish_local_snapshot(
            workspace, {"../../outside.txt": b"blocked"}, previous_records
        )

    await service._publish_local_snapshot(
        workspace,
        {"app.py": b"approved", "src/new.py": b"new"},
        previous_records,
    )
    assert (project / "app.py").read_bytes() == b"approved"
    assert (project / "src" / "new.py").read_bytes() == b"new"

    (project / "app.py").write_text("external edit")
    with pytest.raises(ValueError, match="changed"):
        await service._publish_local_snapshot(
            workspace, {"app.py": b"must not overwrite"}, previous_records
        )
    assert (project / "app.py").read_text() == "external edit"


@pytest.mark.asyncio
async def test_test_executor_receives_exact_registered_local_task_root(project_sandbox, monkeypatch):
    from backend.app.services import test_orchestrator

    project = project_sandbox / "task-root-project"
    project.mkdir()
    (project / "app.py").write_text("selected project content")
    user_id = uuid.uuid4()
    workspace_service = WorkspaceService(
        LocalStorageBackend(project_sandbox / "storage"),
        local_registry_path=project_sandbox / "registry.sqlite3",
    )
    workspace = await workspace_service.register_local_workspace(
        user_id, "Task root", str(project)
    )
    workflow = WorkflowEngine(workspace_service, InMemoryTaskRepository())
    task = await workflow.create_task(workspace, user_id, "Exact root", "Run selected project tests")
    for state in (
        WorkflowState.PLANNING,
        WorkflowState.PLAN_REVIEW,
        WorkflowState.CODING,
        WorkflowState.CODE_REVIEW,
        WorkflowState.PROMOTING,
        WorkflowState.TEST_PLANNING,
        WorkflowState.TEST_EXECUTING,
    ):
        task = await workflow.transition(
            task.id, state, ActorType.SYSTEM, None, "Test local task root",
            expected_version=task.version,
        )

    repository = InMemoryTestingRepository()
    await repository.add_plan(PersistedTestPlan(
        id=uuid.uuid4(), task_id=task.id, agent_run_id=uuid.uuid4(),
        plan_summary="verify selected root", test_cases=[], created_at=task.created_at,
    ))
    captured = {}

    class CapturingExecutor:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, task_id, run_id, workspace_id, staging_root, plan):
            captured["root"] = staging_root
            captured["workspace_id"] = workspace_id
            return SimpleNamespace(id=uuid.uuid4(), all_passed=True)

    monkeypatch.setattr(test_orchestrator, "TestExecutorService", CapturingExecutor)
    orchestrator = TestRunner(workflow, repository, sandbox=object())
    await orchestrator.plan_and_execute(task.id, user_id)

    assert captured == {
        "root": str(project.resolve()),
        "workspace_id": workspace.id,
    }
