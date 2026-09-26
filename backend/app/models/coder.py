"""Structured contracts produced and consumed by the Coder vertical slice."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChangeOperation(str, Enum):
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


class CodeChange(BaseModel):
    path: str = Field(min_length=1)
    operation: ChangeOperation
    content: Optional[str] = None
    rationale: str = ""


class CodeImpact(BaseModel):
    affected_files: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    tests: List[str] = Field(default_factory=list)


class CodeChangeSet(BaseModel):
    """Provider-independent, deterministic description of a proposed patch."""

    summary: str
    commit_message: str = "Apply coder changes"
    changes: List[CodeChange] = Field(default_factory=list)
    impact: CodeImpact = Field(default_factory=CodeImpact)


class CoderContext(BaseModel):
    task_id: UUID
    objective: str
    snapshot_hash: Optional[str]
    files: List[dict] = Field(default_factory=list)


class StoredCodeChangeSet(BaseModel):
    id: UUID
    task_id: UUID
    staging_workspace_id: UUID
    source_snapshot_hash: str
    change_set: CodeChangeSet
    proposal_id: UUID
    created_at: datetime
