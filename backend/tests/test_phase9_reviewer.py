import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.core.permissions import AgentPermissionGatekeeper, SecurityViolationError
from backend.app.models.agent import AgentRole
from backend.app.models.audit import ReviewerReport, ReviewRecommendation
from backend.app.models.task import TaskRecord
from backend.app.services.reviewer_context import ReviewerContextBuilder
from backend.app.workflow.states import WorkflowState


def task():
    return TaskRecord(
        id=uuid4(), workspace_id=uuid4(), conversation_id=uuid4(), user_id=uuid4(),
        title="review", objective="x" * 100_000, user_prompt="x",
        approved_snapshot_hash=None, created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc), status=WorkflowState.REVIEWING,
    )


def test_reviewer_report_is_descriptive_and_has_no_score():
    report = ReviewerReport(
        id=uuid4(), task_id=uuid4(), agent_run_id=uuid4(), summary="summary",
        strengths=["clear"], concerns=[], security_audit="none",
        recommendation=ReviewRecommendation.READY_TO_MERGE,
        created_at=datetime.now(timezone.utc),
    )
    assert "overall_score" not in report.model_dump()


def test_reviewer_context_is_bounded():
    # The builder has no external dependencies for the base task snapshot.
    import asyncio
    result = asyncio.run(ReviewerContextBuilder(max_chars=2_000).build(task()))
    assert len(json.dumps(result, default=str)) <= 2_000
    assert result["truncated"] is True


def test_reviewer_cannot_write_or_execute_commands():
    with pytest.raises(SecurityViolationError):
        AgentPermissionGatekeeper.assert_tool_permitted(AgentRole.REVIEWER, "write_staging_file")
    with pytest.raises(SecurityViolationError):
        AgentPermissionGatekeeper.assert_tool_permitted(AgentRole.REVIEWER, "run_sandbox_command")
