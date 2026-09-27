"""Bounded, read-only context supplied to the final reviewer."""

import json
from typing import Any, Dict
from backend.app.models.task import TaskRecord


class ReviewerContextBuilder:
    """Builds a finite snapshot; it never grants the reviewer write or shell access."""

    def __init__(self, workflow=None, max_chars: int = 80_000, proposals=None, testing=None):
        self.workflow = workflow
        self.max_chars = max_chars
        self.proposals = proposals
        self.testing = testing

    async def build(self, task: TaskRecord) -> Dict[str, Any]:
        workflow = self.workflow
        context: Dict[str, Any] = {
            "task": {"id": str(task.id), "title": _redact(task.title), "objective": _redact(task.objective),
                     "state": task.status.value, "approved_snapshot_hash": task.approved_snapshot_hash},
            "plans": [], "proposals": [], "tests": [], "history": [],
        }
        if workflow is not None:
            context["plans"] = [p.model_dump(mode="json") for p in await workflow.list_plans(task.id, task.user_id)]
            if hasattr(workflow, "list_proposals"):
                context["proposals"] = [p.model_dump(mode="json") for p in await workflow.list_proposals(task.id, task.user_id)]
            if hasattr(workflow, "list_test_executions"):
                context["tests"] = [x.model_dump(mode="json") for x in await workflow.list_test_executions(task.id, task.user_id)]
            context["history"] = [h.model_dump(mode="json") for h in await workflow.get_history(task.id, task.user_id)]
        if self.proposals is not None:
            context["proposals"] = [p.model_dump(mode="json") for p in await self.proposals.list_by_task(task.id)]
        if self.testing is not None:
            context["tests"] = [x.model_dump(mode="json") for x in await self.testing.list_executions(task.id)]
        # Keep prompts bounded even when logs/diffs are unusually large.
        if len(json.dumps(context, default=str)) > self.max_chars:
            context["truncated"] = True
            # Preserve the useful descriptive metadata while dropping unbounded
            # diffs, logs, and historical payloads.
            context["history"] = []
            context["plans"] = [
                {"id": p.get("id"), "revision_number": p.get("revision_number"),
                 "plan": p.get("plan", {}).get("understanding", "")[:2_000]}
                for p in context["plans"]
            ]
            context["proposals"] = [
                {"id": p.get("id"), "summary": p.get("summary", "")[:2_000],
                 "warnings": p.get("warnings", [])[:20]}
                for p in context["proposals"]
            ]
            context["tests"] = context["tests"][:20]
        # A pathological objective can otherwise defeat the collection limits.
        serialized = json.dumps(context, default=str)
        if len(serialized) > self.max_chars:
            context["task"]["objective"] = context["task"]["objective"][:2_000]
            context["plans"] = context["plans"][:20]
            context["proposals"] = context["proposals"][:20]
            context["tests"] = context["tests"][:20]
            context["truncated"] = True
        if len(json.dumps(context, default=str)) > self.max_chars:
            # Keep the contract bounded even for adversarially large fields.
            context = {
                "task": {**context["task"], "objective": context["task"]["objective"][:500]},
                "plans": context["plans"][:5], "proposals": context["proposals"][:5],
                "tests": context["tests"][:5], "history": [], "truncated": True,
            }
        return context


def _redact(value: str) -> str:
    for marker in ("sk-", "GROQ_", "OPENAI_", "Bearer "):
        value = value.replace(marker, "[REDACTED]")
    return value
