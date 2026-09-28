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


TRANSITIONS = {
    WorkflowState.READY: {WorkflowState.FAILED, WorkflowState.ANALYZING, WorkflowState.PLANNING, WorkflowState.CANCELLED},
    WorkflowState.ANALYZING: {WorkflowState.PLANNING, WorkflowState.FAILED},
    WorkflowState.PLANNING: {WorkflowState.PLAN_REVIEW, WorkflowState.FAILED},
    WorkflowState.PLAN_REVIEW: {WorkflowState.STAGING_SETUP, WorkflowState.PLANNING, WorkflowState.CODING, WorkflowState.CANCELLED},
    WorkflowState.STAGING_SETUP: {WorkflowState.CODING, WorkflowState.FAILED},
    WorkflowState.PROMOTING: {WorkflowState.TEST_PLANNING, WorkflowState.FAILED},
    WorkflowState.CODING: {WorkflowState.CODE_REVIEW, WorkflowState.FAILED},
    WorkflowState.CODE_REVIEW: {WorkflowState.PROMOTING, WorkflowState.CODING, WorkflowState.TEST_PLANNING, WorkflowState.CANCELLED},
    WorkflowState.TEST_PLANNING: {WorkflowState.TEST_EXECUTING, WorkflowState.FAILED},
    WorkflowState.TEST_EXECUTING: {WorkflowState.REPAIRING, WorkflowState.REVIEWING, WorkflowState.FAILED},
    WorkflowState.REPAIRING: {WorkflowState.CODING, WorkflowState.FAILED},
    WorkflowState.REVIEWING: {WorkflowState.COMPLETED, WorkflowState.FAILED},
    WorkflowState.COMPLETED: {WorkflowState.READY},
}

# Cancellation is a server-validated terminal operation from any active stage.
for _state in tuple(TRANSITIONS):
    if _state not in {WorkflowState.COMPLETED, WorkflowState.CANCELLED, WorkflowState.FAILED}:
        TRANSITIONS[_state].add(WorkflowState.CANCELLED)
