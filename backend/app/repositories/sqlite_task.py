"""SQLite-backed local task repository.

It reuses the mature in-memory repository semantics and checkpoints its state
after every mutation, keeping hosted PostgreSQL behavior unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from backend.app.repositories.task import InMemoryTaskRepository
from backend.app.storage.sqlite import SQLiteStateStore


class SQLiteTaskRepository(InMemoryTaskRepository):
    def __init__(self, path: str | Path):
        super().__init__()
        self._store = SQLiteStateStore(path)
        self.event_outbox: dict[str, dict[str, Any]] = {}

    async def load(self) -> None:
        state = await self._store.load("tasks")
        if state:
            self.tasks = state["tasks"]
            self.histories = state["histories"]
            self.approvals = state["approvals"]
            self.runs = state["runs"]
            self.states = state["states"]
            self.plans = state["plans"]
            self.messages = state["messages"]
            self.ai_calls = state.get("ai_calls", {})
            self.provider_calls = state.get("provider_calls", {})
            self.event_outbox = state.get("event_outbox", {})

    async def _save(self) -> None:
        await self._store.save("tasks", {
            "tasks": self.tasks, "histories": self.histories,
            "approvals": self.approvals, "runs": self.runs,
            "states": self.states, "plans": self.plans,
            "messages": self.messages, "ai_calls": self.ai_calls,
            "provider_calls": self.provider_calls, "event_outbox": self.event_outbox,
        })

    def _record_transition_event(self, transition) -> None:
        event = {
            "event_id": str(transition.id),
            "task_id": str(transition.task_id),
            "sequence": transition.task_version_after,
            "event_type": transition.new_state.value,
            "payload": {"workflow_state": transition.new_state.value,
                        "version": transition.task_version_after},
            "created_at": transition.timestamp.isoformat(),
            "source": "windows_runtime",
        }
        self.event_outbox[event["event_id"]] = event

    async def create(self, task):
        result = await super().create(task)
        self.event_outbox[str(task.id)] = {
            "event_id": str(task.id),
            "task_id": str(task.id),
            "sequence": 1,
            "event_type": "task_created",
            "payload": {
                "workflow_state": task.status.value,
                "version": task.version,
                "workspace_id": str(task.workspace_id),
            },
            "created_at": task.created_at.isoformat(),
            "source": "windows_runtime",
        }
        await self._save()
        return result

    async def transition(self, task_id, target, transition, expected_version):
        result = await super().transition(task_id, target, transition, expected_version)
        if result:
            self._record_transition_event(transition)
            await self._save()
        return result

    async def add_approval(self, approval):
        result = await super().add_approval(approval)
        await self._save()
        return result

    async def approve_and_transition(self, approval, target, transition, expected_version):
        result = await super().approve_and_transition(approval, target, transition, expected_version)
        if result:
            self._record_transition_event(transition)
            await self._save()
        return result

    async def add_run(self, run):
        result = await super().add_run(run)
        await self._save()
        return result

    async def update_run(self, run):
        result = await super().update_run(run)
        await self._save()
        return result

    async def add_state(self, state):
        result = await super().add_state(state)
        await self._save()
        return result

    async def add_plan(self, plan):
        result = await super().add_plan(plan)
        await self._save()
        return result

    async def add_message(self, task_id, sender_type, content, metadata):
        result = await super().add_message(task_id, sender_type, content, metadata)
        await self._save()
        return result

    async def set_active_staging(self, task_id, staging_id):
        result = await super().set_active_staging(task_id, staging_id)
        if result:
            await self._save()
        return result

    async def set_worker_override(self, task_id, role, worker_id):
        result = await super().set_worker_override(task_id, role, worker_id)
        if result:
            await self._save()
        return result

    async def reserve_ai_call(self, task_id, limit):
        result = await super().reserve_ai_call(task_id, limit)
        await self._save()
        return result

    async def record_provider_call(self, task_id, evidence):
        await super().record_provider_call(task_id, evidence)
        await self._save()

    async def pending_events(self, limit: int = 200) -> list[dict[str, Any]]:
        pending = sorted(self.event_outbox.values(),
                         key=lambda event: (event["task_id"], event["sequence"]))
        return pending[:limit]

    async def acknowledge_events(self, event_ids: list[str]) -> None:
        for event_id in event_ids:
            self.event_outbox.pop(event_id, None)
        await self._save()

    async def close(self) -> None:
        await self._store.close()
