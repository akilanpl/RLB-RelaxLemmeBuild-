"""Crash-recoverable local queue for the Windows runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.app.services.job_queue import Job, JobStatus, LocalJobQueue
from backend.app.storage.sqlite import SQLiteStateStore


class SQLiteJobQueue(LocalJobQueue):
    def __init__(self, workflow, path: str | Path, lease_seconds: int = 60):
        super().__init__(workflow, lease_seconds)
        self._store = SQLiteStateStore(path)

    async def load(self) -> None:
        state = await self._store.load("local_queue")
        if state:
            self.jobs = state["jobs"]
            self.paused_tasks = state.get("paused_tasks", set())
            self._prompts = state.get("prompts", {})
        else:
            self.jobs = await self._store.load("jobs", {})
        # A process that exited while holding a lease must be reclaimable.
        for job in self.jobs.values():
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.PENDING
                job.lease_owner = job.lease_until = None

    async def _save(self) -> None:
        await self._store.save("local_queue", {
            "jobs": self.jobs, "paused_tasks": self.paused_tasks,
            "prompts": self._prompts,
        })

    async def enqueue(self, task_id, user_id):
        job = await super().enqueue(task_id, user_id)
        await self._save()
        return job

    async def claim(self, worker_id):
        job = await super().claim(worker_id)
        await self._save()
        return job

    async def heartbeat(self, job_id, worker_id):
        job = await super().heartbeat(job_id, worker_id)
        await self._save()
        return job

    async def complete(self, job_id, worker_id):
        job = await super().complete(job_id, worker_id)
        await self._save()
        return job

    async def fail(self, job_id, worker_id, error):
        job = await super().fail(job_id, worker_id, error)
        await self._save()
        return job

    async def release(self, job_id, worker_id):
        job = await super().release(job_id, worker_id)
        await self._save()
        return job

    async def wait_for_approval(self, job_id, worker_id):
        job = await super().wait_for_approval(job_id, worker_id)
        await self._save()
        return job

    async def pause_task(self, task_id, user_id):
        await super().pause_task(task_id, user_id)
        await self._save()

    async def resume_task(self, task_id, user_id):
        await super().resume_task(task_id, user_id)
        await self._save()

    async def add_prompt(self, task_id, user_id, prompt):
        await super().add_prompt(task_id, user_id, prompt)
        await self._save()

    async def clear_prompts(self, task_id, count):
        await super().clear_prompts(task_id, count)
        await self._save()

    async def close(self) -> None:
        await self._store.close()
