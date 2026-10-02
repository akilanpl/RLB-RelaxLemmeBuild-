import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from backend.app.services.device_connection import DeviceConnectionManager
from backend.app.models.task import ActorType
from backend.app.models.workspace import Workspace
from backend.app.repositories.sqlite_task import SQLiteTaskRepository
from backend.app.services.device_control import DeviceControlService
from backend.app.services.task_service import WorkflowEngine
from backend.app.workflow.states import WorkflowState


@pytest.mark.asyncio
async def test_connection_polls_executes_and_reports_ack_lifecycle(tmp_path):
    command_id = str(uuid4())
    posted_statuses = []
    calls = {"handler": 0}

    async def handler(request):
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"status": "ONLINE"})
        if request.url.path.endswith("/commands") and request.method == "GET":
            return httpx.Response(200, json=[{
                "id": command_id, "expires_at": "2099-01-01T00:00:00+00:00",
                "command_type": "PAUSE_TASK",
            }])
        if request.url.path.endswith(f"/commands/{command_id}"):
            posted_statuses.append(request.read().decode())
            return httpx.Response(200, json={"id": command_id})
        return httpx.Response(200, json={"status": "OFFLINE"})

    async def execute(command):
        calls["handler"] += 1
        return {"handled": command["command_type"]}

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = DeviceConnectionManager(
        "https://control.example", "opaque-device-token", tmp_path / "state.sqlite3",
        execute, client=client, heartbeat_seconds=30,
    )
    await manager.start()
    assert await manager.poll_once() == 1
    assert calls["handler"] == 1
    assert len(posted_statuses) == 3
    assert '"status":"ACKNOWLEDGED"' in posted_statuses[0]
    assert '"status":"EXECUTING"' in posted_statuses[1]
    assert '"status":"SUCCEEDED"' in posted_statuses[2]
    await manager.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_interrupted_remote_command_is_not_replayed(tmp_path):
    command_id = str(uuid4())
    executed = []
    statuses = []

    async def handler(request):
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/commands") and request.method == "GET":
            return httpx.Response(200, json=[{
                "id": command_id, "status": "EXECUTING",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }])
        if request.url.path.endswith(f"/commands/{command_id}"):
            statuses.append(request.read().decode())
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    async def execute(command):
        executed.append(command)
        return {}

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = DeviceConnectionManager(
        "https://control.example", "opaque", tmp_path / "state.sqlite3", execute, client=client,
    )
    await manager.start()
    manager._receipts[command_id] = "EXECUTING"
    await manager._store.save("remote_command_receipts", manager._receipts)
    assert await manager.poll_once() == 0
    assert executed == []
    assert '"status":"FAILED"' in statuses[0]
    await manager.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_successful_command_result_is_retried_without_reexecution(tmp_path):
    command_id = str(uuid4())
    executions = []
    status_updates = []
    fail_success_update = True

    async def handler(request):
        nonlocal fail_success_update
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/commands") and request.method == "GET":
            return httpx.Response(200, json=[{
                "id": command_id,
                "expires_at": "2099-01-01T00:00:00+00:00",
                "command_type": "START_TASK",
            }])
        if request.url.path.endswith(f"/commands/{command_id}"):
            update = json.loads(request.content)
            status_updates.append(update)
            if update["status"] == "SUCCEEDED" and fail_success_update:
                fail_success_update = False
                return httpx.Response(503, json={"detail": "temporary outage"})
            return httpx.Response(200, json={"id": command_id})
        return httpx.Response(200, json={})

    async def execute(command):
        executions.append(command)
        return {"task_id": str(uuid4())}

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = DeviceConnectionManager(
        "https://control.example", "opaque", tmp_path / "state.sqlite3",
        execute, client=client,
    )
    await manager.start()

    with pytest.raises(httpx.HTTPStatusError):
        await manager.poll_once()
    saved_result = manager._receipts[command_id]
    assert saved_result["status"] == "SUCCEEDED"
    assert saved_result["result"]["task_id"]

    assert await manager.poll_once() == 0
    assert len(executions) == 1
    assert status_updates[-1] == {
        "status": "SUCCEEDED", "result": saved_result["result"],
    }
    await manager.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_offline_event_outbox_is_acknowledged_only_after_server_acceptance(tmp_path):
    event = {
        "event_id": str(uuid4()), "task_id": str(uuid4()), "sequence": 2,
        "event_type": "planning", "payload": {"workflow_state": "planning"},
        "created_at": "2026-10-01T00:00:00+00:00", "source": "windows_runtime",
    }

    class EventSource:
        def __init__(self):
            self.pending = [event]
            self.acknowledged = []

        async def pending_events(self, limit):
            return self.pending[:limit]

        async def acknowledge_events(self, event_ids):
            self.acknowledged.extend(event_ids)
            self.pending = [item for item in self.pending if item["event_id"] not in event_ids]

    source = EventSource()
    async def handler(request):
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/device-session/events"):
            return httpx.Response(200, json={"accepted_event_ids": [event["event_id"]]})
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = DeviceConnectionManager(
        "https://control.example", "opaque", tmp_path / "state.sqlite3",
        lambda command: asyncio.sleep(0, result={}), client=client, event_source=source,
    )
    await manager.start()
    await manager.poll_once()
    assert source.acknowledged == [event["event_id"]]
    assert source.pending == []
    await manager.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_offline_task_events_survive_and_catch_up_once_after_reconnect(tmp_path):
    from datetime import datetime, timezone

    owner = uuid4()
    workspace = Workspace(
        id=uuid4(), user_id=owner, name="offline-project", slug="offline-project",
        canonical_root_path="local", created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repository = SQLiteTaskRepository(tmp_path / "tasks.sqlite3")
    workflow = WorkflowEngine(repository=repository)
    task = await workflow.create_task(workspace, owner, "offline task", "keep working offline")
    await workflow.transition(
        task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None,
        "planner started", expected_version=task.version,
    )
    expected_events = await repository.pending_events()

    control = DeviceControlService(tmp_path / "control.sqlite3")
    await control.start()
    pairing = await control.create_pairing(owner)
    device, secret = await control.pair(
        pairing["pairing_token"], name="Desktop", platform="windows", architecture="x64",
        app_version="1", runtime_version="1", capabilities={},
    )
    connected = False
    uploaded = []

    async def handler(request):
        if not connected:
            raise httpx.ConnectError("offline", request=request)
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"status": "ONLINE"})
        if request.url.path.endswith("/device-session/events"):
            body = json.loads(request.content)
            uploaded.extend(body["events"])
            accepted = await control.ingest_events(secret, body["events"])
            return httpx.Response(200, json={"accepted_event_ids": accepted})
        if request.url.path.endswith("/device-session/commands"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"status": "OFFLINE"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = DeviceConnectionManager(
        "https://control.example", secret, tmp_path / "connection.sqlite3",
        lambda command: asyncio.sleep(0, result={}), client=client, event_source=repository,
    )
    await manager.start()
    with pytest.raises(httpx.ConnectError):
        await manager.poll_once()
    assert await repository.pending_events() == expected_events

    connected = True
    await manager.poll_once()
    assert await repository.pending_events() == []
    assert [event["event_id"] for event in uploaded] == [
        event["event_id"] for event in expected_events
    ]
    page = await control.list_event_page(device.id, owner, limit=20)
    assert [event["event_id"] for event in page["events"]] == [
        event["event_id"] for event in expected_events
    ]
    await manager.poll_once()
    assert len(await control.list_events(device.id, owner)) == len(expected_events)
    await manager.close()
    await client.aclose()
    await repository.close()
    await control.close()
