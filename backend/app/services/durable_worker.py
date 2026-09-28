"""Durable task worker orchestration independent of browser connectivity."""

import asyncio
from contextlib import suppress
from typing import Awaitable, Callable, Dict

from backend.app.services.job_queue import Job, JobStatus, JobQueue
from backend.app.models.task import ActorType
from backend.app.services.task_service import TRANSITIONS
from backend.app.workflow.states import WorkflowState


StageHandler = Callable[[Job], Awaitable[WorkflowState]]


def _transient(exc):
    from backend.app.ai.failover import TransientProviderError
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, TransientProviderError):
            return True
        seen.add(id(exc))
        exc = exc.__cause__
    return False


class MissingStageHandler(RuntimeError):
    pass


class TaskCancelled(RuntimeError):
    pass


class DurableTaskWorker:
    def __init__(self, queue: JobQueue, worker_id: str,
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
                    raise MissingStageHandler(f"No handler registered for workflow state {task.status.value}.")
                await self.queue.heartbeat(job.id, self.worker_id)
                await self._run_with_heartbeat(handler, job)
        except TaskCancelled:
            return await self.queue.complete(job.id, self.worker_id)
        except Exception as exc:
            # A lost lease must not overwrite the new owner's job or mask the
            # original exception with a second lease failure.
            with suppress(RuntimeError):
                if _transient(exc) and job.attempts < 3:
                    await self.queue.release(job.id, self.worker_id)
                else:
                    if _transient(exc):
                        await _mark_failed(self.queue.workflow, job, RuntimeError('Provider retry limit exhausted.'))
                    await self.queue.fail(job.id, self.worker_id, str(exc) if isinstance(exc, MissingStageHandler) else type(exc).__name__)
            raise

    async def _run_with_heartbeat(self, handler, job):
        async def renew():
            while True:
                await asyncio.sleep(max(0.01, self.queue.lease_seconds / 3))
                await self.queue.heartbeat(job.id, self.worker_id)
                task = await self.queue.workflow.get_task(job.task_id, job.user_id)
                if task.status == WorkflowState.CANCELLED:
                    raise TaskCancelled('Task cancelled by user.')

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
    if _transient(exc):
        return
    task = await workflow.get_task(job.task_id, job.user_id)
    if WorkflowState.FAILED not in TRANSITIONS.get(task.status, set()):
        return
    await workflow.transition(
        task.id, WorkflowState.FAILED, ActorType.SYSTEM, None,
        str(exc) or "Workflow step failed",
        expected_version=task.version,
    )


def build_default_worker(queue: JobQueue, worker_id: str, planner, coder, reviewer,
                         test_orchestrator) -> DurableTaskWorker:
    """Bind existing agent services to the replaceable worker boundary."""
    workflow = queue.workflow

    async def ready(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow.transition(task.id, WorkflowState.ANALYZING, ActorType.SYSTEM, None,
                                  "Durable worker started analysis", expected_version=task.version)
        return WorkflowState.ANALYZING

    async def analyzing(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        try:
            from backend.app.analysis.service import CodebaseAnalysisService
            await CodebaseAnalysisService(workspace_service=workflow.workspace_service).analyze_workspace(task.workspace_id, job.user_id)
        except Exception as exc:
            await _mark_failed(workflow, job, exc)
            raise
        await workflow.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None,
                                  "Repository analysis completed", expected_version=task.version)
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

    async def staging_setup(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        if task.active_staging_workspace_id is None:
            await workflow._attach_plan_staging(task, job.user_id)
        await workflow.transition(task.id, WorkflowState.CODING, ActorType.SYSTEM, None,
            'Isolated staging ready', expected_version=task.version)
        return WorkflowState.CODING

    async def promoting(job):
        task = await workflow.get_task(job.task_id, job.user_id)
        if task.approved_proposal_id is None:
            raise RuntimeError('Persisted code approval is missing.')
        await coder.approve_and_apply(task.approved_proposal_id, job.user_id, already_approved=True)
        return WorkflowState.TEST_PLANNING

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
        report = await reviewer.execute(job.task_id, job.user_id)
        task = await workflow.get_task(job.task_id, job.user_id)
        await workflow.transition(task.id, WorkflowState.COMPLETED, ActorType.SYSTEM, None,
            'Read-only reviewer evidence persisted', {'reviewer_report_id': str(report.id)}, expected_version=task.version)
        return WorkflowState.COMPLETED

    return DurableTaskWorker(queue, worker_id, {
        WorkflowState.READY: ready,
        WorkflowState.ANALYZING: analyzing,
        WorkflowState.PLANNING: planning,
        WorkflowState.STAGING_SETUP: staging_setup,
        WorkflowState.PROMOTING: promoting,
        WorkflowState.CODING: coding,
        WorkflowState.TEST_PLANNING: testing,
        WorkflowState.TEST_EXECUTING: testing,
        WorkflowState.REPAIRING: repairing,
        WorkflowState.REVIEWING: reviewing,
    })
