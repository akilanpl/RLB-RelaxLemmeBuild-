"""Replaceable durable-execution boundary for local and future cloud workers."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Optional, Protocol
from uuid import UUID, uuid4

from backend.app.services.task_service import TaskAccessDeniedError, TaskNotFoundError, WorkflowEngine
from backend.app.workflow.states import WorkflowState


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    id: UUID
    task_id: UUID
    user_id: UUID
    status: JobStatus = JobStatus.PENDING
    lease_owner: Optional[str] = None
    lease_until: Optional[datetime] = None
    attempts: int = 0
    error: Optional[str] = None
    completed_by: Optional[str] = None


class JobQueue(Protocol):
    workflow: WorkflowEngine
    lease_seconds: int
    async def enqueue(self, task_id: UUID, user_id: UUID): ...
    async def claim(self, worker_id: str): ...
    async def heartbeat(self, job_id: UUID, worker_id: str): ...
    async def complete(self, job_id: UUID, worker_id: str): ...
    async def fail(self, job_id: UUID, worker_id: str, error: str): ...
    async def release(self, job_id: UUID, worker_id: str): ...
    async def wait_for_approval(self, job_id: UUID, worker_id: str): ...
    async def pause_task(self, task_id: UUID, user_id: UUID): ...
    async def resume_task(self, task_id: UUID, user_id: UUID): ...
    async def is_paused(self, task_id: UUID): ...


class LocalJobQueue:
    """Small in-process queue with leases; cloud adapters can implement this port."""

    def __init__(self, workflow: WorkflowEngine, lease_seconds: int = 60):
        self.workflow = workflow
        self.lease_seconds = lease_seconds
        self.jobs: Dict[UUID, Job] = {}
        self.paused_tasks: set[UUID] = set()
        self._prompts: Dict[UUID, list[str]] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, task_id: UUID, user_id: UUID) -> Job:
        await self.workflow.get_task(task_id, user_id)
        async with self._lock:
            existing = next((job for job in self.jobs.values() if job.task_id == task_id
                             and job.status in {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.WAITING}), None)
            if existing:
                if existing.status == JobStatus.WAITING:
                    existing.status = JobStatus.PENDING
                    existing.attempts = 0
                return existing
            job = Job(uuid4(), task_id, user_id)
            self.jobs[job.id] = job
            return job

    async def claim(self, worker_id: str) -> Optional[Job]:
        async with self._lock:
            now = datetime.now(timezone.utc)
            for job in self.jobs.values():
                if job.status == JobStatus.RUNNING and job.lease_until and job.lease_until <= now:
                    job.status = JobStatus.PENDING
                    job.lease_owner = None
                    job.lease_until = None
                if job.status != JobStatus.PENDING:
                    continue
                task = await self.workflow.get_task(job.task_id, job.user_id)
                if job.task_id in self.paused_tasks:
                    continue
                if task.status in {WorkflowState.CANCELLED, WorkflowState.COMPLETED, WorkflowState.FAILED}:
                    job.status = JobStatus.COMPLETED
                    continue
                job.status = JobStatus.RUNNING
                job.lease_owner = worker_id
                job.lease_until = now + timedelta(seconds=self.lease_seconds)
                job.attempts += 1
                return job
            return None

    async def pause_task(self, task_id: UUID, user_id: UUID) -> None:
        await self.workflow.get_task(task_id, user_id)
        async with self._lock:
            self.paused_tasks.add(task_id)

    async def resume_task(self, task_id: UUID, user_id: UUID) -> None:
        await self.workflow.get_task(task_id, user_id)
        async with self._lock:
            self.paused_tasks.discard(task_id)

    async def is_paused(self, task_id: UUID) -> bool:
        async with self._lock:
            return task_id in self.paused_tasks

    async def add_prompt(self, task_id: UUID, user_id: UUID, prompt: str) -> None:
        task = await self.workflow.get_task(task_id, user_id)
        if task.status not in {WorkflowState.READY, WorkflowState.ANALYZING, WorkflowState.PLANNING,
                               WorkflowState.CODING, WorkflowState.REPAIRING, WorkflowState.TEST_EXECUTING}:
            raise ValueError("Prompts cannot bypass a review gate or terminal state.")
        async with self._lock:
            self._prompts.setdefault(task_id, []).append(prompt)

    async def pending_prompts(self, task_id: UUID) -> list[str]:
        async with self._lock:
            return list(self._prompts.get(task_id, []))

    async def clear_prompts(self, task_id: UUID, count: int) -> None:
        async with self._lock:
            pending = self._prompts.get(task_id, [])
            remaining = pending[count:]
            if remaining:
                self._prompts[task_id] = remaining
            else:
                self._prompts.pop(task_id, None)

    async def heartbeat(self, job_id: UUID, worker_id: str) -> Job:
        async with self._lock:
            job = self.jobs[job_id]
            if job.status != JobStatus.RUNNING or job.lease_owner != worker_id:
                raise RuntimeError("Job lease is not owned by this worker.")
            job.lease_until = datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
            return job

    async def complete(self, job_id: UUID, worker_id: str) -> Job:
        async with self._lock:
            job = self.jobs[job_id]
            if job.status == JobStatus.COMPLETED and job.completed_by == worker_id:
                return job
            self._assert_owner(job, worker_id)
            job.status = JobStatus.COMPLETED
            job.completed_by = worker_id
            job.lease_owner = job.lease_until = None
            return job

    async def fail(self, job_id: UUID, worker_id: str, error: str) -> Job:
        async with self._lock:
            job = self.jobs[job_id]
            self._assert_owner(job, worker_id)
            job.status = JobStatus.FAILED
            job.error = error
            job.lease_owner = job.lease_until = None
            return job

    async def release(self, job_id: UUID, worker_id: str) -> Job:
        async with self._lock:
            job = self.jobs[job_id]
            self._assert_owner(job, worker_id)
            job.status = JobStatus.PENDING
            job.lease_owner = job.lease_until = None
            return job

    async def wait_for_approval(self, job_id: UUID, worker_id: str) -> Job:
        async with self._lock:
            job = self.jobs[job_id]
            self._assert_owner(job, worker_id)
            job.status = JobStatus.WAITING
            job.lease_owner = job.lease_until = None
            return job

    @staticmethod
    def _assert_owner(job: Job, worker_id: str) -> None:
        if job.status != JobStatus.RUNNING or job.lease_owner != worker_id:
            raise RuntimeError("Job lease is not owned by this worker.")


default_job_queue: Optional[LocalJobQueue] = None
