"""Deterministic reporting for incomplete lifecycle state."""

from datetime import datetime, timezone, timedelta
from typing import Any, Iterable


def find_orphaned_state(
    *,
    staging_workspaces: Iterable[Any] = (),
    agent_runs: Iterable[Any] = (),
    tasks: Iterable[Any] = (),
    executions: Iterable[Any] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Report suspicious records without mutating or deleting anything."""
    now = datetime.now(timezone.utc)
    staging = [
        {"id": str(item.id), "reason": "staging workspace has no active task"}
        for item in staging_workspaces
        if getattr(item, "task_id", None) is None
    ]
    runs = [
        {"id": str(item.id), "reason": "agent run remains running without completion"}
        for item in agent_runs
        if getattr(item, "started_at", None)
        and getattr(item, "completed_at", None) is None
        and getattr(getattr(item, "status", None), "value", None) in {"running", "queued"}
    ]
    stale_cutoff = now - timedelta(hours=1)
    abandoned = [
        {"id": str(item.id), "reason": "task is not terminal and has no recent update"}
        for item in tasks
        if getattr(item, "updated_at", now) < stale_cutoff
        and getattr(getattr(item, "status", None), "value", None) in {"repairing", "test_executing"}
    ]
    failed = [
        {"id": str(item.id), "reason": "execution contains a failure report"}
        for item in executions
        if getattr(item, "failure_report", None) is not None
    ]
    return {
        "staging_workspaces": staging,
        "incomplete_agent_runs": runs,
        "abandoned_tasks": abandoned,
        "failed_executions": failed,
    }
