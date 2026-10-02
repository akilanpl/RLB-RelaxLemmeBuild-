"""Small SQLite persistence primitives for the local Windows runtime."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID


def _registry():
    from backend.app.models.agent import AgentRole, ExecutionStatus
    from backend.app.models.planner import ImplementationPlan, ImplementationStep, PersistedPlan
    from backend.app.models.task import (
        ActorType, AgentRunRecord, AgentStateRecord, ApprovalRecord,
        TaskRecord, TransitionRecord,
    )
    from backend.app.services.job_queue import Job, JobStatus
    from backend.app.workflow.states import WorkflowState
    classes = (
        TaskRecord, TransitionRecord, ApprovalRecord, AgentRunRecord,
        AgentStateRecord, PersistedPlan, ImplementationPlan, ImplementationStep,
        Job,
    )
    enums = (ActorType, AgentRole, ExecutionStatus, JobStatus, WorkflowState)
    return ({f"{cls.__module__}.{cls.__qualname__}": cls for cls in classes},
            {f"{cls.__module__}.{cls.__qualname__}": cls for cls in enums})


def _encode(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        name = f"{type(value).__module__}.{type(value).__qualname__}"
        return {"$type": "model", "name": name, "value": _encode(value.model_dump(mode="python"))}
    if dataclasses.is_dataclass(value):
        name = f"{type(value).__module__}.{type(value).__qualname__}"
        return {"$type": "dataclass", "name": name,
                "value": _encode(dataclasses.asdict(value))}
    if isinstance(value, Enum):
        return {"$type": "enum", "name": f"{type(value).__module__}.{type(value).__qualname__}",
                "value": value.value}
    if isinstance(value, UUID):
        return {"$type": "uuid", "value": str(value)}
    if isinstance(value, datetime):
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, set):
        return {"$type": "set", "value": [_encode(item) for item in value]}
    if isinstance(value, dict):
        return {"$type": "dict", "value": [[_encode(key), _encode(item)] for key, item in value.items()]}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported SQLite state value: {type(value).__name__}")


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if not isinstance(value, dict) or "$type" not in value:
        raise ValueError("SQLite state contains an invalid tagged value.")
    kind = value["$type"]
    if kind == "uuid":
        return UUID(value["value"])
    if kind == "datetime":
        return datetime.fromisoformat(value["value"])
    if kind == "set":
        return set(_decode(item) for item in value["value"])
    if kind == "dict":
        return {_decode(key): _decode(item) for key, item in value["value"]}
    if kind in {"model", "dataclass"}:
        classes, _ = _registry()
        cls = classes.get(value["name"])
        if cls is None:
            raise ValueError("SQLite state references an unsupported model.")
        content = _decode(value["value"])
        if kind == "model":
            return cls.model_validate(content)
        return cls(**content)
    if kind == "enum":
        _, enums = _registry()
        cls = enums.get(value["name"])
        if cls is None:
            raise ValueError("SQLite state references an unsupported enum.")
        return cls(value["value"])
    raise ValueError("SQLite state contains an unsupported type tag.")


class SQLiteStateStore:
    """Persist trusted local runtime state in one SQLite database.

    The local database is not a cloud interchange format; values are written by
    the runtime itself and are protected by the local filesystem boundary.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        legacy = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runtime_state'"
        ).fetchone()
        if legacy and self._connection.execute("SELECT 1 FROM runtime_state LIMIT 1").fetchone():
            self._connection.close()
            raise RuntimeError(
                "Legacy local runtime state cannot be safely decoded. Preserve the SQLite file and migrate it explicitly."
            )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS runtime_state_json "
            "(name TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self._connection.commit()

    async def load(self, name: str, default: Any = None) -> Any:
        async with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM runtime_state_json WHERE name = ?", (name,)
            ).fetchone()
            return _decode(json.loads(row[0])) if row else default

    async def save(self, name: str, value: Any) -> None:
        payload = json.dumps(_encode(value), separators=(",", ":"), ensure_ascii=True)
        async with self._lock:
            self._connection.execute(
                "INSERT INTO runtime_state_json(name, payload) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
                (name, payload),
            )
            self._connection.commit()

    async def close(self) -> None:
        async with self._lock:
            self._connection.close()
