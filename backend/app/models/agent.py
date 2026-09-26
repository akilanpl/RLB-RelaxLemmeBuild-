"""Agent domain models, roles, and execution run audit records."""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    TEST_ARCHITECT = "test_architect"
    TEST_EXECUTOR = "test_executor"
    REVIEWER = "reviewer"


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    SUCCESS = "success"
    RETRYABLE_ERROR = "retryable_error"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    NOT_APPLICABLE = "not_applicable"


class AgentRun(BaseModel):
    """
    Immutable audit record for every discrete agent execution invocation.
    Guarantees full worker and fallback provenance.
    """
    id: UUID = Field(..., description="Unique agent execution run identifier")
    task_id: UUID = Field(..., description="Task to which this run belongs")
    agent_role: AgentRole = Field(..., description="Specialized role assigned to this run")
    loadout_id: UUID = Field(..., description="Active loadout configuration identifier")
    worker_id: str = Field(..., description="Worker that generated the final output")
    provider_id: str = Field(..., description="Provider adapter (groq, gemini, openrouter)")
    model_name: str = Field(..., description="Concrete model used (e.g. llama-3.3-70b-versatile)")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    fallback_used: bool = Field(default=False, description="True if a rate-limit failover occurred")
    fallback_reason: Optional[str] = Field(None, description="Reason for failover (e.g. 429 rate limit)")
    initial_worker_id: Optional[str] = Field(None, description="First worker attempted if failover occurred")
    execution_status: ExecutionStatus = Field(default=ExecutionStatus.RUNNING)
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error_message: Optional[str] = None


class AgentState(BaseModel):
    """Serialized working state and memory for an agent in a task."""
    id: UUID
    task_id: UUID
    agent_role: AgentRole
    state_payload: Dict[str, Any]
    checkpoint_seq: int = 1
    created_at: datetime
