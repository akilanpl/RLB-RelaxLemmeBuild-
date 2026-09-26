import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.ai.gateway import AIGateway, AIRequest, AIResponse
from backend.app.models.task import ActorType
from backend.app.models.workspace import Workspace
from backend.app.services.durable_worker import DurableTaskWorker
from backend.app.services.job_queue import JobStatus, LocalJobQueue
from backend.app.services.task_service import TaskAccessDeniedError, WorkflowEngine
from backend.app.workflow.states import WorkflowState
from backend.app.repositories.task import InMemoryTaskRepository


class FakeAIGateway(AIGateway):
    def __init__(self):
        self.calls = 0

    def validate_configuration(self):
        return None

    async def generate(self, request: AIRequest):
        self.calls += 1
        return AIResponse(content="deterministic")


def make_workspace(user_id):
    now = datetime.now(timezone.utc)
    return Workspace(
        id=uuid4(), user_id=user_id, name="runtime", slug="runtime",
        canonical_root_path="runtime/canonical", created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_queue_claim_lease_completion_and_duplicate_claim():
    user = uuid4()
    engine = WorkflowEngine(repository=InMemoryTaskRepository())
    task = await engine.create_task(make_workspace(user), user, "task", "objective")
    queue = LocalJobQueue(engine, lease_seconds=30)
    job = await queue.enqueue(task.id, user)
    first, second = await asyncio.gather(queue.claim("worker-a"), queue.claim("worker-b"))
    claimed = [item for item in (first, second) if item is not None]
    assert len(claimed) == 1
    owner = claimed[0].lease_owner
    await queue.complete(job.id, owner)
    assert queue.jobs[job.id].status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_worker_pauses_for_approval_then_resumes_to_completion():
    user = uuid4()
    engine = WorkflowEngine(repository=InMemoryTaskRepository())
    task = await engine.create_task(make_workspace(user), user, "task", "objective")
    queue = LocalJobQueue(engine)
    gateway = FakeAIGateway()

    async def ready(job):
        current = await engine.get_task(job.task_id, job.user_id)
        await engine.transition(current.id, WorkflowState.PLANNING, ActorType.SYSTEM, None,
                                "queued", expected_version=current.version)
        return WorkflowState.PLANNING

    async def planning(job):
        await gateway.generate(AIRequest(system_prompt="planner", user_prompt="objective"))
        current = await engine.get_task(job.task_id, job.user_id)
        await engine.transition(current.id, WorkflowState.PLAN_REVIEW, ActorType.SYSTEM, None,
                                "plan persisted", expected_version=current.version)
        return WorkflowState.PLAN_REVIEW

    async def coding(job):
        await gateway.generate(AIRequest(system_prompt="coder", user_prompt="objective"))
        current = await engine.get_task(job.task_id, job.user_id)
        await engine.transition(current.id, WorkflowState.CODE_REVIEW, ActorType.SYSTEM, None,
                                "proposal persisted", expected_version=current.version)
        return WorkflowState.CODE_REVIEW

    async def test_planning(job):
        current = await engine.get_task(job.task_id, job.user_id)
        await engine.transition(current.id, WorkflowState.TEST_EXECUTING, ActorType.SYSTEM, None,
                                "test plan persisted", expected_version=current.version)
        await engine.transition(current.id, WorkflowState.REVIEWING, ActorType.SYSTEM, None,
                                "tests passed", expected_version=current.version + 1)
        return WorkflowState.REVIEWING

    async def reviewing(job):
        await gateway.generate(AIRequest(system_prompt="reviewer", user_prompt="objective"))
        current = await engine.get_task(job.task_id, job.user_id)
        await engine.transition(current.id, WorkflowState.COMPLETED, ActorType.SYSTEM, None,
                                "review persisted", expected_version=current.version)
        return WorkflowState.COMPLETED

    worker = DurableTaskWorker(queue, "worker-a", {
        WorkflowState.READY: ready, WorkflowState.PLANNING: planning,
        WorkflowState.CODING: coding, WorkflowState.TEST_PLANNING: test_planning,
        WorkflowState.REVIEWING: reviewing,
    })
    await queue.enqueue(task.id, user)
    await worker.run_once()
    assert queue.jobs[next(iter(queue.jobs))].status == JobStatus.WAITING
    assert (await engine.get_task(task.id, user)).status == WorkflowState.PLAN_REVIEW

    current = await engine.get_task(task.id, user)
    await engine.record_approval(task.id, user, "plan", "approved", None)
    await queue.enqueue(task.id, user)
    await worker.run_once()
    assert (await engine.get_task(task.id, user)).status == WorkflowState.CODE_REVIEW

    await engine.record_approval(task.id, user, "code", "approved", None)
    await queue.enqueue(task.id, user)
    await worker.run_until_idle()
    assert (await engine.get_task(task.id, user)).status == WorkflowState.COMPLETED
    assert gateway.calls == 3


@pytest.mark.asyncio
async def test_worker_crash_recovery_does_not_rerun_completed_stage():
    user = uuid4()
    engine = WorkflowEngine(repository=InMemoryTaskRepository())
    task = await engine.create_task(make_workspace(user), user, "task", "objective")
    queue = LocalJobQueue(engine, lease_seconds=1)
    calls = {"planning": 0}

    async def planning(job):
        calls["planning"] += 1
        current = await engine.get_task(job.task_id, job.user_id)
        await engine.transition(current.id, WorkflowState.PLAN_REVIEW, ActorType.SYSTEM, None,
                                "plan persisted", expected_version=current.version)
        raise RuntimeError("worker disappeared after persistence")

    worker = DurableTaskWorker(queue, "worker-a", {WorkflowState.PLANNING: planning})
    await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None, "start",
                            expected_version=task.version)
    await queue.enqueue(task.id, user)
    with pytest.raises(RuntimeError):
        await worker.run_once()
    failed_job = next(iter(queue.jobs.values()))
    assert failed_job.status == JobStatus.FAILED
    await queue.enqueue(task.id, user)
    assert await worker.run_once() is not None
    assert calls["planning"] == 1
    assert (await engine.get_task(task.id, user)).status == WorkflowState.PLAN_REVIEW


@pytest.mark.asyncio
async def test_worker_security_and_terminal_task_protection():
    user_a, user_b = uuid4(), uuid4()
    engine = WorkflowEngine(repository=InMemoryTaskRepository())
    task = await engine.create_task(make_workspace(user_a), user_a, "task", "objective")
    queue = LocalJobQueue(engine)
    with pytest.raises(TaskAccessDeniedError):
        await queue.enqueue(task.id, user_b)
    await engine.transition(task.id, WorkflowState.CANCELLED, ActorType.USER, user_a,
                            "cancelled", expected_version=task.version)
    job = await queue.enqueue(task.id, user_a)
    assert await queue.claim("worker-a") is None
    assert queue.jobs[job.id].status == JobStatus.COMPLETED
