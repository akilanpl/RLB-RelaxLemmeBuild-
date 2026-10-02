from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.models.task import ActorType
from backend.app.models.workspace import Workspace
from backend.app.repositories.task import InMemoryTaskRepository
from backend.app.services.device_control import CommandType
from backend.app.services.job_queue import LocalJobQueue
from backend.app.services.remote_command_router import RemoteCommandRouter
from backend.app.services.task_service import WorkflowEngine
from backend.app.workflow.states import WorkflowState


@pytest.mark.asyncio
async def test_remote_controls_use_existing_workflow_and_queue(tmp_path):
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    workspace = Workspace(
        id=uuid4(), user_id=user_id, name="local", slug="local",
        canonical_root_path="local", created_at=now, updated_at=now,
    )
    workflow = WorkflowEngine(repository=InMemoryTaskRepository())
    queue = LocalJobQueue(workflow)
    runtime = SimpleNamespace(workflow=workflow, queue=queue)
    router = RemoteCommandRouter(runtime)
    task = await workflow.create_task(workspace, user_id, "task", "objective")

    await router({"user_id": str(user_id), "command_type": CommandType.PAUSE_TASK,
                  "task_id": str(task.id), "payload": {}})
    assert await queue.is_paused(task.id)
    await router({"user_id": str(user_id), "command_type": CommandType.RESUME_TASK,
                  "task_id": str(task.id), "payload": {}})
    assert not await queue.is_paused(task.id)
    assert len(queue.jobs) == 1

    await router({"user_id": str(user_id), "command_type": CommandType.STOP_TASK,
                  "task_id": str(task.id), "payload": {}})
    assert (await workflow.get_task(task.id, user_id)).status == WorkflowState.CANCELLED


@pytest.mark.asyncio
async def test_remote_prompt_is_queued_and_approval_gate_is_not_bypassed():
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    workspace = Workspace(
        id=uuid4(), user_id=user_id, name="local", slug="local",
        canonical_root_path="local", created_at=now, updated_at=now,
    )
    workflow = WorkflowEngine(repository=InMemoryTaskRepository())
    queue = LocalJobQueue(workflow)
    router = RemoteCommandRouter(SimpleNamespace(workflow=workflow, queue=queue))
    task = await workflow.create_task(workspace, user_id, "task", "objective")
    await workflow.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None,
                              "started", expected_version=task.version)
    result = await router({
        "user_id": str(user_id), "command_type": CommandType.PROMPT,
        "task_id": str(task.id), "payload": {"prompt": "Continue the implementation."},
    })
    assert result["accepted"] is True
    assert await queue.pending_prompts(task.id) == ["Continue the implementation."]

    current = await workflow.get_task(task.id, user_id)
    await workflow.transition(current.id, WorkflowState.PLAN_REVIEW, ActorType.SYSTEM, None,
                              "approval needed", expected_version=current.version)
    with pytest.raises(ValueError, match="human approval"):
        await router({
            "user_id": str(user_id), "command_type": CommandType.PROMPT,
            "task_id": str(task.id), "payload": {"prompt": "Continue."},
        })
