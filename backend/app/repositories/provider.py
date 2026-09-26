"""Persistence adapters for Phase 10 provider configuration."""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text


class InMemoryProviderRepository:
    def __init__(self):
        self.providers: dict[str, dict[str, Any]] = {}
        self.credentials: dict[tuple[UUID, str], dict[str, Any]] = {}
        self.workers: dict[str, dict[str, Any]] = {}
        self.loadouts: dict[UUID, dict[str, Any]] = {}
        self.active_loadouts: dict[UUID, UUID] = {}

    async def runtime_configuration(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "workers": list(self.workers.values()),
            "credentials": list(self.credentials.values()),
            "loadouts": list(self.loadouts.values()),
            "active_loadouts": [
                {"workspace_id": workspace_id, "active_loadout_id": loadout_id}
                for workspace_id, loadout_id in self.active_loadouts.items()
            ],
        }

    async def save_worker(self, record: dict[str, Any]) -> None:
        self.workers[record["id"]] = dict(record)

    async def ensure_provider(self, record: dict[str, Any]) -> dict[str, Any]:
        existing = self.providers.get(record["id"])
        stored = {**(existing or {}), **record}
        self.providers[record["id"]] = stored
        return stored

    async def list_providers(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.providers.values() if item.get("is_active", True)]

    async def save_credential(self, user_id: UUID, record: dict[str, Any]) -> None:
        self.credentials[(user_id, record["provider_id"])] = {
            **record, "user_id": user_id
        }

    async def list_credentials(self, user_id: UUID) -> list[dict[str, Any]]:
        records = []
        for (owner, _), record in self.credentials.items():
            if owner != user_id:
                continue
            provider = self.providers.get(record["provider_id"], {})
            records.append({
                "id": record.get("id"),
                "provider_id": record["provider_id"],
                "provider_name": provider.get("name") or record.get("provider_name") or record["provider_id"],
                "key_fingerprint": record.get("key_fingerprint"),
                "created_at": record.get("created_at"),
                "updated_at": record.get("updated_at"),
            })
        return records

    async def delete_credential(self, user_id: UUID, provider_id: str) -> bool:
        return self.credentials.pop((user_id, provider_id), None) is not None

    async def delete_worker(self, worker_id: str) -> bool:
        return self.workers.pop(worker_id, None) is not None

    async def upsert_loadout(self, record: dict[str, Any]) -> dict[str, Any]:
        current = self.loadouts.get(record["id"], {})
        stored = {**current, **record}
        self.loadouts[record["id"]] = stored
        return stored

    async def save_loadout(self, record: dict[str, Any]) -> None:
        self.loadouts[record["id"]] = dict(record)

    async def switch_loadout(self, user_id: UUID, workspace_id: UUID, loadout_id: UUID) -> None:
        record = self.loadouts.get(loadout_id)
        if record is None or record.get("user_id") not in (user_id, None):
            raise LookupError("Loadout not found")
        self.active_loadouts[workspace_id] = loadout_id


