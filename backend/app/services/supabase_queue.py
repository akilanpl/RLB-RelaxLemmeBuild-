"""Supabase queue boundary; payloads contain identifiers only."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid5, NAMESPACE_URL

from backend.app.services.job_queue import Job, JobStatus


class SupabaseQueueAdapter:
    """Adapter for a Supabase Queue client, kept injectable for tests."""

    def __init__(self, client: Any, queue_name: str = "task_execution", workflow=None):
        self.client = client
        self.queue_name = queue_name
        self.workflow = workflow
        self.lease_seconds = 60
        self._jobs = {}

    @staticmethod
    def message(task_id: UUID, task_version: int, requested_at: Optional[datetime] = None) -> dict:
        return {
            "task_id": str(task_id),
            "task_version": task_version,
            "requested_at": (requested_at or datetime.now(timezone.utc)).isoformat(),
        }

    async def enqueue(self, task_id: UUID, user_id: UUID, task_version: int = 1) -> dict:
        if self.workflow is not None:
            task = await self.workflow.get_task(task_id, user_id)
            task_version = task.version
        payload = self.message(task_id, task_version)
        receipt = await self.client.send(self.queue_name, payload)
        if self.workflow is not None:
            return Job(uuid5(NAMESPACE_URL, f"{self.queue_name}/{receipt}"), task_id, user_id)
        return payload

    async def claim(self, worker_id: str):
        delivery = await self.client.claim(self.queue_name, worker_id)
        if delivery is None or self.workflow is None:
            return delivery
        receipt = delivery["receipt"]
        task_id = UUID(delivery["message"]["task_id"])
        job = Job(uuid5(NAMESPACE_URL, f"{self.queue_name}/{receipt}"), task_id,
                  UUID(str(delivery["user_id"])), status=JobStatus.RUNNING,
                  lease_owner=worker_id, attempts=delivery.get("attempts", 1))
        self._jobs[job.id] = (job, receipt)
        return job

    def _owned(self, job_id, worker_id):
        item = self._jobs.get(job_id)
        if item is None or item[0].lease_owner != worker_id:
            raise RuntimeError("Job lease is not owned by this worker.")
        return item

    async def heartbeat(self, job_id, worker_id=None):
        if self.workflow is None:
            await self.client.extend(self.queue_name, job_id, worker_id or 60)
            return
        job, receipt = self._owned(job_id, worker_id)
        await self.client.extend(self.queue_name, receipt, self.lease_seconds)
        return job

    async def complete(self, job_id, worker_id=None):
        if self.workflow is None:
            return await self.client.ack(self.queue_name, job_id)
        job, receipt = self._owned(job_id, worker_id)
        await self.client.ack(self.queue_name, receipt)
        self._jobs.pop(job_id)
        job.status = JobStatus.COMPLETED
        return job

    async def fail(self, job_id, worker_id, error=None):
        if self.workflow is None:
            return await self.client.release(self.queue_name, job_id, worker_id)
        job, receipt = self._owned(job_id, worker_id)
        if job.attempts >= 3:
            await self.client.ack(self.queue_name, receipt)
        else:
            await self.client.release(self.queue_name, receipt, error)
        self._jobs.pop(job_id)
        job.status = JobStatus.FAILED
        job.error = error
        return job

    async def wait_for_approval(self, job_id, worker_id=None):
        if self.workflow is None:
            return await self.client.release(self.queue_name, job_id, "waiting_for_human_approval")
        job = await self.complete(job_id, worker_id)
        job.status = JobStatus.WAITING
        return job
