"""Workflow state machine, tasks, approvals, and diff proposals."""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    READY = "ready"
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    STAGING_SETUP = "staging_setup"
    CODING = "coding"
    CODE_REVIEW = "code_review"
    STAGING_CLEANUP = "staging_cleanup"
    PROMOTING = "promoting"
    TEST_PLANNING = "test_planning"
    TEST_EXECUTING = "test_executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class ApprovalGateType(str, Enum):
    PLAN_APPROVAL = "plan_approval"
    CODE_APPROVAL = "code_approval"


class Task(BaseModel):
    id: UUID
    workspace_id: UUID
    conversation_id: UUID
    user_prompt: str
    status: TaskStatus = TaskStatus.IDLE
    active_loadout_id: UUID
    worker_overrides: Optional[Dict[str, str]] = Field(
        None, 
        description="Optional temporary worker overrides for this task"
    )
    active_staging_workspace_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None
    objective: Optional[str] = None
    user_id: Optional[UUID] = None
    version: int = 1
    approved_snapshot_hash: Optional[str] = None


class PlanStep(BaseModel):
    step_number: int
    title: str
    description: str
    target_files: List[str]


class Plan(BaseModel):
    id: UUID
    task_id: UUID
    agent_run_id: UUID
    title: str
    summary: str
    steps: List[PlanStep]
    affected_files: List[str]
    risk_assessment: Optional[str] = None
    revision_number: int = 1
    created_at: datetime


class Approval(BaseModel):
    id: UUID
    task_id: UUID
    gate_type: ApprovalGateType
    status: ApprovalStatus = ApprovalStatus.PENDING
    user_feedback: Optional[str] = None
    reviewed_by: UUID
    created_at: datetime
    resolved_at: Optional[datetime] = None


class DiffType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class Diff(BaseModel):
    id: UUID
    code_proposal_id: UUID
    file_path: str
    diff_type: DiffType
    unified_diff: str
    additions_count: int = 0
    deletions_count: int = 0
    created_at: datetime
    before_content: str = ""
    after_content: str = ""


class CodeProposal(BaseModel):
    id: UUID
    task_id: UUID
    agent_run_id: UUID
    staging_workspace_id: UUID
    summary: str
    commit_message: str
    diffs: List[Diff] = []
    revision_number: int = 1
    base_snapshot_hash: Optional[str] = None
    status: str = "ready_for_review"
    impact: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    created_at: datetime
