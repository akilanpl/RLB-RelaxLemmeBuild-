"""Workspace domain models and schema definitions."""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


class EnvironmentMode(str, Enum):
    SANDBOXED = "sandboxed"
    CONNECTED = "connected"


class WorkspaceStatus(str, Enum):
    PROVISIONING = "provisioning"
    READY = "ready"
    IMPORT_FAILED = "import_failed"
    ARCHIVED = "archived"


class WorkspaceBase(BaseModel):
    name: str = Field(..., description="Human-readable project workspace name")
    slug: str = Field(..., description="URL-safe workspace identifier")
    description: Optional[str] = Field(None, description="Optional project description")
    environment_mode: EnvironmentMode = Field(
        default=EnvironmentMode.SANDBOXED, 
        description="Isolation mode for workspace code execution"
    )
    status: WorkspaceStatus = Field(
        default=WorkspaceStatus.READY,
        description="Current workspace status"
    )
    canonical_root_path: str = Field(
        default="project-root/canonical", 
        description="Persistent path for approved project files"
    )
    file_count: int = Field(default=0, description="Total number of files tracked")
    total_size_bytes: int = Field(default=0, description="Total size in bytes")
    current_snapshot_hash: Optional[str] = Field(None, description="Current git snapshot SHA or hash")
    git_remote_url: Optional[str] = Field(None, description="Optional upstream repository remote")


class Workspace(WorkspaceBase):
    id: UUID
    user_id: UUID
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime


class StagingWorkspace(BaseModel):
    """
    Isolated snapshot/copy of the approved workspace.
    The Coder is permitted to edit files exclusively within this boundary.
    """
    id: UUID
    workspace_id: UUID
    task_id: Optional[UUID] = None
    staging_root_path: str = Field(
        ..., 
        description="Isolated ephemeral filesystem directory for pending code proposals"
    )
    base_snapshot_hash: str = Field(
        ..., 
        description="Git tree/commit hash from which this staging snapshot was cloned"
    )
    is_active: bool = True
    created_at: datetime
    discarded_at: Optional[datetime] = None



class WorkspaceSettings(BaseModel):
    workspace_id: UUID
    active_loadout_id: UUID
    sandbox_cpu_limit: float = 2.0
    sandbox_memory_limit_mb: int = 4096
    sandbox_timeout_seconds: int = 600
    auto_analyze_on_import: bool = True
    created_at: datetime
    updated_at: datetime


class FileRecord(BaseModel):
    id: UUID
    workspace_id: UUID
    relative_path: str
    file_type: str  # 'file' or 'directory'
    size_bytes: int
    sha256_hash: str
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class FileMetadata(BaseModel):
    file_id: UUID
    language: Optional[str] = None
    ast_summary: Optional[Dict[str, Any]] = None
    imports: Optional[List[str]] = None
    exports: Optional[List[str]] = None
    line_count: int = 0
    is_test_file: bool = False
    updated_at: datetime


class CodebaseAnalysis(BaseModel):
    id: UUID
    workspace_id: UUID
    summary: str
    primary_languages: List[str]
    frameworks_detected: List[str]
    dependency_graph: Dict[str, List[str]]
    architecture_overview: str
    analysis_duration_ms: int
    created_at: datetime
