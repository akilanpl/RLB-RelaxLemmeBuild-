"""Persistence ports for the testing entities (test plans, cases and runs)."""

from datetime import datetime, timezone
import json
from typing import Dict, List, Optional, Protocol
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from backend.app.models.agent import ExecutionStatus
from backend.app.models.test import BaselineCheckType, BuildResult, TestCase, TestCaseCategory, TestExecution, TestPlan


class TestingRepository(Protocol):
    async def add_plan(self, plan: TestPlan) -> TestPlan: ...
    async def get_plan(self, plan_id: UUID) -> Optional[TestPlan]: ...
    async def list_plans(self, task_id: UUID) -> List[TestPlan]: ...
    async def add_execution(self, execution: TestExecution) -> TestExecution: ...
    async def add_build_result(self, result: BuildResult) -> BuildResult: ...
    async def list_executions(self, task_id: UUID) -> List[TestExecution]: ...


class InMemoryTestingRepository:
    """Explicit test double; production callers can provide a SQL adapter."""
    def __init__(self):
        self.plans: Dict[UUID, TestPlan] = {}
        self.executions: Dict[UUID, TestExecution] = {}

    async def add_plan(self, plan):
        self.plans[plan.id] = plan
        return plan

    async def get_plan(self, plan_id):
        return self.plans.get(plan_id)

    async def list_plans(self, task_id):
        return sorted((p for p in self.plans.values() if p.task_id == task_id), key=lambda p: p.created_at)

    async def add_execution(self, execution):
        self.executions[execution.id] = execution
        return execution

    async def add_build_result(self, result):
        execution = self.executions[result.test_execution_id]
        self.executions[result.test_execution_id] = execution.model_copy(
            update={"baseline_results": [*execution.baseline_results, result]}
        )
        return result

    async def list_executions(self, task_id):
        return sorted((e for e in self.executions.values() if e.task_id == task_id), key=lambda e: e.created_at)


class PostgresTestingRepository:
    """SQL adapter for the existing test_plans/test_cases/test_executions/build_results entities."""
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]):
        self.sessionmaker = sessionmaker

    async def add_plan(self, plan):
        async with self.sessionmaker() as session:
            await session.execute(text(
                "INSERT INTO test_plans (id, task_id, agent_run_id, plan_summary, created_at) "
                "VALUES (:id, :task_id, :run_id, :summary, :created_at)"
            ), {"id": plan.id, "task_id": plan.task_id, "run_id": plan.agent_run_id,
                "summary": plan.plan_summary, "created_at": plan.created_at})
            for case in plan.test_cases:
                await session.execute(text(
                    "INSERT INTO test_cases (id, test_plan_id, category, title, description, expected_result, test_code, created_at) "
                    "VALUES (:id, :plan_id, :category, :title, :description, :expected, :code, :created_at)"
                ), {"id": case.id, "plan_id": plan.id, "category": case.category.value,
                    "title": case.title, "description": case.description, "expected": case.expected_result,
                    "code": case.test_code, "created_at": case.created_at})
            await session.commit()
        return plan

    async def get_plan(self, plan_id):
        async with self.sessionmaker() as session:
            row = (await session.execute(text("SELECT * FROM test_plans WHERE id=:id"), {"id": plan_id})).mappings().first()
            if not row:
                return None
            cases = (await session.execute(text("SELECT * FROM test_cases WHERE test_plan_id=:id ORDER BY created_at"),
                                           {"id": plan_id})).mappings().all()
            return _plan(row, cases)

    async def list_plans(self, task_id):
        async with self.sessionmaker() as session:
            rows = (await session.execute(text("SELECT * FROM test_plans WHERE task_id=:id ORDER BY created_at"),
                                          {"id": task_id})).mappings().all()
            result = []
            for row in rows:
                cases = (await session.execute(text("SELECT * FROM test_cases WHERE test_plan_id=:id ORDER BY created_at"),
                                                {"id": row["id"]})).mappings().all()
                result.append(_plan(row, cases))
            return result

    async def add_execution(self, execution):
        async with self.sessionmaker() as session:
            await session.execute(text(
                "INSERT INTO test_executions (id, task_id, agent_run_id, all_passed, total_tests, passed_tests, failed_tests, execution_duration_ms, failure_report, created_at) "
                "VALUES (:id,:task_id,:run_id,:all_passed,:total,:passed,:failed,:duration,:report,:created_at) "
                "ON CONFLICT (id) DO UPDATE SET all_passed=:all_passed,total_tests=:total,passed_tests=:passed,failed_tests=:failed,execution_duration_ms=:duration,failure_report=:report"
            ), {"id": execution.id, "task_id": execution.task_id, "run_id": execution.agent_run_id,
                "all_passed": execution.all_passed, "total": execution.total_tests, "passed": execution.passed_tests,
                "failed": execution.failed_tests, "duration": execution.execution_duration_ms,
                "report": json.dumps(execution.failure_report.model_dump(mode="json")) if execution.failure_report else None,
                "created_at": execution.created_at})
            await session.commit()
        return execution

    async def add_build_result(self, result):
        async with self.sessionmaker() as session:
            await session.execute(text(
                "INSERT INTO build_results (id,test_execution_id,check_type,status,exit_code,stdout_output,stderr_output,duration_ms,created_at) "
                "VALUES (:id,:execution,:check,:status,:exit,:stdout,:stderr,:duration,:created_at)"
            ), {"id": result.id, "execution": result.test_execution_id, "check": result.check_type.value,
                "status": result.status.value, "exit": result.exit_code, "stdout": result.stdout_output,
                "stderr": result.stderr_output, "duration": result.duration_ms, "created_at": result.created_at})
            await session.commit()
        return result

    async def list_executions(self, task_id):
        # Execution reads are intentionally returned with persisted baseline rows.
        async with self.sessionmaker() as session:
            rows = (await session.execute(text("SELECT * FROM test_executions WHERE task_id=:id ORDER BY created_at"),
                                          {"id": task_id})).mappings().all()
            result = []
            for row in rows:
                builds = (await session.execute(text("SELECT * FROM build_results WHERE test_execution_id=:id ORDER BY created_at"),
                                                {"id": row["id"]})).mappings().all()
                result.append(_execution(row, builds))
            return result


def _plan(row, cases):
    return TestPlan(id=row["id"], task_id=row["task_id"], agent_run_id=row["agent_run_id"],
                    plan_summary=row["plan_summary"], created_at=row["created_at"],
                    test_cases=[TestCase(id=c["id"], test_plan_id=c["test_plan_id"],
                        category=TestCaseCategory(c["category"]), title=c["title"], description=c["description"],
                        expected_result=c["expected_result"], test_code=c["test_code"], created_at=c["created_at"]) for c in cases])


def _execution(row, builds):
    report = row["failure_report"]
    if isinstance(report, str):
        report = json.loads(report)
    return TestExecution(id=row["id"], task_id=row["task_id"], agent_run_id=row["agent_run_id"],
        all_passed=row["all_passed"], total_tests=row["total_tests"], passed_tests=row["passed_tests"],
        failed_tests=row["failed_tests"], execution_duration_ms=row["execution_duration_ms"],
        failure_report=report, created_at=row["created_at"],
        baseline_results=[BuildResult(id=b["id"], test_execution_id=b["test_execution_id"],
            check_type=BaselineCheckType(b["check_type"]), status=ExecutionStatus(b["status"]),
            exit_code=b["exit_code"], stdout_output=b["stdout_output"], stderr_output=b["stderr_output"],
            duration_ms=b["duration_ms"], created_at=b["created_at"]) for b in builds])
