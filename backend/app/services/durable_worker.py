"""Durable task worker orchestration independent of browser connectivity."""

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
                if task.status in {WorkflowState.CANCELLED, WorkflowState.COMPLETED}:
                    return await self.queue.complete(job.id, self.worker_id)
                if task.status in {WorkflowState.PLAN_REVIEW, WorkflowState.CODE_REVIEW}:
                    return await self.queue.wait_for_approval(job.id, self.worker_id)
                handler = self.handlers.get(task.status)
                if handler is None:
                    await self.queue.fail(
                        job.id,
                        self.worker_id,
                        f"No handler registered for workflow state {task.status.value}.",
                    )
                    raise RuntimeError(f"No handler registered for workflow state {task.status.value}.")
                await self.queue.heartbeat(job.id, self.worker_id)
                await handler(job)
        except Exception as exc:
            await self.queue.fail(job.id, self.worker_id, str(exc))
            raise

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
            plan = await planner.execute(job.task_id, job.user_id)
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
            proposal = await coder.execute(task.id, job.user_id, task.active_staging_workspace_id)
        except Exception as exc:
            await _mark_failed(workflow, job, exc)
            raise
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow.transition(task.id, WorkflowState.CODE_REVIEW, ActorType.SYSTEM, None,
                                  "Coder produced a structured code proposal",
                                  {"proposal_id": str(proposal.id)}, expected_version=task.version)
        return WorkflowState.CODE_REVIEW

    async def testing(job):
        await test_orchestrator.plan_and_execute(job.task_id, job.user_id)
        return (await workflow.get_task(job.task_id, job.user_id)).status

    async def repairing(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow.transition(task.id, WorkflowState.CODING, ActorType.SYSTEM, None,
                                  "Repair requested from failed tests", expected_version=task.version)
        return WorkflowState.CODING

    async def reviewing(job):
        await reviewer.execute(job.task_id, job.user_id)
        return WorkflowState.COMPLETED

    return DurableTaskWorker(queue, worker_id, {
        WorkflowState.READY: ready,
        WorkflowState.PLANNING: planning,
        WorkflowState.CODING: coding,
        WorkflowState.TEST_PLANNING: testing,
        WorkflowState.REPAIRING: repairing,
        WorkflowState.REVIEWING: reviewing,
    })
