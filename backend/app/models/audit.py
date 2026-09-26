"""Audit trails, reviewer reports, and version snapshots."""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel


class ReviewRecommendation(str, Enum):
    READY_TO_MERGE = "ready_to_merge"
    REQUIRES_FOLLOWUP = "requires_followup"


class ReviewerReport(BaseModel):
    """
    Immutable structured report generated exclusively by the Reviewer agent.
    Reviewer has strict read-only access.
    """
    id: UUID
    task_id: UUID
    agent_run_id: UUID
    summary: str
    strengths: List[str]
    concerns: List[str]
    security_audit: str
    recommendation: ReviewRecommendation
    task_understanding: str = ""
    implementation_summary: str = ""
    changed_files: List[Dict[str, Any]] = []
    requirements_coverage: List[Dict[str, Any]] = []
    behavior_verified: List[str] = []
    tests_summary: List[Dict[str, Any]] = []
    test_failures: List[Dict[str, Any]] = []
    repair_summary: List[str] = []
    remaining_risks: List[str] = []
    unresolved_items: List[str] = []
    evidence: List[Dict[str, Any]] = []
    final_status: str = "COMPLETED_WITH_LIMITATIONS"
    created_at: datetime


class ExecutionLog(BaseModel):
    id: UUID
    agent_run_id: Optional[UUID] = None
    task_id: UUID
    source: str  # 'sandbox', 'agent', 'system'
    stream: str  # 'stdout', 'stderr', 'event'
    log_line: str
    logged_at: datetime


class GitSnapshot(BaseModel):
    """Immutable checkpoint recorded upon approval and patch promotion."""
    id: UUID
    workspace_id: UUID
    task_id: Optional[UUID] = None
    commit_sha: str
    tree_sha: str
    parent_commit_sha: Optional[str] = None
    message: str
    created_at: datetime
