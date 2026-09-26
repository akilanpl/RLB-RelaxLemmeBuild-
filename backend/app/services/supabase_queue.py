"""Supabase queue boundary; payloads contain identifiers only."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from backend.app.services.job_queue import Job, JobStatus


class SupabaseQueueAdapter:
    """Adapter for a Supabase Queue client, kept injectable for tests."""

    def __init__(self, client: Any, queue_name: str = "task-execution"):
        self.client = client
        self.queue_name = queue_name

    @staticmethod
    def message(task_id: UUID, task_version: int, requested_at: Optional[datetime] = None) -> dict:
        return {
            "task_id": str(task_id),
            "task_version": task_version,
            "requested_at": (requested_at or datetime.now(timezone.utc)).isoformat(),
        }

    async def enqueue(self, task_id: UUID, user_id: UUID, task_version: int = 1) -> dict:
        payload = self.message(task_id, task_version)
        await self.client.send(self.queue_name, payload)
        return payload

    async def claim(self, worker_id: str) -> Optional[dict]:
        return await self.client.claim(self.queue_name, worker_id)

    async def heartbeat(self, receipt: str, visibility_timeout: int = 60) -> None:
        await self.client.extend(self.queue_name, receipt, visibility_timeout)

    async def complete(self, receipt: str) -> None:
        await self.client.ack(self.queue_name, receipt)

    async def fail(self, receipt: str, error: str) -> None:
        await self.client.release(self.queue_name, receipt, error)

    async def wait_for_approval(self, receipt: str) -> None:
        await self.client.release(self.queue_name, receipt, "waiting_for_human_approval")
