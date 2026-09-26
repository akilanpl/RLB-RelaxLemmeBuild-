from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.models.task import ActorType, TaskRecord, TransitionRecord
from backend.app.repositories.task import InMemoryTaskRepository
from backend.app.workflow.states import WorkflowState


def task():
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id=uuid4(), workspace_id=uuid4(), conversation_id=uuid4(), user_id=uuid4(),
        title="persist", objective="persist", user_prompt="persist",
        created_at=now, updated_at=now,
    )


@pytest.mark.asyncio
async def test_in_memory_repository_is_an_explicit_optimistic_concurrency_double():
    repository = InMemoryTaskRepository()
    record = task()
    await repository.create(record)
    transition = TransitionRecord(
        id=uuid4(), task_id=record.id, previous_state=WorkflowState.READY,
        new_state=WorkflowState.PLANNING, actor_type=ActorType.USER, reason="start",
        timestamp=record.updated_at, task_version_before=1, task_version_after=2,
    )
    assert await repository.transition(record.id, WorkflowState.PLANNING, transition, 1)
    assert await repository.transition(record.id, WorkflowState.PLAN_REVIEW, transition, 1) is None
    assert (await repository.history(record.id))[0].new_state == WorkflowState.PLANNING
