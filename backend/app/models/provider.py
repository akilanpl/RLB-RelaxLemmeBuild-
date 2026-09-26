"""Provider, Worker, Loadout, and Credentials models."""

from datetime import datetime
from typing import Optional, List, Dict
from uuid import UUID
from pydantic import BaseModel, Field
from backend.app.models.agent import AgentRole


class Provider(BaseModel):
    id: str = Field(..., description="Provider identifier, e.g. groq, gemini, openrouter")
    name: str
    base_url: str
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    is_active: bool = True
    created_at: datetime


class Credential(BaseModel):
    id: UUID
    user_id: UUID
    provider_id: str
    key_fingerprint: str = Field(..., description="Masked/hashed display key, e.g. 'gsk_...3a9f'")
    created_at: datetime
    updated_at: datetime


class Worker(BaseModel):
    """
    A concrete model worker instance.
    Represents a specific configured model/API combination.
    """
    id: str = Field(..., description="Worker identifier, e.g. 'worker-groq-llama-70b'")
    provider_id: str
    model_name: str
    context_window_tokens: int
    max_output_tokens: int
    temperature: float = 0.2
    rate_limit_rpm: Optional[int] = None
    rate_limit_tpm: Optional[int] = None
    created_at: datetime


class AgentWorkerMapping(BaseModel):
    """Worker assignment for a single agent role, including fallback chain."""
    primary_worker_id: str
    fallback_worker_ids: List[str] = []


class Loadout(BaseModel):
    """
    A named configuration mapping agent roles to workers.
    Changing loadout does NOT mutate or destroy historical task data.
    """
    id: UUID
    user_id: Optional[UUID] = None  # None for global system presets
    name: str
    description: Optional[str] = None
    is_system_preset: bool = False
    mappings: Dict[AgentRole, AgentWorkerMapping]
    created_at: datetime
    updated_at: datetime


class TemporaryOverride(BaseModel):
    """
    Temporary per-task worker override.
    Overrides the worker assignment for a single task without mutating the loadout.
    """
    task_id: UUID
    agent_role: AgentRole
    target_worker_id: str
    reason: Optional[str] = None
