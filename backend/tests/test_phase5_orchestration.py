import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.core.permissions import AgentPermissionGatekeeper, SecurityViolationError
from backend.app.main import app
from backend.app.models.agent import AgentRole


@pytest.mark.asyncio
async def test_task_workflow_and_stale_version_are_enforced():
    user_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        workspace = await client.post(
            "/api/v1/workspaces",
            data={"name": "Phase 5"},
            headers={"x-user-id": user_id},
        )
        task = await client.post(
            "/api/v1/tasks",
            json={
                "workspace_id": workspace.json()["id"],
                "title": "Add auth",
                "objective": "Add authentication",
            },
            headers={"x-user-id": user_id},
        )
        assert task.status_code == 201
        task_data = task.json()
        headers = {"x-user-id": user_id}
        first = await client.post(
            f"/api/v1/tasks/{task_data['id']}/transition",
            json={"target_state": "planning", "reason": "begin", "expected_version": 1},
            headers=headers,
        )
        assert first.status_code == 200
        stale = await client.post(
            f"/api/v1/tasks/{task_data['id']}/transition",
            json={"target_state": "plan_review", "reason": "stale", "expected_version": 1},
            headers=headers,
        )
        assert stale.status_code == 409
        history = await client.get(f"/api/v1/tasks/{task_data['id']}/history", headers=headers)
        assert len(history.json()) == 1


def test_agent_storage_boundary_is_executable():
    with pytest.raises(SecurityViolationError):
        AgentPermissionGatekeeper.assert_action_allowed(
            AgentRole.CODER, "APPROVED_FILE_WRITE", "/approved/app.py"
        )
    with pytest.raises(SecurityViolationError):
        AgentPermissionGatekeeper.assert_action_allowed(
            AgentRole.PLANNER, "STAGING_FILE_WRITE", "/staging/app.py", "/staging"
        )
    AgentPermissionGatekeeper.assert_action_allowed(
        AgentRole.CODER, "STAGING_FILE_WRITE", "/tmp/staging/app.py", "/tmp/staging"
    )
