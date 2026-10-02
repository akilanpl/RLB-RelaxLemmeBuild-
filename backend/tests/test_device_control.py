import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from backend.app.services.device_control import (
    CommandStatus, CommandType, DeviceControlService, DeviceStatus, utcnow,
)


async def paired_control(tmp_path, user_id=None):
    service = DeviceControlService(tmp_path / "control.sqlite3")
    await service.start()
    owner = user_id or uuid4()
    pairing = await service.create_pairing(owner)
    device, secret = await service.pair(
        pairing["pairing_token"], name="Desktop", platform="windows",
        architecture="x64", app_version="1", runtime_version="1",
        capabilities={"local_execution": True},
    )
    return service, owner, device, secret, pairing


@pytest.mark.asyncio
async def test_pairing_is_one_time_and_device_is_user_scoped(tmp_path):
    service, owner, device, secret, pairing = await paired_control(tmp_path)
    with pytest.raises(ValueError, match="invalid, expired, or already used"):
        await service.pair(
            pairing["pairing_token"], name="Replay", platform="windows",
            architecture="x64", app_version="1", runtime_version="1", capabilities={},
        )
    assert (await service.get_device(device.id, owner)).status == DeviceStatus.ONLINE
    with pytest.raises(PermissionError):
        await service.get_device(device.id, uuid4())
    assert (await service.authenticate_device(secret)).id == device.id


@pytest.mark.asyncio
async def test_expiry_revoke_and_revoke_invalidates_device_credential(tmp_path):
    service, owner, device, secret, pairing = await paired_control(tmp_path)
    pending = await service.enqueue_command(
        device.id, owner, CommandType.PAUSE_TASK, {}, "queued-before-revoke"
    )
    service._state["pairings"][service._digest(pairing["pairing_token"])]["expires_at"] = utcnow() - timedelta(seconds=1)
    extra = await service.create_pairing(owner)
    service._state["pairings"][service._digest(extra["pairing_token"])]["expires_at"] = utcnow() - timedelta(seconds=1)
    with pytest.raises(ValueError, match="expired"):
        await service.pair(
            extra["pairing_token"], name="Expired", platform="windows",
            architecture="x64", app_version="1", runtime_version="1", capabilities={},
        )
    revoked = await service.revoke(device.id, owner)
    assert revoked.status == DeviceStatus.REVOKED
    assert (await service.list_commands(device.id, owner))[0].status == CommandStatus.FAILED
    with pytest.raises(PermissionError, match="revoked"):
        await service.authenticate_device(secret)


