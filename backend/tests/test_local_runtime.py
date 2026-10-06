import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.models.workspace import Workspace
from backend.app.models.task import ActorType
from backend.app.repositories.sqlite_task import SQLiteTaskRepository
from backend.app.services.job_queue import JobStatus
from backend.app.services.local_queue import SQLiteJobQueue
from backend.app.services.task_service import WorkflowEngine
from backend.app.sandbox.local import LocalWindowsSandboxDriver
from backend.app.sandbox.types import SandboxCommand, SandboxLimits
from backend.app.workflow.states import WorkflowState


def workspace(user_id):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return Workspace(id=uuid4(), user_id=user_id, name="local", slug="local",
                     canonical_root_path="local", created_at=now, updated_at=now)


@pytest.mark.asyncio
async def test_sqlite_task_and_queue_recover_after_reconstruction(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TASKS_PER_USER_PER_HOUR", "100")
    user_id = uuid4()
    db = tmp_path / "runtime.sqlite3"
    engine = WorkflowEngine(repository=SQLiteTaskRepository(db))
    task = await engine.create_task(workspace(user_id), user_id, "persist", "objective")
    await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None,
                            "analysis complete", expected_version=task.version)
    local_repository = engine.repository
    pending_events = await local_repository.pending_events()
    assert [event["sequence"] for event in pending_events] == [1, 2]
    assert [event["event_type"] for event in pending_events] == ["task_created", "planning"]
    assert pending_events[0]["payload"] == {
        "workflow_state": "ready",
        "version": 1,
        "workspace_id": str(task.workspace_id),
    }
    queue = SQLiteJobQueue(engine, db)
    job = await queue.enqueue(task.id, user_id)
    claimed = await queue.claim("worker")
    assert claimed.id == job.id
    await queue.pause_task(task.id, user_id)

    restored_repo = SQLiteTaskRepository(db)
    await restored_repo.load()
    restored_engine = WorkflowEngine(repository=restored_repo)
    assert (await restored_engine.get_task(task.id, user_id)).title == "persist"
    restored_events = await restored_repo.pending_events()
    assert [event["event_id"] for event in restored_events] == [
        event["event_id"] for event in pending_events
    ]
    assert [event["sequence"] for event in restored_events] == [1, 2]
    assert restored_events[0]["payload"]["workspace_id"] == str(task.workspace_id)
    await restored_repo.acknowledge_events([event["event_id"] for event in pending_events])
    assert await restored_repo.pending_events() == []
    restored_queue = SQLiteJobQueue(restored_engine, db)
    await restored_queue.load()
    assert restored_queue.jobs[job.id].status == JobStatus.PENDING
    assert await restored_queue.is_paused(task.id)
    assert await restored_queue.claim("recovered-worker") is None
    await restored_queue.resume_task(task.id, user_id)
    assert (await restored_queue.claim("recovered-worker")).id == job.id


@pytest.mark.asyncio
async def test_local_driver_containment_output_and_timeout(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    driver = LocalWindowsSandboxDriver()
    handle = await driver.create_sandbox(uuid4(), str(root), SandboxLimits(timeout_seconds=1))
    result = await driver.execute_command(handle, SandboxCommand(cmd='python -c "import sys; sys.stdout.write(\'out\'); sys.stderr.write(\'err\')"'))
    assert result.exit_code == 0
    assert result.stdout == "out"
    assert result.stderr == "err"

    with pytest.raises(ValueError, match="escapes"):
        await driver.execute_command(handle, SandboxCommand(cmd="pwd", cwd=".."))

    timeout = await driver.execute_command(handle, SandboxCommand(cmd='python -c "import time; time.sleep(2)"', timeout_seconds=1))
    assert timeout.timed_out is True
    await driver.destroy_sandbox(handle)
