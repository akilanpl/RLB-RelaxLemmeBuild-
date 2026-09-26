"""Testing domain models, test specs, execution results, and failure reports."""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field
from backend.app.models.agent import ExecutionStatus


class BaselineCheckType(str, Enum):
    DEPENDENCY_INSTALL = "dependency_install"
    TYPE_CHECK = "type_check"
    LINT = "lint"
    PRODUCTION_BUILD = "production_build"
    UNIT_INTEGRATION_TESTS = "unit_integration_tests"
    HEALTH_CHECK = "health_check"


class TestCaseCategory(str, Enum):
    FUNCTIONAL = "functional"
    REGRESSION = "regression"
    EDGE_CASE = "edge_case"
    SECURITY = "security"


class TestCase(BaseModel):
    id: UUID
    test_plan_id: UUID
    category: TestCaseCategory
    title: str
    description: str
    expected_result: str
    test_code: str
    created_at: datetime


class TestPlan(BaseModel):
    id: UUID
    task_id: UUID
    agent_run_id: UUID
    plan_summary: str
    test_cases: List[TestCase] = Field(default_factory=list)
    created_at: datetime


class BuildResult(BaseModel):
    """
    Result of an individual mandatory baseline verification step.
    Mandatory baseline checks must execute before Test Architect tests.
    """
    id: UUID
    test_execution_id: UUID
    check_type: BaselineCheckType
    status: ExecutionStatus
    exit_code: int
    stdout_output: Optional[str] = None
    stderr_output: Optional[str] = None
    duration_ms: int
    created_at: datetime


class FailedCheckDetail(BaseModel):
    check_name: str
    error_summary: str
    exit_code: int
    traceback_or_logs: str


class FailureReport(BaseModel):
    """
    Structured failure report produced by Test Executor when baseline or
    tests fail. Routes back to Coder to guide automated correction.
    """
    summary: str
    failed_baseline_checks: List[FailedCheckDetail] = []
    failed_test_cases: List[FailedCheckDetail] = []
    remediation_suggestions: List[str] = []


class TestExecution(BaseModel):
    id: UUID
    task_id: UUID
    agent_run_id: UUID
    all_passed: bool = False
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    execution_duration_ms: int = 0
    baseline_results: List[BuildResult] = Field(default_factory=list)
    failure_report: Optional[FailureReport] = None
    created_at: datetime
