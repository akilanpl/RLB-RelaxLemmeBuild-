"""Durable task worker orchestration independent of browser connectivity."""

import asyncio
from contextlib import suppress
from typing import Awaitable, Callable, Dict

from backend.app.services.job_queue import Job, JobStatus, LocalJobQueue
from backend.app.models.task import ActorType
from backend.app.services.task_service import TRANSITIONS
from backend.app.workflow.states import WorkflowState


StageHandler = Callable[[Job], Awaitable[WorkflowState]]


class DurableTaskWorker:
    def __init__(self, queue: LocalJobQueue, worker_id: str,
                 handlers: Dict[WorkflowState, StageHandler]):
        self.queue = queue
        self.worker_id = worker_id
        self.handlers = handlers

    async def run_once(self) -> Job | None:
        job = await self.queue.claim(self.worker_id)
        if job is None:
            return None
        try:
            while True:
                task = await self.queue.workflow.get_task(job.task_id, job.user_id)
                if task.status in {WorkflowState.CANCELLED, WorkflowState.COMPLETED, WorkflowState.FAILED}:
                    return await self.queue.complete(job.id, self.worker_id)
                if task.status in {WorkflowState.PLAN_REVIEW, WorkflowState.CODE_REVIEW}:
                    return await self.queue.wait_for_approval(job.id, self.worker_id)
                handler = self.handlers.get(task.status)
                if handler is None:
                    raise RuntimeError(f"No handler registered for workflow state {task.status.value}.")
                await self.queue.heartbeat(job.id, self.worker_id)
                await self._run_with_heartbeat(handler, job)
        except Exception as exc:
            # A lost lease must not overwrite the new owner's job or mask the
            # original exception with a second lease failure.
            with suppress(RuntimeError):
                await self.queue.fail(job.id, self.worker_id, str(exc))
            raise

    async def _run_with_heartbeat(self, handler, job):
        async def renew():
            while True:
                await asyncio.sleep(max(0.01, self.queue.lease_seconds / 3))
                await self.queue.heartbeat(job.id, self.worker_id)

        stage = asyncio.create_task(handler(job))
        heartbeat = asyncio.create_task(renew())
        try:
            done, _ = await asyncio.wait({stage, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                await heartbeat  # Losing the lease cancels work immediately.
            return await stage
        finally:
            stage.cancel()
            heartbeat.cancel()
            await asyncio.gather(stage, heartbeat, return_exceptions=True)

    async def run_until_idle(self, limit: int = 100) -> None:
        for _ in range(limit):
            if await self.run_once() is None:
                return


async def _mark_failed(workflow, job, exc: Exception) -> None:
    task = await workflow.get_task(job.task_id, job.user_id)
    if WorkflowState.FAILED not in TRANSITIONS.get(task.status, set()):
        return
    await workflow.transition(
        task.id, WorkflowState.FAILED, ActorType.SYSTEM, None,
        str(exc) or "Workflow step failed",
        expected_version=task.version,
    )


def build_default_worker(queue: LocalJobQueue, worker_id: str, planner, coder, reviewer,
                         test_orchestrator) -> DurableTaskWorker:
    """Bind existing agent services to the replaceable worker boundary."""
    workflow = queue.workflow

    async def ready(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None,
                                  "Durable worker started task", expected_version=task.version)
        return WorkflowState.PLANNING

    async def planning(job):
        try:
            history = await workflow.get_history(job.task_id, job.user_id)
            feedback = history[-1].metadata.get("feedback") if history else None
            plan = await planner.execute(job.task_id, job.user_id, feedback)
        except Exception as exc:
            await _mark_failed(workflow, job, exc)
            raise
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow.transition(task.id, WorkflowState.PLAN_REVIEW, ActorType.SYSTEM, None,
                                  "Planner produced a structured plan",
                                  {"plan_id": str(plan.id)}, expected_version=task.version)
        return WorkflowState.PLAN_REVIEW

    async def coding(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        try:
            history = await workflow.get_history(job.task_id, job.user_id)
            feedback = history[-1].metadata.get("feedback") if history else None
            proposal = await coder.execute(task.id, job.user_id, task.active_staging_workspace_id, feedback)
        except Exception as exc:
            await _mark_failed(workflow, job, exc)
            raise
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow.transition(task.id, WorkflowState.CODE_REVIEW, ActorType.SYSTEM, None,
                                  "Coder produced a structured code proposal",
                                  {"proposal_id": str(proposal.id)}, expected_version=task.version)
        return WorkflowState.CODE_REVIEW

    async def testing(job):
        try:
            await test_orchestrator.plan_and_execute(job.task_id, job.user_id)
        except Exception as exc:
            await _mark_failed(workflow, job, exc)
            raise
        return (await workflow.get_task(job.task_id, job.user_id)).status

    async def repairing(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow._attach_plan_staging(task, job.user_id)
        executions = await test_orchestrator.repository.list_executions(task.id)
        feedback = executions[-1].failure_report.model_dump_json() if executions and executions[-1].failure_report else "Repair failing tests."
        await workflow.transition(task.id, WorkflowState.CODING, ActorType.SYSTEM, None,
                                  "Repair requested from failed tests", {"feedback": feedback}, expected_version=task.version)
        return WorkflowState.CODING

    async def reviewing(job):
        await reviewer.execute(job.task_id, job.user_id)
        return WorkflowState.COMPLETED

    return DurableTaskWorker(queue, worker_id, {
        WorkflowState.READY: ready,
        WorkflowState.PLANNING: planning,
        WorkflowState.CODING: coding,
        WorkflowState.TEST_PLANNING: testing,
        WorkflowState.TEST_EXECUTING: testing,
        WorkflowState.REPAIRING: repairing,
        WorkflowState.REVIEWING: reviewing,
    })
