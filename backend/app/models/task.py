"""Persistent task, workflow, approval, and audit contracts."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.workflow.states import WorkflowState


class ActorType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"


class TaskRecord(BaseModel):
    id: UUID
    workspace_id: UUID
    conversation_id: UUID
    user_id: UUID
    title: str
    objective: str
    user_prompt: str
    status: WorkflowState = WorkflowState.READY
    version: int = 1
    approved_snapshot_hash: Optional[str] = None
    approved_proposal_id: Optional[UUID] = None
    active_loadout_id: Optional[UUID] = None
    worker_overrides: Dict[str, str] = Field(default_factory=dict)
    active_staging_workspace_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class TransitionRecord(BaseModel):
    id: UUID
    task_id: UUID
    previous_state: WorkflowState
    new_state: WorkflowState
    actor_type: ActorType
    actor_id: Optional[UUID] = None
    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    task_version_before: int
    task_version_after: int


class ApprovalRecord(BaseModel):
    id: UUID
    task_id: UUID
    approval_type: str
    user_id: UUID
    status: str
    feedback: Optional[str] = None
    timestamp: datetime


class AgentRunRecord(BaseModel):
    id: UUID
    task_id: UUID
    agent_role: AgentRole
    loadout_id: Optional[UUID] = None
    worker_id: Optional[str] = None
    provider_id: Optional[str] = None
    model_name: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.QUEUED
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentStateRecord(BaseModel):
    id: UUID
    task_id: UUID
    agent_role: AgentRole
    state_payload: Dict[str, Any]
    checkpoint_seq: int
    created_at: datetime