class PostgresProviderRepository:
    """Uses only the existing providers/credentials/workers/loadouts tables."""

    def __init__(self, sessionmaker):
        self.sessionmaker = sessionmaker

    async def ensure_provider(self, record: dict[str, Any]) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            await session.execute(text("""
                INSERT INTO providers (id, name, base_url, supports_streaming, supports_tool_calling, is_active)
                VALUES (:id, :name, :base_url, :supports_streaming, :supports_tool_calling, TRUE)
                ON CONFLICT (id) DO UPDATE SET
                  name=EXCLUDED.name,
                  base_url=EXCLUDED.base_url,
                  is_active=TRUE
            """), {
                "id": record["id"],
                "name": record["name"],
                "base_url": record["base_url"],
                "supports_streaming": record.get("supports_streaming", True),
                "supports_tool_calling": record.get("supports_tool_calling", True),
            })
            await session.commit()
        return record

    async def save_credential(self, user_id: UUID, record: dict[str, Any]) -> None:
        async with self.sessionmaker() as session:
            await session.execute(text("""
                INSERT INTO credentials (id,user_id,provider_id,encrypted_api_key,key_fingerprint)
                VALUES (:id,:user_id,:provider_id,:encrypted_api_key,:key_fingerprint)
                ON CONFLICT (user_id,provider_id) DO UPDATE SET
                  encrypted_api_key=:encrypted_api_key,key_fingerprint=:key_fingerprint,updated_at=NOW()
            """), {**record, "user_id": user_id})
            await session.commit()

    async def list_providers(self) -> list[dict[str, Any]]:
        async with self.sessionmaker() as session:
            result = await session.execute(text("SELECT * FROM providers WHERE is_active=TRUE ORDER BY id"))
            return [dict(row) for row in result.mappings().all()]

    async def save_worker(self, record: dict[str, Any]) -> None:
        async with self.sessionmaker() as session:
            await session.execute(text("""
                INSERT INTO workers (id,provider_id,model_name,context_window_tokens,max_output_tokens,temperature,rate_limit_rpm,rate_limit_tpm)
                VALUES (:id,:provider_id,:model_name,:context_window_tokens,:max_output_tokens,:temperature,:rate_limit_rpm,:rate_limit_tpm)
                ON CONFLICT (id) DO UPDATE SET provider_id=:provider_id,model_name=:model_name,
                  context_window_tokens=:context_window_tokens,max_output_tokens=:max_output_tokens,
                  temperature=:temperature,rate_limit_rpm=:rate_limit_rpm,rate_limit_tpm=:rate_limit_tpm
            """), record)
            await session.commit()

    async def list_workers(self) -> list[dict[str, Any]]:
        async with self.sessionmaker() as session:
            result = await session.execute(text("SELECT * FROM workers ORDER BY id"))
            return [dict(row) for row in result.mappings().all()]

    async def list_credentials(self, user_id: UUID) -> list[dict[str, Any]]:
        async with self.sessionmaker() as session:
            result = await session.execute(
                text("""
                    SELECT c.id, c.provider_id, COALESCE(p.name, c.provider_id) AS provider_name,
                           c.key_fingerprint, c.created_at, c.updated_at
                    FROM credentials c
                    LEFT JOIN providers p ON p.id = c.provider_id
                    WHERE c.user_id=:user_id
                    ORDER BY c.updated_at DESC
                """),
                {"user_id": user_id},
            )
            return [dict(row) for row in result.mappings().all()]

    async def delete_credential(self, user_id: UUID, provider_id: str) -> bool:
        async with self.sessionmaker() as session:
            result = await session.execute(
                text("DELETE FROM credentials WHERE user_id=:user_id AND provider_id=:provider_id"),
                {"user_id": user_id, "provider_id": provider_id},
            )
            await session.commit()
            return (result.rowcount or 0) > 0

    async def delete_worker(self, worker_id: str) -> bool:
        async with self.sessionmaker() as session:
            result = await session.execute(text("DELETE FROM workers WHERE id=:id"), {"id": worker_id})
            await session.commit()
            return (result.rowcount or 0) > 0

    async def get_credential(self, user_id: UUID, provider_id: str) -> dict[str, Any] | None:
        async with self.sessionmaker() as session:
            result = await session.execute(
                text("SELECT * FROM credentials WHERE user_id=:user_id AND provider_id=:provider_id"),
                {"user_id": user_id, "provider_id": provider_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def save_loadout(self, record: dict[str, Any]) -> None:
        await self.upsert_loadout(record)

    async def upsert_loadout(self, record: dict[str, Any]) -> dict[str, Any]:
        async with self.sessionmaker() as session:
            mappings = record["mappings"]
            if not isinstance(mappings, str):
                mappings = json.dumps({
                    key: (value.model_dump() if hasattr(value, "model_dump") else value)
                    for key, value in (mappings.items() if isinstance(mappings, dict) else [])
                }) if isinstance(mappings, dict) else json.dumps(mappings)
            await session.execute(text("""
                INSERT INTO loadouts (id,user_id,name,description,is_system_preset,mappings)
                VALUES (:id,:user_id,:name,:description,:is_system_preset,:mappings)
                ON CONFLICT (id) DO UPDATE SET
                  name=EXCLUDED.name,
                  description=EXCLUDED.description,
                  mappings=EXCLUDED.mappings,
                  updated_at=NOW()
                WHERE loadouts.user_id=:user_id
            """), {
                "id": record["id"],
                "user_id": record["user_id"],
                "name": record["name"],
                "description": record.get("description"),
                "is_system_preset": record.get("is_system_preset", False),
                "mappings": mappings,
            })
            await session.commit()
        return record

    async def get_loadout(self, user_id: UUID, loadout_id: UUID) -> dict[str, Any] | None:
        async with self.sessionmaker() as session:
            result = await session.execute(
                text("SELECT * FROM loadouts WHERE id=:id AND (user_id=:user_id OR is_system_preset=TRUE)"),
                {"id": loadout_id, "user_id": user_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            record = dict(row)
            if isinstance(record.get("mappings"), str):
                record["mappings"] = json.loads(record["mappings"])
            return record

    async def list_loadouts(self, user_id: UUID) -> list[dict[str, Any]]:
        async with self.sessionmaker() as session:
            result = await session.execute(
                text("SELECT * FROM loadouts WHERE user_id=:user_id OR is_system_preset=TRUE"),
                {"user_id": user_id},
            )
            records = []
            for row in result.mappings().all():
                record = dict(row)
                if isinstance(record.get("mappings"), str):
                    record["mappings"] = json.loads(record["mappings"])
                records.append(record)
            return records

    async def switch_loadout(self, user_id: UUID, workspace_id: UUID, loadout_id: UUID) -> None:
        async with self.sessionmaker() as session:
            workspace = await session.execute(
                text("SELECT 1 FROM workspaces WHERE id=:workspace_id AND user_id=:user_id"),
                {"workspace_id": workspace_id, "user_id": user_id},
            )
            if workspace.first() is None:
                raise PermissionError("Workspace is not accessible")
            valid = await session.execute(
                text("SELECT 1 FROM loadouts WHERE id=:id AND (user_id=:user_id OR is_system_preset=TRUE)"),
                {"id": loadout_id, "user_id": user_id},
            )
            if valid.first() is None:
                raise LookupError("Loadout not found")
            await session.execute(text("""
                INSERT INTO workspace_settings (workspace_id,active_loadout_id)
                VALUES (:workspace_id,:loadout_id)
                ON CONFLICT (workspace_id) DO UPDATE SET active_loadout_id=:loadout_id,updated_at=NOW()
            """), {"workspace_id": workspace_id, "loadout_id": loadout_id})
            await session.commit()

    async def active_loadout(self, user_id: UUID, workspace_id: UUID) -> dict[str, Any] | None:
        async with self.sessionmaker() as session:
            result = await session.execute(text("""
                SELECT l.* FROM workspace_settings s
                JOIN loadouts l ON l.id=s.active_loadout_id
                JOIN workspaces w ON w.id=s.workspace_id
                WHERE s.workspace_id=:workspace_id AND w.user_id=:user_id
            """), {"workspace_id": workspace_id, "user_id": user_id})
            row = result.mappings().first()
            return dict(row) if row else None

    async def runtime_configuration(self) -> dict[str, list[dict[str, Any]]]:
        async with self.sessionmaker() as session:
            workers = await session.execute(text("SELECT * FROM workers"))
            credentials = await session.execute(text("SELECT * FROM credentials"))
            loadouts = await session.execute(text("SELECT * FROM loadouts"))
            active = await session.execute(text(
                "SELECT workspace_id,active_loadout_id FROM workspace_settings "
                "WHERE active_loadout_id IS NOT NULL"
            ))
            overrides = await session.execute(text(
                "SELECT id, worker_overrides FROM tasks WHERE worker_overrides IS NOT NULL"
            ))
            return {
                "workers": [dict(row) for row in workers.mappings().all()],
                "credentials": [dict(row) for row in credentials.mappings().all()],
                "loadouts": [dict(row) for row in loadouts.mappings().all()],
                "active_loadouts": [dict(row) for row in active.mappings().all()],
                "task_overrides": [dict(row) for row in overrides.mappings().all()],
            }
