"""Persistent Codebase Analysis repository with an in-memory test double."""

import json
from datetime import datetime, timezone
from typing import Dict, Optional, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.analysis.types import AnalysisStatus, CodebaseAnalysisResult


class AnalysisRepository(Protocol):
    async def get_latest(self, workspace_id: UUID) -> Optional[CodebaseAnalysisResult]: ...
    async def save(self, analysis: CodebaseAnalysisResult) -> CodebaseAnalysisResult: ...


class InMemoryAnalysisRepository:
    """Test/local repository; production uses PostgresAnalysisRepository."""

    def __init__(self):
        self.items: Dict[UUID, CodebaseAnalysisResult] = {}

    async def get_latest(self, workspace_id: UUID) -> Optional[CodebaseAnalysisResult]:
        return self.items.get(workspace_id)

    async def save(self, analysis: CodebaseAnalysisResult) -> CodebaseAnalysisResult:
        self.items[analysis.workspace_id] = analysis
        return analysis


def _datetime(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class PostgresAnalysisRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    @staticmethod
    def _from_row(row) -> CodebaseAnalysisResult:
        def value(name, default):
            return row[name] if row[name] is not None else default

        return CodebaseAnalysisResult(
            id=row["id"],
            workspace_id=row["workspace_id"],
            analysis_version=row["analysis_version"],
            status=AnalysisStatus(row["status"]),
            source_snapshot_hash=row["source_snapshot_hash"],
            summary=row["summary"],
            architecture_overview=row["architecture_overview"],
            primary_languages=value("primary_languages", []),
            frameworks_detected=value("frameworks_detected", []),
            technologies=value("technologies", []),
            dependencies=value("dependencies", []),
            entry_points=value("entry_points", []),
            dependency_graph=value("dependency_graph", {}),
            warnings=value("warnings", []),
            indexed_files=value("indexed_files", []),
            analysis_duration_ms=row["analysis_duration_ms"],
            started_at=_datetime(row["started_at"]),
            completed_at=_datetime(row["completed_at"]),
            created_at=_datetime(row["created_at"]),
        )

    async def get_latest(self, workspace_id: UUID) -> Optional[CodebaseAnalysisResult]:
        async with self.sessions() as session:
            row = (await session.execute(text("""
                SELECT * FROM codebase_analyses
                WHERE workspace_id = :workspace_id
                ORDER BY analysis_version DESC, created_at DESC
                LIMIT 1
            """), {"workspace_id": workspace_id})).mappings().first()
            return self._from_row(row) if row else None

    async def save(self, analysis: CodebaseAnalysisResult) -> CodebaseAnalysisResult:
        payload = analysis.model_dump(mode="json")
        async with self.sessions.begin() as session:
            await session.execute(text("""
                INSERT INTO codebase_analyses (
                    id, workspace_id, analysis_version, status, source_snapshot_hash,
                    summary, primary_languages, frameworks_detected, technologies,
                    dependencies, entry_points, dependency_graph, warnings,
                    indexed_files, architecture_overview, analysis_duration_ms,
                    started_at, completed_at, created_at
                ) VALUES (
                    :id, :workspace_id, :analysis_version, :status, :source_snapshot_hash,
                    :summary, :primary_languages, :frameworks_detected, :technologies,
                    :dependencies, :entry_points, :dependency_graph, :warnings,
                    :indexed_files, :architecture_overview, :analysis_duration_ms,
                    :started_at, :completed_at, :created_at
                )
            """), {
                "id": analysis.id,
                "workspace_id": analysis.workspace_id,
                "analysis_version": analysis.analysis_version,
                "status": analysis.status.value,
                "source_snapshot_hash": analysis.source_snapshot_hash,
                "summary": analysis.summary,
                "primary_languages": json.dumps(payload["primary_languages"]),
                "frameworks_detected": json.dumps(payload["frameworks_detected"]),
                "technologies": json.dumps(payload["technologies"]),
                "dependencies": json.dumps(payload["dependencies"]),
                "entry_points": json.dumps(payload["entry_points"]),
                "dependency_graph": json.dumps(payload["dependency_graph"]),
                "warnings": json.dumps(payload["warnings"]),
                "indexed_files": json.dumps(payload["indexed_files"]),
                "architecture_overview": analysis.architecture_overview,
                "analysis_duration_ms": analysis.analysis_duration_ms,
                "started_at": analysis.started_at,
                "completed_at": analysis.completed_at,
                "created_at": analysis.created_at,
            })
        return analysis
