"""Codebase Analysis Service orchestrating deterministic analysis steps."""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from backend.app.analysis.types import (
    AnalysisStatus,
    CodebaseAnalysisResult,
    DependencyGraph,
    DetectedTechnology,
    EntryPoint,
    FileSymbols,
    IndexedFile,
    ProjectDependency,
    ProjectSummary,
)
from backend.app.analysis.indexer import FileIndexer
from backend.app.analysis.detector import TechnologyDetector
from backend.app.analysis.dependencies import DependencyParser
from backend.app.analysis.entry_points import EntryPointDetector
from backend.app.analysis.symbols import SymbolExtractor
from backend.app.analysis.graph import DependencyGraphBuilder
from backend.app.analysis.summary import SummaryGenerator
from backend.app.analysis.sanitizer import redact_secrets
from backend.app.services.workspace_service import WorkspaceService
from backend.app.storage import get_storage_backend
from backend.app.storage.base import BaseStorageBackend
from backend.app.analysis.repository import (
    AnalysisRepository,
    InMemoryAnalysisRepository,
    PostgresAnalysisRepository,
)
from backend.app.core.config import get_settings
from backend.app.db.session import get_sessionmaker


class CodebaseAnalysisService:
    """Service orchestrating the complete deterministic codebase intelligence pipeline."""

    def __init__(
        self,
        workspace_service: Optional[WorkspaceService] = None,
        storage: Optional[BaseStorageBackend] = None,
        repository: Optional[AnalysisRepository] = None,
    ):
        self.workspace_service = workspace_service or WorkspaceService()
        self.storage = storage or self.workspace_service.storage
        self.indexer = FileIndexer()
        sessions = get_sessionmaker()
        if repository is not None:
            self.repository = repository
        elif sessions is not None:
            self.repository = PostgresAnalysisRepository(sessions)
        else:
            if get_settings().ENVIRONMENT == "production":
                raise RuntimeError("Production codebase analysis requires PostgreSQL persistence.")
            self.repository = InMemoryAnalysisRepository()

    async def analyze_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
        force: bool = False,
    ) -> CodebaseAnalysisResult:
        """
        Execute full deterministic analysis on the approved workspace.
        Enforces user ownership, checks snapshot hash cache, indexes files,
        detects technologies, parses dependencies, detects entry points, extracts
        symbols, constructs dependency graph, and redacts sensitive tokens.
        """
        # 1. Enforce ownership and retrieve canonical workspace details
        ws = await self.workspace_service.get_workspace(workspace_id, user_id)

        # 2. Check cache / staleness if not forced
        existing = await self.repository.get_latest(workspace_id)
        if (
            existing
            and not force
            and existing.status == AnalysisStatus.COMPLETED
            and existing.source_snapshot_hash == ws.current_snapshot_hash
        ):
            return existing

        started_at = datetime.now(timezone.utc)
        version = (existing.analysis_version + 1) if existing else 1
        canonical_prefix = ws.canonical_root_path

        # 3. Step 1: Deterministic file indexer
        indexed_files = await self.indexer.index_workspace(self.storage, canonical_prefix)

        # 4. Step 2: Technology & framework detector
        technologies = await TechnologyDetector.detect_technologies(
            indexed_files, self.storage, canonical_prefix
        )

        # 5. Step 3: Dependency manifest parser
        dependencies = await DependencyParser.extract_dependencies(
            indexed_files, self.storage, canonical_prefix
        )

        # 6. Step 4: Entry point detector
        entry_points = await EntryPointDetector.detect_entry_points(
            indexed_files, self.storage, canonical_prefix
        )

        # 7. Step 5: Symbol extraction (AST for Python, regex for TS/JS)
        file_symbols: List[FileSymbols] = []
        for f in indexed_files:
            syms = await SymbolExtractor.extract_file_symbols(
                f, self.storage, canonical_prefix
            )
            file_symbols.append(syms)

        # 8. Step 6: Dependency graph construction
        dependency_graph = DependencyGraphBuilder.build_graph(indexed_files, file_symbols)

        # 9. Step 7: Deterministic project summary
        summary = SummaryGenerator.generate_summary(
            indexed_files, technologies, dependencies, entry_points
        )

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        # 10. Step 8: Redact any accidental secrets
        clean_overview = redact_secrets(summary.architecture_overview)
        clean_summary = clean_overview
        clean_warnings = [redact_secrets(w) for w in summary.warnings]

        result = CodebaseAnalysisResult(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            analysis_version=version,
            status=AnalysisStatus.COMPLETED,
            source_snapshot_hash=ws.current_snapshot_hash,
            summary=clean_summary,
            architecture_overview=clean_overview,
            primary_languages=summary.primary_languages,
            frameworks_detected=summary.frameworks,
            technologies=technologies,
            dependencies=dependencies,
            entry_points=entry_points,
            dependency_graph=dependency_graph,
            warnings=clean_warnings,
            indexed_files=indexed_files,
            analysis_duration_ms=duration_ms,
            started_at=started_at,
            completed_at=completed_at,
            created_at=completed_at,
        )

        await self.repository.save(result)
        return result

    async def get_latest_analysis(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> Optional[CodebaseAnalysisResult]:
        """
        Fetch latest analysis result for the workspace.
        Validates ownership and detects whether the analysis is stale compared to
        the workspace's current snapshot hash.
        """
        ws = await self.workspace_service.get_workspace(workspace_id, user_id)
        result = await self.repository.get_latest(workspace_id)
        if not result:
            return None

        # Check if snapshot hash changed
        if ws.current_snapshot_hash != result.source_snapshot_hash:
            stale_copy = result.model_copy(update={"status": AnalysisStatus.STALE})
            return stale_copy

        return result
