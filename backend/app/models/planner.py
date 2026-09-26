"""Structured Planner output and bounded context contracts."""

from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ImplementationStep(BaseModel):
    order: int = Field(ge=1)
    description: str
    rationale: str
    candidate_files: List[str] = []


class ImplementationPlan(BaseModel):
    objective: str
    understanding: str
    implementation_steps: List[ImplementationStep] = Field(min_length=1)
    affected_files: List[str] = []
    dependencies: List[str] = []
    risks: List[str] = []
    assumptions: List[str] = []
    expected_behavior: str
    unresolved_questions: List[str] = []


class PersistedPlan(BaseModel):
    id: UUID
    task_id: UUID
    agent_run_id: UUID
    revision_number: int
    plan: ImplementationPlan
    source_snapshot_hash: Optional[str] = None
    status: str = "pending_review"
    created_at: str