@pytest.mark.asyncio
async def test_remote_commands_are_idempotent_delivered_and_terminal(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    first = await service.enqueue_command(
        device.id, owner, CommandType.PAUSE_TASK, {}, "pause-command-0001"
    )
    duplicate = await service.enqueue_command(
        device.id, owner, CommandType.PAUSE_TASK, {}, "pause-command-0001"
    )
    assert duplicate.id == first.id
    with pytest.raises(PermissionError):
        await service.enqueue_command(device.id, uuid4(), CommandType.STOP_TASK, {}, "wrong-owner-key")

    delivered = await service.claim_commands(secret)
    assert [command.id for command in delivered] == [first.id]
    with pytest.raises(ValueError, match="Invalid command transition"):
        await service.update_command(secret, first.id, CommandStatus.SUCCEEDED)
    await service.update_command(secret, first.id, CommandStatus.ACKNOWLEDGED)
    await service.update_command(secret, first.id, CommandStatus.EXECUTING)
    completed = await service.update_command(
        secret, first.id, CommandStatus.SUCCEEDED, result={"accepted": True}
    )
    assert completed.status == CommandStatus.SUCCEEDED
    assert (await service.list_commands(device.id, owner))[0].result == {"accepted": True}


@pytest.mark.asyncio
async def test_claimed_command_is_not_redelivered_until_claim_lease_expires(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    command = await service.enqueue_command(
        device.id, owner, CommandType.START_TASK, {"workspace_id": str(uuid4())},
        "claim-lease-command",
    )

    claimant, other_claimant = uuid4(), uuid4()
    first_claim = await service.claim_commands(secret, claimant)
    assert [item.id for item in first_claim] == [command.id]
    assert first_claim[0].claim_until is not None
    assert [item.id for item in await service.claim_commands(secret, claimant)] == [command.id]
    assert await service.claim_commands(secret, other_claimant) == []

    stored = service._state["commands"][str(command.id)]
    stored["claim_until"] = (utcnow() - timedelta(seconds=1)).isoformat()
    await service._save()
    assert [item.id for item in await service.claim_commands(secret, other_claimant)] == [command.id]
    await service.close()


@pytest.mark.asyncio
async def test_expired_command_is_terminal_and_never_delivered(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    command = await service.enqueue_command(
        device.id, owner, CommandType.START_TASK, {"workspace_id": str(uuid4())},
        "expired-command-key",
    )
    raw = service._state["commands"][str(command.id)]
    raw["expires_at"] = (utcnow() - timedelta(seconds=1)).isoformat()
    await service._save()

    assert await service.claim_commands(secret) == []
    stored = await service.list_commands(device.id, owner)
    assert stored[0].status == CommandStatus.EXPIRED
    assert stored[0].completed_at is not None


@pytest.mark.asyncio
async def test_heartbeat_updates_presence_and_offline_staleness(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    device = await service.heartbeat(
        secret, runtime_state="paused", current_task_id=None,
        app_version="1.2", runtime_version="2.0", capabilities={"workflow": True},
    )
    assert device.status == DeviceStatus.ONLINE
    assert device.runtime_state == "paused"
    assert device.app_version == "1.2"
    service._state["devices"][str(device.id)]["last_seen_at"] = (
        utcnow() - timedelta(seconds=181)
    ).isoformat()
    assert (await service.get_device(device.id, owner)).status == DeviceStatus.OFFLINE


@pytest.mark.asyncio
async def test_revoke_waits_for_inflight_heartbeat_without_being_overwritten(tmp_path, monkeypatch):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    entered_save = asyncio.Event()
    allow_save = asyncio.Event()
    original_save = service._save

    async def paused_save():
        entered_save.set()
        await allow_save.wait()
        await original_save()

    monkeypatch.setattr(service, "_save", paused_save)
    heartbeat = asyncio.create_task(service.heartbeat(
        secret, runtime_state="running", current_task_id=None,
        app_version="1", runtime_version="1", capabilities={},
    ))
    await entered_save.wait()
    revoke = asyncio.create_task(service.revoke(device.id, owner))
    await asyncio.sleep(0)
    assert not revoke.done()
    allow_save.set()
    await heartbeat
    await revoke
    with pytest.raises(PermissionError, match="revoked"):
        await service.authenticate_device(secret)
    await service.close()


@pytest.mark.asyncio
async def test_graceful_disconnect_is_not_overridden_by_recent_heartbeat(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    connected = await service.heartbeat(
        secret, runtime_state="running", current_task_id=None,
        app_version="1", runtime_version="1", capabilities={},
    )
    connected.status = DeviceStatus.OFFLINE
    connected.runtime_state = "stopped"
    await service._persist_device(connected)
    assert (await service.get_device(device.id, owner)).status == DeviceStatus.OFFLINE


@pytest.mark.asyncio
async def test_device_events_are_deduplicated_and_tenant_scoped(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    event = {
        "event_id": str(uuid4()), "task_id": str(uuid4()), "sequence": 1,
        "event_type": "planning", "payload": {"workflow_state": "planning", "version": 2},
        "created_at": utcnow().isoformat(), "source": "windows_runtime",
    }
    assert await service.ingest_events(secret, [event]) == [event["event_id"]]
    assert await service.ingest_events(secret, [event]) == [event["event_id"]]
    assert len(await service.list_events(device.id, owner)) == 1
    with pytest.raises(PermissionError):
        await service.list_events(device.id, uuid4())


@pytest.mark.asyncio
async def test_event_cursor_tracks_ingestion_not_client_clock_and_deduplicates(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    task_id = uuid4()
    events = [
        {
            "event_id": str(uuid4()), "task_id": str(task_id), "sequence": sequence,
            "event_type": "state", "payload": {"version": sequence},
            "created_at": (utcnow() - timedelta(minutes=sequence)).isoformat(),
            "source": "windows_runtime",
        }
        for sequence in (1, 2, 3)
    ]
    await service.ingest_events(secret, events[:2])
    first_page = await service.list_event_page(device.id, owner, limit=1)
    assert first_page["events"][0]["event_id"] == events[1]["event_id"]
    assert first_page["cursor"] == "2"

    await service.ingest_events(secret, [events[2]])
    await service.ingest_events(secret, [events[2]])
    caught_up = await service.list_event_page(device.id, owner, after=int(first_page["cursor"]))
    assert [item["event_id"] for item in caught_up["events"]] == [events[2]["event_id"]]
    assert caught_up["cursor"] == "3"
    assert len(await service.list_events(device.id, owner)) == 3

    with pytest.raises(ValueError, match="cursor"):
        await service.list_event_page(device.id, owner, after=-1)
    await service.close()
    restored = DeviceControlService(tmp_path / "control.sqlite3")
    await restored.start()
    replay = await restored.list_event_page(device.id, owner, after=2)
    assert [item["event_id"] for item in replay["events"]] == [events[2]["event_id"]]
    assert replay["cursor"] == "3"
    await restored.close()


@pytest.mark.asyncio
async def test_device_task_workspace_is_bound_to_its_persisted_creation_event(tmp_path):
    service, owner, device, secret, _ = await paired_control(tmp_path)
    task_id, workspace_id = uuid4(), uuid4()
    await service.heartbeat(
        secret, runtime_state="running", current_task_id=task_id,
        app_version="1", runtime_version="1", capabilities={},
    )
    event = {
        "event_id": str(uuid4()), "task_id": str(task_id), "sequence": 1,
        "event_type": "task_created",
        "payload": {"workspace_id": str(workspace_id), "workflow_state": "ready"},
        "created_at": utcnow().isoformat(), "source": "windows_runtime",
    }
    await service.ingest_events(secret, [event])
    assert await service.workspace_for_device_task(device.id, owner, task_id) == workspace_id
