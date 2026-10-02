"""Task-linked artifact storage and metadata with device/user authorization."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_MEMORY_REPOSITORY = None


def safe_artifact_name(value: str | None) -> str:
    name = (value or "").replace("\\", "/").split("/")[-1].strip()
    if not name or name in {".", ".."} or not _SAFE_NAME.fullmatch(name):
        raise ValueError("Artifact filename contains unsupported characters.")
    name = name.rstrip(" .")
    if not name or name.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise ValueError("Artifact filename is not safe.")
    return name


def safe_relative_path(value: str) -> str:
    path = (value or "").replace("\\", "/")
    if not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError("Artifact source path must be relative.")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Artifact source path escapes the task workspace.")
    if any(safe_artifact_name(part) != part for part in parts):
        raise ValueError("Artifact source path contains unsupported characters.")
    return "/".join(parts)


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "device_id": str(row["device_id"]),
        "workspace_id": str(row["workspace_id"]),
        "task_id": str(row["task_id"]),
        "name": row["name"],
        "content_type": row["content_type"],
        "size_bytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "expires_at": row["expires_at"].isoformat() if hasattr(row["expires_at"], "isoformat") else str(row["expires_at"]),
    }


class InMemoryTaskArtifactRepository:
    """Small test/development adapter; hosted deployments use PostgreSQL metadata."""

    def __init__(self):
        self.rows: dict[str, dict[str, Any]] = {}

    async def create(self, row: dict[str, Any]) -> None:
        self.rows[str(row["id"])] = row

    async def list_for_task(self, task_id: UUID, user_id: UUID,
                            device_id: UUID | None = None) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        rows = [row for row in self.rows.values()
                if row["task_id"] == task_id and row["user_id"] == user_id
                and (device_id is None or row["device_id"] == device_id)
                and row.get("deleted_at") is None and row["expires_at"] > now]
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    async def get(self, artifact_id: UUID, user_id: UUID, task_id: UUID | None = None,
                  device_id: UUID | None = None):
        row = self.rows.get(str(artifact_id))
        if (not row or row["user_id"] != user_id or row.get("deleted_at") is not None
                or row["expires_at"] <= datetime.now(timezone.utc)
                or (task_id is not None and row["task_id"] != task_id)
                or (device_id is not None and row["device_id"] != device_id)):
            return None
        return row


class PostgresTaskArtifactRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def create(self, row: dict[str, Any]) -> None:
        async with self.sessions() as session:
            await session.execute(text("""
                INSERT INTO rlb_task_artifacts(
                  id,user_id,device_id,workspace_id,task_id,name,content_type,
                  object_path,size_bytes,sha256,created_at,expires_at
                ) VALUES (
                  :id,:user_id,:device_id,:workspace_id,:task_id,:name,:content_type,
                  :object_path,:size_bytes,:sha256,:created_at,:expires_at
                )
            """), {key: row[key] for key in (
                "id", "user_id", "device_id", "workspace_id", "task_id", "name",
                "content_type", "object_path", "size_bytes", "sha256", "created_at", "expires_at",
            )})
            await session.commit()

    async def list_for_task(self, task_id: UUID, user_id: UUID,
                            device_id: UUID | None = None) -> list[dict[str, Any]]:
        async with self.sessions() as session:
            rows = (await session.execute(text("""
                SELECT id,user_id,device_id,workspace_id,task_id,name,content_type,
                       size_bytes,sha256,created_at,expires_at
                FROM rlb_task_artifacts
                WHERE task_id=:task_id AND user_id=:user_id
                  AND (:device_id IS NULL OR device_id=:device_id)
                  AND deleted_at IS NULL AND expires_at>now()
                ORDER BY created_at DESC LIMIT 200
            """), {"task_id": task_id, "user_id": user_id, "device_id": device_id})).mappings().all()
        return [dict(row) for row in rows]

    async def get(self, artifact_id: UUID, user_id: UUID, task_id: UUID | None = None,
                  device_id: UUID | None = None):
        async with self.sessions() as session:
            row = (await session.execute(text("""
                SELECT id,user_id,device_id,workspace_id,task_id,name,content_type,
                       object_path,size_bytes,sha256,created_at,expires_at
                FROM rlb_task_artifacts
                WHERE id=:id AND user_id=:user_id AND deleted_at IS NULL
                  AND expires_at>now() AND (:task_id IS NULL OR task_id=:task_id)
                  AND (:device_id IS NULL OR device_id=:device_id)
            """), {"id": artifact_id, "user_id": user_id, "task_id": task_id,
                   "device_id": device_id})).mappings().first()
        return dict(row) if row else None


class TaskArtifactService:
    def __init__(self, storage, *, sessions=None, repository=None, retention_days: int = 7):
        global _MEMORY_REPOSITORY
        self.storage = storage
        if repository is not None:
            self.repository = repository
        elif sessions is not None:
            self.repository = PostgresTaskArtifactRepository(sessions)
        else:
            if _MEMORY_REPOSITORY is None:
                _MEMORY_REPOSITORY = InMemoryTaskArtifactRepository()
            self.repository = _MEMORY_REPOSITORY
        self.retention_days = retention_days

    async def create(self, *, user_id: UUID, device_id: UUID, workspace_id: UUID,
                     task_id: UUID, name: str, content_type: str, content: bytes) -> dict[str, Any]:
        if not content or len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("Artifact must be between 1 byte and 25 MiB.")
        safe_name = safe_artifact_name(name)
        if len(content_type) > 120 or any(ord(char) < 32 for char in content_type):
            content_type = "application/octet-stream"
        artifact_id = uuid4()
        now = datetime.now(timezone.utc)
        path = f"task-artifacts/{workspace_id}/{task_id}/{artifact_id}/{safe_name}"
        row = {
            "id": artifact_id, "user_id": user_id, "device_id": device_id,
            "workspace_id": workspace_id, "task_id": task_id,
            "name": safe_name, "content_type": content_type or "application/octet-stream",
            "object_path": path, "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "created_at": now, "expires_at": now + timedelta(days=self.retention_days),
            "deleted_at": None,
        }
        await self.storage.write_file(path, content)
        try:
            await self.repository.create(row)
        except Exception:
            await self.storage.delete_file(path)
            raise
        return _metadata(row)

    async def list_for_task(self, task_id: UUID, user_id: UUID,
                            device_id: UUID | None = None) -> list[dict[str, Any]]:
        return [_metadata(row) for row in await self.repository.list_for_task(task_id, user_id, device_id)]

    async def read(self, artifact_id: UUID, user_id: UUID, task_id: UUID | None = None,
                   device_id: UUID | None = None):
        row = await self.repository.get(artifact_id, user_id, task_id, device_id)
        if row is None:
            return None
        content = await self.storage.read_file(row["object_path"])
        if len(content) != int(row["size_bytes"]) or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise IOError("Stored task artifact failed integrity validation.")
        return _metadata(row), content

    async def get_metadata(self, artifact_id: UUID, user_id: UUID, task_id: UUID | None = None,
                           device_id: UUID | None = None):
        row = await self.repository.get(artifact_id, user_id, task_id, device_id)
        return _metadata(row) if row else None
