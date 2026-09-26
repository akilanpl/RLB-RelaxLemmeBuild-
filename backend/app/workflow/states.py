"""Workflow states, events, and deterministic transition definitions."""

from enum import Enum
from typing import Dict, Set


class WorkflowState(str, Enum):
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
    REPAIRING = "repairing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class WorkflowEvent(str, Enum):
    IMPORT_REPO = "import_repo"
    ANALYSIS_COMPLETE = "analysis_complete"
    START_TASK = "start_task"
    PLAN_GENERATED = "plan_generated"
    PLAN_APPROVED = "plan_approved"
    PLAN_REVISION_REQUESTED = "plan_revision_requested"
    PLAN_REJECTED = "plan_rejected"
    STAGING_READY = "staging_ready"
    DIFF_PROPOSED = "diff_proposed"
    CODE_APPROVED = "code_approved"
    CODE_REVISION_REQUESTED = "code_revision_requested"
    CODE_REJECTED = "code_rejected"
    STAGING_CLEARED = "staging_cleared"
    PATCH_PROMOTED = "patch_promoted"
    TEST_PLAN_GENERATED = "test_plan_generated"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    REVIEW_SUBMITTED = "review_submitted"
    RESET = "reset"


# Allowed state transitions matrix
VALID_TRANSITIONS: Dict[WorkflowState, Dict[WorkflowEvent, WorkflowState]] = {
    WorkflowState.IDLE: {
        WorkflowEvent.IMPORT_REPO: WorkflowState.ANALYZING,
    },
    WorkflowState.ANALYZING: {
        WorkflowEvent.ANALYSIS_COMPLETE: WorkflowState.READY,
    },
    WorkflowState.READY: {
        WorkflowEvent.START_TASK: WorkflowState.PLANNING,
    },
    WorkflowState.PLANNING: {
        WorkflowEvent.PLAN_GENERATED: WorkflowState.PLAN_REVIEW,
    },
    WorkflowState.PLAN_REVIEW: {
        WorkflowEvent.PLAN_APPROVED: WorkflowState.STAGING_SETUP,
        WorkflowEvent.PLAN_REVISION_REQUESTED: WorkflowState.PLANNING,
        WorkflowEvent.PLAN_REJECTED: WorkflowState.CANCELLED,
    },
    WorkflowState.STAGING_SETUP: {
        WorkflowEvent.STAGING_READY: WorkflowState.CODING,
    },
    WorkflowState.CODING: {
        WorkflowEvent.DIFF_PROPOSED: WorkflowState.CODE_REVIEW,
    },
    WorkflowState.CODE_REVIEW: {
        WorkflowEvent.CODE_APPROVED: WorkflowState.PROMOTING,
        WorkflowEvent.CODE_REVISION_REQUESTED: WorkflowState.CODING,
        WorkflowEvent.CODE_REJECTED: WorkflowState.STAGING_CLEANUP,
    },
    WorkflowState.STAGING_CLEANUP: {
        WorkflowEvent.STAGING_CLEARED: WorkflowState.READY,
    },
    WorkflowState.PROMOTING: {
        WorkflowEvent.PATCH_PROMOTED: WorkflowState.TEST_PLANNING,
    },
    WorkflowState.TEST_PLANNING: {
        WorkflowEvent.TEST_PLAN_GENERATED: WorkflowState.TEST_EXECUTING,
    },
    WorkflowState.TEST_EXECUTING: {
        WorkflowEvent.TESTS_PASSED: WorkflowState.REVIEWING,
        WorkflowEvent.TESTS_FAILED: WorkflowState.CODING,  # Automated failure loopback to Coder
    },
    WorkflowState.REVIEWING: {
        WorkflowEvent.REVIEW_SUBMITTED: WorkflowState.COMPLETED,
    },
    WorkflowState.COMPLETED: {
        WorkflowEvent.RESET: WorkflowState.READY,
    },
    WorkflowState.CANCELLED: {
        WorkflowEvent.RESET: WorkflowState.READY,
    },
}
