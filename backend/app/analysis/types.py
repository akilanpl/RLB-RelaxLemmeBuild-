"""Types and schemas for deterministic Codebase Intelligence."""

from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"


class IndexedFile(BaseModel):
    relative_path: str
    extension: str
    language: str
    size_bytes: int
    line_count: int
    sha256_hash: str
    is_binary: bool = False
    is_test_file: bool = False


class DetectedTechnology(BaseModel):
    name: str
    category: str  # 'language', 'framework', 'build_tool', 'library'
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: List[str] = []


class ProjectDependency(BaseModel):
    name: str
    version_spec: Optional[str] = None
    dependency_type: str  # 'production' | 'development'
    manifest_source: str


class EntryPoint(BaseModel):
    path: str
    entry_type: str  # 'nextjs_app_router', 'nextjs_pages_router', 'python_module', 'web_root'
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: List[str] = []


class SymbolInfo(BaseModel):
    name: str
    kind: str  # 'function', 'class', 'interface', 'type', 'variable'
    line_number: int
    is_exported: bool = False


class FileSymbols(BaseModel):
    relative_path: str
    symbols: List[SymbolInfo] = []
    imports: List[str] = []
    exports: List[str] = []
    symbols_available: bool = True


class DependencyGraphNode(BaseModel):
    id: str  # file path or package name
    node_type: str  # 'file' | 'package'


class DependencyGraphEdge(BaseModel):
    source: str
    target: str
    edge_type: str  # 'internal_import' | 'external_dependency'


class DependencyGraph(BaseModel):
    nodes: List[DependencyGraphNode] = []
    edges: List[DependencyGraphEdge] = []


class ProjectSummary(BaseModel):
    total_files: int
    total_size_bytes: int
    total_lines: int
    primary_languages: List[str] = []
    frameworks: List[str] = []
    dependency_counts: Dict[str, int] = {}
    likely_entry_points: List[str] = []
    top_level_directories: List[str] = []
    config_files: List[str] = []
    warnings: List[str] = []
    unsupported_areas: List[str] = []
    architecture_overview: str


class CodebaseAnalysisResult(BaseModel):
    id: UUID
    workspace_id: UUID
    analysis_version: int = 1
    status: AnalysisStatus = AnalysisStatus.COMPLETED
    source_snapshot_hash: Optional[str] = None
    summary: str
    architecture_overview: str
    primary_languages: List[str] = []
    frameworks_detected: List[str] = []
    technologies: List[DetectedTechnology] = []
    dependencies: List[ProjectDependency] = []
    entry_points: List[EntryPoint] = []
    dependency_graph: DependencyGraph
    warnings: List[str] = []
    indexed_files: List[IndexedFile] = []
    analysis_duration_ms: int = 0
    started_at: datetime
    completed_at: Optional[datetime] = None
    created_at: datetime
