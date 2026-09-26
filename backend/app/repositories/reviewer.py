"""Persistence adapters for immutable reviewer reports."""
import json
from typing import Dict, List, Optional, Protocol
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from backend.app.models.audit import ReviewerReport


class ReviewerReportRepository(Protocol):
    async def add(self, report: ReviewerReport) -> ReviewerReport: ...
    async def get_by_task(self, task_id: UUID) -> Optional[ReviewerReport]: ...


class InMemoryReviewerReportRepository:
    def __init__(self):
        self.reports: Dict[UUID, ReviewerReport] = {}

    async def add(self, report):
        self.reports[report.id] = report
        return report

    async def get_by_task(self, task_id):
        reports = [r for r in self.reports.values() if r.task_id == task_id]
        return max(reports, key=lambda r: r.created_at) if reports else None


class PostgresReviewerReportRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def add(self, report):
        async with self.sessions.begin() as session:
            await session.execute(text("""INSERT INTO reviewer_reports
                (id, task_id, agent_run_id, summary, strengths, concerns,
                 security_audit, recommendation, task_understanding, implementation_summary,
                 changed_files, requirements_coverage, behavior_verified, tests_summary,
                 test_failures, repair_summary, remaining_risks, unresolved_items, evidence,
                 final_status, created_at)
                VALUES (:id,:task_id,:run_id,:summary,:strengths,:concerns,
                        :security_audit,:recommendation,:task_understanding,:implementation_summary,
                        :changed_files,:requirements_coverage,:behavior_verified,:tests_summary,
                        :test_failures,:repair_summary,:remaining_risks,:unresolved_items,:evidence,
                        :final_status,:created_at)"""), {
                "id": report.id, "task_id": report.task_id, "run_id": report.agent_run_id,
                "summary": report.summary, "strengths": json.dumps(report.strengths),
                "concerns": json.dumps(report.concerns), "security_audit": report.security_audit,
                "recommendation": report.recommendation.value, "created_at": report.created_at,
                "task_understanding": report.task_understanding,
                "implementation_summary": report.implementation_summary,
                "changed_files": json.dumps(report.changed_files),
                "requirements_coverage": json.dumps(report.requirements_coverage),
                "behavior_verified": json.dumps(report.behavior_verified),
                "tests_summary": json.dumps(report.tests_summary),
                "test_failures": json.dumps(report.test_failures),
                "repair_summary": json.dumps(report.repair_summary),
                "remaining_risks": json.dumps(report.remaining_risks),
                "unresolved_items": json.dumps(report.unresolved_items),
                "evidence": json.dumps(report.evidence),
                "final_status": report.final_status,
            })
        return report

    async def get_by_task(self, task_id):
        async with self.sessions() as session:
            row = (await session.execute(text(
                "SELECT * FROM reviewer_reports WHERE task_id=:task_id ORDER BY created_at DESC LIMIT 1"
            ), {"task_id": task_id})).mappings().first()
        if not row:
            return None
        return ReviewerReport(id=row["id"], task_id=row["task_id"], agent_run_id=row["agent_run_id"],
            summary=row["summary"], strengths=row["strengths"] if isinstance(row["strengths"], list) else json.loads(row["strengths"]),
            concerns=row["concerns"] if isinstance(row["concerns"], list) else json.loads(row["concerns"]),
            security_audit=row["security_audit"], recommendation=row["recommendation"],
            task_understanding=row.get("task_understanding") or "",
            implementation_summary=row.get("implementation_summary") or "",
            changed_files=_json_list(row.get("changed_files")),
            requirements_coverage=_json_list(row.get("requirements_coverage")),
            behavior_verified=_json_list(row.get("behavior_verified")),
            tests_summary=_json_list(row.get("tests_summary")),
            test_failures=_json_list(row.get("test_failures")),
            repair_summary=_json_list(row.get("repair_summary")),
            remaining_risks=_json_list(row.get("remaining_risks")),
            unresolved_items=_json_list(row.get("unresolved_items")),
            evidence=_json_list(row.get("evidence")),
            final_status=row.get("final_status") or "COMPLETED_WITH_LIMITATIONS",
            created_at=row["created_at"])


def _json_list(value):
    if not value:
        return []
    return value if isinstance(value, list) else json.loads(value)
