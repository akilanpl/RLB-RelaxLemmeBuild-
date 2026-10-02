"""Device pairing, presence, and durable remote command control plane."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.app.storage.sqlite import SQLiteStateStore


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    RECONNECTING = "RECONNECTING"
    REVOKED = "REVOKED"


class Device(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    platform: str
    architecture: str
    app_version: str
    runtime_version: str
    status: DeviceStatus = DeviceStatus.OFFLINE
    capabilities: dict[str, Any] = Field(default_factory=dict)
    current_task_id: UUID | None = None
    runtime_state: str = "stopped"
    last_seen_at: datetime | None = None
    paired_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CommandType(str, Enum):
    START_TASK = "START_TASK"
    PROMPT = "PROMPT"
    PAUSE_TASK = "PAUSE_TASK"
    RESUME_TASK = "RESUME_TASK"
    STOP_TASK = "STOP_TASK"
    DOWNLOAD_ARTIFACT_TO_PC = "DOWNLOAD_ARTIFACT_TO_PC"
    REQUEST_ARTIFACT_UPLOAD = "REQUEST_ARTIFACT_UPLOAD"


class CommandStatus(str, Enum):
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class RemoteCommand(BaseModel):
    id: UUID
    user_id: UUID
    device_id: UUID
    task_id: UUID | None = None
    command_type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    status: CommandStatus = CommandStatus.QUEUED
    created_at: datetime
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None
    claim_until: datetime | None = None
    claim_owner: UUID | None = None


class DeviceControlService:
    """Persistent control-plane records; SQLite for local mode, PostgreSQL hosted."""

    PAIRING_LIFETIME = timedelta(minutes=5)
    DEFAULT_COMMAND_LIFETIME = timedelta(hours=24)
    MAX_COMMAND_TTL = timedelta(days=7)
    ONLINE_WINDOW = timedelta(seconds=60)
    RECONNECT_WINDOW = timedelta(seconds=180)
    COMMAND_CLAIM_LIFETIME = timedelta(minutes=5)

    def __init__(self, path: str | Path | None = None, sessions=None):
        if (path is None) == (sessions is None):
            raise ValueError("Specify exactly one local database path or PostgreSQL session factory.")
        self._store = SQLiteStateStore(path) if path is not None else None
        self._sessions = sessions
        self._lock = __import__("asyncio").Lock()
        self._state: dict[str, Any] = {
            "pairings": {}, "devices": {}, "device_secrets": {},
            "commands": {}, "idempotency": {}, "events": {}, "event_cursors": {},
        }

    async def start(self) -> None:
        if self._store:
            self._state = await self._store.load("device_control", self._state)
            self._state.setdefault("event_cursors", {})
        else:
            async with self._sessions() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT id FROM rlb_devices LIMIT 0"))
                await session.execute(text("SELECT token_hash FROM rlb_device_pairings LIMIT 0"))
                await session.execute(text("SELECT id FROM rlb_remote_commands LIMIT 0"))
                await session.execute(text("SELECT event_id FROM rlb_device_events LIMIT 0"))

    async def close(self) -> None:
        if self._store:
            await self._store.close()

    async def _save(self) -> None:
        if self._store:
            await self._store.save("device_control", self._state)

    @staticmethod
    def _digest(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    async def create_pairing(self, user_id: UUID) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        pairing = {"user_id": user_id, "expires_at": utcnow() + self.PAIRING_LIFETIME, "used_at": None}
        if self._store:
            async with self._lock:
                self._state["pairings"][self._digest(token)] = pairing
                await self._save()
        else:
            from sqlalchemy import text
            async with self._sessions() as session:
                await session.execute(text("""
                    INSERT INTO rlb_device_pairings(token_hash,user_id,expires_at)
                    VALUES (:hash,:user_id,:expires_at)
                """), {"hash": self._digest(token), "user_id": user_id, "expires_at": pairing["expires_at"]})
                await session.commit()
        return {"pairing_token": token, "expires_at": pairing["expires_at"]}

    async def pair(self, token: str, *, name: str, platform: str, architecture: str,
                   app_version: str, runtime_version: str, capabilities: dict[str, Any]) -> tuple[Device, str]:
        now = utcnow()
        device_secret = secrets.token_urlsafe(48)
        device = Device(
            id=uuid4(), user_id=UUID(int=0), name=name, platform=platform,
            architecture=architecture, app_version=app_version, runtime_version=runtime_version,
            status=DeviceStatus.ONLINE, capabilities=capabilities, last_seen_at=now,
            paired_at=now, created_at=now, updated_at=now,
        )
        token_hash = self._digest(device_secret)
        pairing_hash = self._digest(token)
        if self._store:
            async with self._lock:
                pair = self._state["pairings"].get(pairing_hash)
                if not pair or pair["used_at"] or pair["expires_at"] <= now:
                    raise ValueError("Pairing token is invalid, expired, or already used.")
                device.user_id = pair["user_id"]
                pair["used_at"] = now
                self._state["devices"][str(device.id)] = device.model_dump(mode="json")
                self._state["device_secrets"][str(device.id)] = token_hash
                await self._save()
        else:
            from sqlalchemy import text
            async with self._sessions() as session, session.begin():
                pair = (await session.execute(text("""
                    SELECT user_id, expires_at, used_at FROM rlb_device_pairings
                    WHERE token_hash=:hash FOR UPDATE
                """), {"hash": pairing_hash})).mappings().first()
                if not pair or pair["used_at"] or pair["expires_at"] <= now:
                    raise ValueError("Pairing token is invalid, expired, or already used.")
                device.user_id = pair["user_id"]
                await session.execute(text("""
                    UPDATE rlb_device_pairings SET used_at=:now WHERE token_hash=:hash
                """), {"now": now, "hash": pairing_hash})
                await session.execute(text("""
                    INSERT INTO rlb_devices(id,user_id,token_hash,payload)
                    VALUES (:id,:user_id,:token_hash,CAST(:payload AS jsonb))
                """), {"id": device.id, "user_id": device.user_id, "token_hash": token_hash,
                       "payload": device.model_dump_json()})
        return device, device_secret

    async def _device_for_user(self, device_id: UUID, user_id: UUID) -> Device:
        if self._store:
            raw = self._state["devices"].get(str(device_id))
            if not raw:
                raise LookupError("Device not found.")
            device = Device.model_validate(raw)
            if device.user_id != user_id:
                raise PermissionError("Device access denied.")
            return device
        from sqlalchemy import text
        async with self._sessions() as session:
            row = (await session.execute(text("""
                SELECT payload FROM rlb_devices WHERE id=:id AND user_id=:user_id
            """), {"id": device_id, "user_id": user_id})).scalar_one_or_none()
        if row is None:
            raise LookupError("Device not found.")
        return Device.model_validate(row)

    async def authorize_task_for_device(self, device_id: UUID, user_id: UUID, task_id: UUID) -> Device:
        """Require a same-owner task observed on this paired device."""
        device = await self._device_for_user(device_id, user_id)
        if device.current_task_id == task_id:
            return device
        if self._store:
            associated = any(
                event["device_id"] == str(device_id) and event["user_id"] == str(user_id)
                and str(event["task_id"]) == str(task_id)
                for event in self._state["events"].values()
            )
        else:
            from sqlalchemy import text
            async with self._sessions() as session:
                associated = (await session.execute(text("""
                    SELECT EXISTS(
                      SELECT 1 FROM rlb_device_events
                      WHERE device_id=:device AND user_id=:user_id AND task_id=:task_id
                    )
                """), {"device": device_id, "user_id": user_id, "task_id": task_id})).scalar()
        if not associated:
            raise LookupError("Task is not associated with this device.")
        return device

    async def workspace_for_device_task(self, device_id: UUID, user_id: UUID,
                                        task_id: UUID) -> UUID:
        await self.authorize_task_for_device(device_id, user_id, task_id)
        if self._store:
            workspace_id = next((
                event.get("payload", {}).get("workspace_id")
                for event in self._state["events"].values()
                if event["device_id"] == str(device_id)
                and event["user_id"] == str(user_id)
                and str(event["task_id"]) == str(task_id)
                and event["event_type"] == "task_created"
            ), None)
        else:
            from sqlalchemy import text
            async with self._sessions() as session:
                workspace_id = (await session.execute(text("""
                    SELECT payload->>'workspace_id' FROM rlb_device_events
                    WHERE device_id=:device AND user_id=:user_id AND task_id=:task_id
                      AND event_type='task_created' AND payload ? 'workspace_id'
                    ORDER BY cursor LIMIT 1
                """), {"device": device_id, "user_id": user_id, "task_id": task_id})).scalar_one_or_none()
                if workspace_id is None:
                    workspace_id = (await session.execute(text("""
                        SELECT workspace_id FROM tasks WHERE id=:task_id AND user_id=:user_id
                    """), {"task_id": task_id, "user_id": user_id})).scalar_one_or_none()
        if workspace_id is None:
            raise LookupError("Task workspace association is not available.")
        return UUID(str(workspace_id))

    async def list_devices(self, user_id: UUID) -> list[Device]:
        if self._store:
            values = [Device.model_validate(item) for item in self._state["devices"].values()]
            return sorted((item for item in values if item.user_id == user_id), key=lambda x: x.created_at, reverse=True)
        from sqlalchemy import text
        async with self._sessions() as session:
            rows = (await session.execute(text("SELECT payload FROM rlb_devices WHERE user_id=:user_id ORDER BY created_at DESC"),
                                          {"user_id": user_id})).scalars().all()
        return [Device.model_validate(row) for row in rows]

    async def get_device(self, device_id: UUID, user_id: UUID) -> Device:
        device = await self._device_for_user(device_id, user_id)
        return self._freshness(device)

    def _freshness(self, device: Device) -> Device:
        if device.status != DeviceStatus.REVOKED and not (
            device.status == DeviceStatus.OFFLINE and device.runtime_state == "stopped"
        ):
            age = utcnow() - device.last_seen_at if device.last_seen_at else None
            device.status = (
                DeviceStatus.ONLINE if age is not None and age < self.ONLINE_WINDOW else
                DeviceStatus.RECONNECTING if age is not None and age < self.RECONNECT_WINDOW else
                DeviceStatus.OFFLINE
            )
        return device

    async def revoke(self, device_id: UUID, user_id: UUID) -> Device:
        now = utcnow()
        if self._store:
            async with self._lock:
                raw = self._state["devices"].get(str(device_id))
                if not raw:
                    raise LookupError("Device not found.")
                device = Device.model_validate(raw)
                if device.user_id != user_id:
                    raise PermissionError("Device access denied.")
                device.status = DeviceStatus.REVOKED
                device.revoked_at = device.updated_at = now
                self._state["devices"][str(device.id)] = device.model_dump(mode="json")
                for key, raw_command in self._state["commands"].items():
                    command = RemoteCommand.model_validate(raw_command)
                    if command.device_id == device_id and command.status in {
                        CommandStatus.QUEUED, CommandStatus.DELIVERED,
                        CommandStatus.ACKNOWLEDGED, CommandStatus.EXECUTING,
                    }:
                        command.status = CommandStatus.FAILED
                        command.error = "Device revoked."
                        command.completed_at = now
                        self._state["commands"][key] = command.model_dump(mode="json")
                await self._save()
                return device

        from sqlalchemy import text
        async with self._sessions() as session, session.begin():
            row = (await session.execute(text("""
                SELECT payload FROM rlb_devices WHERE id=:id AND user_id=:user_id FOR UPDATE
            """), {"id": device_id, "user_id": user_id})).scalar_one_or_none()
            if row is None:
                raise LookupError("Device not found.")
            device = Device.model_validate(row)
            device.status = DeviceStatus.REVOKED
            device.revoked_at = device.updated_at = now
            await session.execute(text("""
                UPDATE rlb_devices SET payload=CAST(:payload AS jsonb) WHERE id=:id
            """), {"payload": device.model_dump_json(), "id": device_id})
            rows = (await session.execute(text("""
                SELECT id,payload FROM rlb_remote_commands
                WHERE device_id=:device AND status IN ('QUEUED','DELIVERED','ACKNOWLEDGED','EXECUTING')
                FOR UPDATE
            """), {"device": device_id})).mappings().all()
            for row in rows:
                command = RemoteCommand.model_validate(row["payload"])
                command.status = CommandStatus.FAILED
                command.error = "Device revoked."
                command.completed_at = now
                await session.execute(text("""
                    UPDATE rlb_remote_commands SET status='FAILED',payload=CAST(:payload AS jsonb)
                    WHERE id=:id
                """), {"payload": command.model_dump_json(), "id": command.id})
        return device

    async def _persist_device(self, device: Device) -> None:
        if self._store:
            async with self._lock:
                self._state["devices"][str(device.id)] = device.model_dump(mode="json")
                await self._save()
        else:
            from sqlalchemy import text
            async with self._sessions() as session:
                await session.execute(text("""
                    UPDATE rlb_devices SET payload=CAST(:payload AS jsonb) WHERE id=:id AND user_id=:user_id
                """), {"payload": device.model_dump_json(), "id": device.id, "user_id": device.user_id})
                await session.commit()

    async def authenticate_device(self, secret: str) -> Device:
        token_hash = self._digest(secret)
        if self._store:
            async with self._lock:
                device_id = next((key for key, value in self._state["device_secrets"].items() if secrets.compare_digest(value, token_hash)), None)
                if not device_id:
                    raise PermissionError("Invalid device credential.")
                device = Device.model_validate(self._state["devices"][device_id])
                if device.status == DeviceStatus.REVOKED or device.revoked_at:
                    raise PermissionError("Device has been revoked.")
                device.status = DeviceStatus.ONLINE
                device.last_seen_at = device.updated_at = utcnow()
                self._state["devices"][device_id] = device.model_dump(mode="json")
                await self._save()
                return device
        from sqlalchemy import text
        async with self._sessions() as session, session.begin():
            row = (await session.execute(text("SELECT id,payload FROM rlb_devices WHERE token_hash=:hash FOR UPDATE"),
                                         {"hash": token_hash})).mappings().first()
            if not row:
                raise PermissionError("Invalid device credential.")
            device = Device.model_validate(row["payload"])
            if device.revoked_at:
                raise PermissionError("Device has been revoked.")
            device.status = DeviceStatus.ONLINE
            device.last_seen_at = device.updated_at = utcnow()
            await session.execute(text("UPDATE rlb_devices SET payload=CAST(:payload AS jsonb) WHERE id=:id"),
                                  {"payload": device.model_dump_json(), "id": device.id})
        return device

    async def heartbeat(self, secret: str, *, runtime_state: str, current_task_id: UUID | None,
                        app_version: str, runtime_version: str, capabilities: dict[str, Any]) -> Device:
        token_hash = self._digest(secret)
        now = utcnow()
        if self._store:
            async with self._lock:
                device_id = next((
                    key for key, value in self._state["device_secrets"].items()
                    if secrets.compare_digest(value, token_hash)
                ), None)
                if not device_id:
                    raise PermissionError("Invalid device credential.")
                device = Device.model_validate(self._state["devices"][device_id])
                if device.status == DeviceStatus.REVOKED or device.revoked_at:
                    raise PermissionError("Device has been revoked.")
                device.status = DeviceStatus.ONLINE
                device.runtime_state = runtime_state
                device.current_task_id = current_task_id
                device.app_version = app_version
                device.runtime_version = runtime_version
                device.capabilities = capabilities
                device.last_seen_at = device.updated_at = now
                self._state["devices"][device_id] = device.model_dump(mode="json")
                await self._save()
                return device

        from sqlalchemy import text
        async with self._sessions() as session, session.begin():
            row = (await session.execute(text("""
                SELECT id,payload FROM rlb_devices WHERE token_hash=:hash FOR UPDATE
            """), {"hash": token_hash})).mappings().first()
            if not row:
                raise PermissionError("Invalid device credential.")
            device = Device.model_validate(row["payload"])
            if device.status == DeviceStatus.REVOKED or device.revoked_at:
                raise PermissionError("Device has been revoked.")
            device.status = DeviceStatus.ONLINE
            device.runtime_state = runtime_state
            device.current_task_id = current_task_id
            device.app_version = app_version
            device.runtime_version = runtime_version
            device.capabilities = capabilities
            device.last_seen_at = device.updated_at = now
            await session.execute(text("""
                UPDATE rlb_devices SET payload=CAST(:payload AS jsonb) WHERE id=:id
            """), {"payload": device.model_dump_json(), "id": device.id})
        return device

    async def enqueue_command(self, device_id: UUID, user_id: UUID, command_type: CommandType,
                              payload: dict[str, Any], idempotency_key: str,
                              task_id: UUID | None = None, ttl_seconds: int | None = None) -> RemoteCommand:
        device = await self._device_for_user(device_id, user_id)
        if device.revoked_at:
            raise PermissionError("Revoked devices cannot receive commands.")
        if command_type in {CommandType.DOWNLOAD_ARTIFACT_TO_PC, CommandType.REQUEST_ARTIFACT_UPLOAD}:
            if task_id is None:
                raise ValueError("Artifact commands require a task associated with this device.")
            device = await self.authorize_task_for_device(device_id, user_id, task_id)
        elif task_id:
            from backend.app.services.runtime import get_runtime
            await get_runtime().workflow.get_task(task_id, user_id)
        ttl = min(max(ttl_seconds or int(self.DEFAULT_COMMAND_LIFETIME.total_seconds()), 1),
                  int(self.MAX_COMMAND_TTL.total_seconds()))
        now = utcnow()
        command = RemoteCommand(id=uuid4(), user_id=user_id, device_id=device_id, task_id=task_id,
                                command_type=command_type, payload=payload, idempotency_key=idempotency_key,
                                created_at=now, expires_at=now + timedelta(seconds=ttl))
        if self._store:
            async with self._lock:
                key = f"{device_id}:{idempotency_key}"
                existing_id = self._state["idempotency"].get(key)
                if existing_id:
                    return RemoteCommand.model_validate(self._state["commands"][existing_id])
                self._state["idempotency"][key] = str(command.id)
                self._state["commands"][str(command.id)] = command.model_dump(mode="json")
                await self._save()
        else:
            from sqlalchemy import text
            async with self._sessions() as session:
                row = (await session.execute(text("""
                    INSERT INTO rlb_remote_commands(id,user_id,device_id,idempotency_key,status,payload)
                    VALUES (:id,:user_id,:device_id,:key,:status,CAST(:payload AS jsonb))
                    ON CONFLICT(device_id,idempotency_key) DO UPDATE SET idempotency_key=EXCLUDED.idempotency_key
                    RETURNING payload
                """), {"id": command.id, "user_id": user_id, "device_id": device_id, "key": idempotency_key,
                       "status": command.status.value, "payload": command.model_dump_json()})).scalar_one()
                await session.commit()
                return RemoteCommand.model_validate(row)
        return command

    async def list_commands(self, device_id: UUID, user_id: UUID) -> list[RemoteCommand]:
        await self._device_for_user(device_id, user_id)
        if self._store:
            values = [RemoteCommand.model_validate(raw) for raw in self._state["commands"].values()]
            return sorted((x for x in values if x.device_id == device_id and x.user_id == user_id), key=lambda x: x.created_at, reverse=True)
        from sqlalchemy import text
        async with self._sessions() as session:
            rows = (await session.execute(text("""
                SELECT payload FROM rlb_remote_commands WHERE device_id=:device AND user_id=:user_id ORDER BY created_at DESC
            """), {"device": device_id, "user_id": user_id})).scalars().all()
        return [RemoteCommand.model_validate(row) for row in rows]

    async def claim_commands(self, secret: str, claim_owner: UUID | None = None) -> list[RemoteCommand]:
        device = await self.authenticate_device(secret)
        claim_owner = claim_owner or UUID(int=0)
        now = utcnow()
        if self._store:
            async with self._lock:
                results = []
                for key, raw in self._state["commands"].items():
                    command = RemoteCommand.model_validate(raw)
                    if command.device_id != device.id or command.status not in {
                        CommandStatus.QUEUED, CommandStatus.DELIVERED,
                        CommandStatus.ACKNOWLEDGED, CommandStatus.EXECUTING,
                    }:
                        continue
                    if (command.claim_until and command.claim_until > now
                            and command.claim_owner != claim_owner):
                        continue
                    if command.expires_at <= now:
                        command.status = CommandStatus.EXPIRED
                        command.completed_at = now
                    else:
                        if command.status in {CommandStatus.QUEUED, CommandStatus.DELIVERED}:
                            command.status = CommandStatus.DELIVERED
                            command.delivered_at = command.delivered_at or now
                        command.claim_until = now + self.COMMAND_CLAIM_LIFETIME
                        command.claim_owner = claim_owner
                        results.append(command)
                    self._state["commands"][key] = command.model_dump(mode="json")
                await self._save()
                return results
        from sqlalchemy import text
        async with self._sessions() as session, session.begin():
            rows = (await session.execute(text("""
                SELECT id,payload FROM rlb_remote_commands WHERE device_id=:device
                AND status IN ('QUEUED','DELIVERED','ACKNOWLEDGED','EXECUTING')
                AND (payload->>'claim_owner'=:claim_owner
                     OR (payload->>'claim_until') IS NULL
                     OR (payload->>'claim_until')::timestamptz<=:now)
                ORDER BY created_at FOR UPDATE SKIP LOCKED
            """), {"device": device.id, "now": now, "claim_owner": str(claim_owner)})).mappings().all()
            commands = []
            for row in rows:
                command = RemoteCommand.model_validate(row["payload"])
                if command.expires_at <= now:
                    command.status = CommandStatus.EXPIRED
                    command.completed_at = now
                else:
                    if command.status in {CommandStatus.QUEUED, CommandStatus.DELIVERED}:
                        command.status = CommandStatus.DELIVERED
                        command.delivered_at = command.delivered_at or now
                    command.claim_until = now + self.COMMAND_CLAIM_LIFETIME
                    command.claim_owner = claim_owner
                    commands.append(command)
                await session.execute(text("""
                    UPDATE rlb_remote_commands SET status=:status,payload=CAST(:payload AS jsonb) WHERE id=:id
                """), {"status": command.status.value, "payload": command.model_dump_json(), "id": command.id})
            return commands

    async def ingest_events(self, secret: str, events: list[dict[str, Any]]) -> list[str]:
        if len(events) > 200:
            raise ValueError("A synchronization batch may contain at most 200 events.")
        device = await self.authenticate_device(secret)
        accepted: list[str] = []
        normalized = []
        for event in events:
            event_id = UUID(str(event["event_id"]))
            task_id = UUID(str(event["task_id"]))
            sequence = int(event["sequence"])
            if sequence < 1:
                raise ValueError("Event sequence must be positive.")
            payload = event.get("payload") or {}
            if not isinstance(payload, dict) or len(json.dumps(payload, default=str).encode("utf-8")) > 16384:
                raise ValueError("Event payload must be an object no larger than 16 KiB.")
            created_at = event.get("created_at") or utcnow()
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            normalized.append({
                "event_id": event_id, "task_id": task_id, "sequence": sequence,
                "event_type": str(event["event_type"])[:80],
                "payload": payload,
                "created_at": created_at,
                "source": str(event.get("source") or "windows_runtime")[:80],
            })
        if self._store:
            async with self._lock:
                for event in normalized:
                    key = str(event["event_id"])
                    existing = self._state["events"].get(key)
                    if existing and (existing["device_id"] != str(device.id)
                                     or str(existing["task_id"]) != str(event["task_id"])
                                     or existing["sequence"] != event["sequence"]
                                     or existing["event_type"] != event["event_type"]
                                     or existing["payload"] != event["payload"]):
                        raise ValueError("Event identifier was reused with different content.")
                    sequence_exists = any(
                        stored["device_id"] == str(device.id)
                        and stored["task_id"] == str(event["task_id"])
                        and stored["sequence"] == event["sequence"]
                        and stored["event_id"] != key
                        for stored in self._state["events"].values()
                    )
                    if sequence_exists:
                        raise ValueError("Event sequence already exists for this task.")
                    if key not in self._state["events"]:
                        self._state["events"][key] = {
                            **event, "event_id": key, "task_id": str(event["task_id"]),
                            "device_id": str(device.id), "user_id": str(device.user_id),
                            "cursor": self._next_event_cursor(device.id),
                            "created_at": event["created_at"].isoformat(),
                        }
                    accepted.append(key)
                await self._save()
            return accepted

        from sqlalchemy import text
        async with self._sessions() as session, session.begin():
            for event in normalized:
                task_owner = (await session.execute(text("""
                    SELECT user_id FROM tasks WHERE id=:task_id
                """), {"task_id": event["task_id"]})).scalar_one_or_none()
                if task_owner is not None and UUID(str(task_owner)) != device.user_id:
                    raise PermissionError("Event task belongs to another user.")
                inserted = (await session.execute(text("""
                    INSERT INTO rlb_device_events(
                      device_id,user_id,event_id,task_id,sequence,event_type,payload,created_at,source
                    ) VALUES (
                      :device,:user_id,:event_id,:task_id,:sequence,:event_type,
                      CAST(:payload AS jsonb),:created_at,:source
                    ) ON CONFLICT DO NOTHING RETURNING event_id
                """), {
                    **event, "device": device.id, "user_id": device.user_id,
                    "payload": json.dumps(event["payload"]),
                })).scalar_one_or_none()
                if inserted is None:
                    existing = (await session.execute(text("""
                        SELECT event_id,task_id,sequence,event_type,payload
                        FROM rlb_device_events WHERE device_id=:device
                        AND (event_id=:event_id OR (task_id=:task_id AND sequence=:sequence))
                    """), {
                        "device": device.id, "event_id": event["event_id"],
                        "task_id": event["task_id"], "sequence": event["sequence"],
                    })).mappings().all()
                    same = next((row for row in existing if row["event_id"] == event["event_id"]), None)
                    if (same is None or same["task_id"] != event["task_id"]
                            or same["sequence"] != event["sequence"]
                            or same["event_type"] != event["event_type"]
                            or same["payload"] != event["payload"]):
                        raise ValueError("Event identifier or sequence was reused with different content.")
                accepted.append(str(event["event_id"]))
        return accepted

    def _next_event_cursor(self, device_id: UUID) -> int:
        cursors = self._state.setdefault("event_cursors", {})
        device_key = str(device_id)
        cursor = int(cursors.get(device_key, 0)) + 1
        cursors[device_key] = cursor
        return cursor

    async def list_events(self, device_id: UUID, user_id: UUID, limit: int = 200) -> list[dict[str, Any]]:
        await self._device_for_user(device_id, user_id)
        limit = min(max(limit, 1), 500)
        if self._store:
            events = [event for event in self._state["events"].values()
                      if event["device_id"] == str(device_id) and event["user_id"] == str(user_id)]
            return sorted(events, key=lambda item: item["created_at"], reverse=True)[:limit]
        from sqlalchemy import text
        async with self._sessions() as session:
            rows = (await session.execute(text("""
                SELECT event_id,task_id,sequence,event_type,payload,created_at,source
                FROM rlb_device_events WHERE device_id=:device AND user_id=:user_id
                ORDER BY created_at DESC LIMIT :limit
            """), {"device": device_id, "user_id": user_id, "limit": limit})).mappings().all()
        return [dict(row) for row in rows]

    async def list_event_page(self, device_id: UUID, user_id: UUID, limit: int = 200,
                              after: int | None = None) -> dict[str, Any]:
        await self._device_for_user(device_id, user_id)
        limit = min(max(limit, 1), 500)
        if after is not None and after < 0:
            raise ValueError("Event cursor must be non-negative.")
        if self._store:
            events = [dict(event) for event in self._state["events"].values()
                      if event["device_id"] == str(device_id) and event["user_id"] == str(user_id)]
            if after is not None:
                events = [event for event in events if int(event.get("cursor", 0)) > after]
                events.sort(key=lambda event: int(event.get("cursor", 0)))
            else:
                events.sort(key=lambda event: int(event.get("cursor", 0)), reverse=True)
                events = events[:limit]
                events.reverse()
            page = events[:limit]
        else:
            from sqlalchemy import text
            async with self._sessions() as session:
                if after is not None:
                    rows = (await session.execute(text("""
                        SELECT cursor,event_id,task_id,sequence,event_type,payload,created_at,source
                        FROM rlb_device_events
                        WHERE device_id=:device AND user_id=:user_id AND cursor>:after
                        ORDER BY cursor LIMIT :limit
                    """), {"device": device_id, "user_id": user_id,
                           "after": after, "limit": limit})).mappings().all()
                else:
                    rows = (await session.execute(text("""
                        SELECT cursor,event_id,task_id,sequence,event_type,payload,created_at,source
                        FROM (
                          SELECT cursor,event_id,task_id,sequence,event_type,payload,created_at,source
                          FROM rlb_device_events
                          WHERE device_id=:device AND user_id=:user_id
                          ORDER BY cursor DESC LIMIT :limit
                        ) recent ORDER BY cursor
                    """), {"device": device_id, "user_id": user_id, "limit": limit})).mappings().all()
                page = [dict(row) for row in rows]
        return {
            "events": page,
            "cursor": str(page[-1]["cursor"]) if page else str(after) if after is not None else None,
        }

    async def update_command(self, secret: str, command_id: UUID, status: CommandStatus,
                             result: dict[str, Any] | None = None, error: str | None = None) -> RemoteCommand:
        device = await self.authenticate_device(secret)
        if self._store:
            async with self._lock:
                raw = self._state["commands"].get(str(command_id))
                if not raw:
                    raise LookupError("Command not found.")
                command = RemoteCommand.model_validate(raw)
                if command.device_id != device.id:
                    raise PermissionError("Command belongs to another device.")
                if command.status in {CommandStatus.SUCCEEDED, CommandStatus.FAILED, CommandStatus.EXPIRED}:
                    return command
                if command.status == status:
                    return command
                if command.expires_at <= utcnow():
                    command.status = CommandStatus.EXPIRED
                    command.completed_at = utcnow()
                    self._state["commands"][str(command_id)] = command.model_dump(mode="json")
                    await self._save()
                    return command
                allowed = {
                    CommandStatus.DELIVERED: {CommandStatus.ACKNOWLEDGED, CommandStatus.FAILED},
                    CommandStatus.ACKNOWLEDGED: {CommandStatus.EXECUTING, CommandStatus.FAILED},
                    CommandStatus.EXECUTING: {CommandStatus.SUCCEEDED, CommandStatus.FAILED},
                }
                if status not in allowed.get(command.status, set()):
                    raise ValueError(f"Invalid command transition: {command.status.value} -> {status.value}.")
                command.status = status
                command.result = result
                command.error = error
                now = utcnow()
                if status == CommandStatus.ACKNOWLEDGED:
                    command.acknowledged_at = now
                if status == CommandStatus.EXECUTING:
                    command.started_at = now
                if status in {CommandStatus.SUCCEEDED, CommandStatus.FAILED, CommandStatus.EXPIRED}:
                    command.completed_at = now
                self._state["commands"][str(command_id)] = command.model_dump(mode="json")
                await self._save()
                return command
        from sqlalchemy import text
        async with self._sessions() as session, session.begin():
            row = (await session.execute(text("""
                SELECT payload FROM rlb_remote_commands WHERE id=:id AND device_id=:device FOR UPDATE
            """), {"id": command_id, "device": device.id})).scalar_one_or_none()
            if row is None:
                raise LookupError("Command not found.")
            command = RemoteCommand.model_validate(row)
            if command.status in {CommandStatus.SUCCEEDED, CommandStatus.FAILED, CommandStatus.EXPIRED}:
                return command
            if command.status == status:
                return command
            if command.expires_at <= utcnow():
                command.status = CommandStatus.EXPIRED
                command.completed_at = utcnow()
                await session.execute(text("""
                    UPDATE rlb_remote_commands SET status=:status,payload=CAST(:payload AS jsonb) WHERE id=:id
                """), {"status": command.status.value, "payload": command.model_dump_json(), "id": command_id})
                return command
            allowed = {
                CommandStatus.DELIVERED: {CommandStatus.ACKNOWLEDGED, CommandStatus.FAILED},
                CommandStatus.ACKNOWLEDGED: {CommandStatus.EXECUTING, CommandStatus.FAILED},
                CommandStatus.EXECUTING: {CommandStatus.SUCCEEDED, CommandStatus.FAILED},
            }
            if status not in allowed.get(command.status, set()):
                raise ValueError(f"Invalid command transition: {command.status.value} -> {status.value}.")
            command.status, command.result, command.error = status, result, error
            now = utcnow()
            if status == CommandStatus.ACKNOWLEDGED: command.acknowledged_at = now
            if status == CommandStatus.EXECUTING: command.started_at = now
            if status in {CommandStatus.SUCCEEDED, CommandStatus.FAILED, CommandStatus.EXPIRED}: command.completed_at = now
            await session.execute(text("""
                UPDATE rlb_remote_commands SET status=:status,payload=CAST(:payload AS jsonb) WHERE id=:id
            """), {"status": status.value, "payload": command.model_dump_json(), "id": command_id})
            return command
