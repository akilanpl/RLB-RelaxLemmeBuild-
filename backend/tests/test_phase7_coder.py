import json
from uuid import uuid4

import pytest

from backend.app.ai.gateway import AIGateway, AIRequest, AIResponse
from backend.app.models.task import ActorType
from backend.app.services.coder_service import CoderService
from backend.app.services.staging_service import StagingService
from backend.app.services.task_service import WorkflowEngine
from backend.app.services.workspace_service import WorkspaceService
from backend.app.storage.local import LocalStorageBackend
from backend.app.workflow.states import WorkflowState


class MockGateway(AIGateway):
    def validate_configuration(self):
        pass

    async def generate(self, request: AIRequest):
        return AIResponse(content=json.dumps({
            "summary": "Update greeting",
            "commit_message": "Update greeting",
            "changes": [{"path": "app.py", "operation": "modify", "content": "print('hi')\n"}],
            "impact": {"affected_files": ["app.py"], "risks": [], "tests": []},
        }))


@pytest.mark.asyncio
async def test_coder_only_changes_staging_and_produces_stable_diff(tmp_path):
    user_id = uuid4()
    storage = LocalStorageBackend(tmp_path)
    workspaces = WorkspaceService(storage)
    workspace = await workspaces.create_workspace(user_id, "Coder")
    await storage.write_file(f"{workspace.canonical_root_path}/app.py", b"print('hello')\n")
    workspace.current_snapshot_hash = "snapshot-1"
    staging_service = StagingService(workspaces, storage)
    staging = await staging_service.create_staging_workspace(workspace.id, user_id)

    engine = WorkflowEngine(workspace_service=workspaces)
    task = await engine.create_task(workspace, user_id, "Greeting", "Update greeting")
    task = await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None, "test")
    task = await engine.transition(task.id, WorkflowState.PLAN_REVIEW, ActorType.SYSTEM, None, "test")
    task = await engine.transition(task.id, WorkflowState.CODING, ActorType.SYSTEM, None, "test")
    service = CoderService(MockGateway(), staging_service=staging_service, workflow=engine)

    proposal = await service.execute(task.id, user_id, staging.id)
    assert proposal.diffs[0].file_path == "app.py"
    assert await storage.read_file(f"{workspace.canonical_root_path}/app.py") == b"print('hello')\n"
    assert await staging_service.read_staging_file(staging.id, "app.py", user_id) == b"print('hi')\n"


@pytest.mark.asyncio
async def test_staging_path_jail_and_isolation(tmp_path):
    user_id = uuid4()
    storage = LocalStorageBackend(tmp_path)
    workspaces = WorkspaceService(storage)
    workspace = await workspaces.create_workspace(user_id, "Isolation")
    await storage.write_file(f"{workspace.canonical_root_path}/keep.txt", b"approved")
    staging_service = StagingService(workspaces, storage)
    staging = await staging_service.create_staging_workspace(workspace.id, user_id)

    with pytest.raises(ValueError):
        await staging_service.write_staging_file(staging.id, "../escape.txt", b"no", user_id)
    await staging_service.write_staging_file(staging.id, "new.txt", b"staged", user_id)
    await staging_service.delete_staging_file(staging.id, "keep.txt", user_id)

    assert await storage.read_file(f"{workspace.canonical_root_path}/keep.txt") == b"approved"
    with pytest.raises(FileNotFoundError):
        await storage.read_file(f"{workspace.canonical_root_path}/new.txt")
