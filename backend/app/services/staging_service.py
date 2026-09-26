"""Staging Workspace management service.

Implements isolated ephemeral copies cloned from the canonical Approved Workspace.
Guarantees that staging mutations NEVER leak into or overwrite the Approved Workspace.
"""

import uuid
import posixpath
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID
from backend.app.models.workspace import StagingWorkspace
from backend.app.storage import get_storage_backend
from backend.app.storage.base import BaseStorageBackend
from sqlalchemy import text

from backend.app.db.session import get_sessionmaker
from backend.app.services.workspace_service import WorkspaceService

_MEMORY_STAGING: Dict[UUID, StagingWorkspace] = {}

def _safe_relative_path(relative_path: str) -> str:
    clean = relative_path.replace("\\", "/")
    if clean.startswith("/") or posixpath.isabs(clean):
        raise ValueError("Staging paths must be relative.")
    normalized = posixpath.normpath(clean)
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        raise ValueError("Staging path escapes the workspace.")
    return normalized


class StagingService:
    """Service governing ephemeral Staging Workspace lifecycle."""

    def __init__(
        self, 
        workspace_service: Optional[WorkspaceService] = None,
        storage: Optional[BaseStorageBackend] = None
    ):
        self.workspace_service = workspace_service or WorkspaceService(storage)
        self.storage = storage or get_storage_backend()

    async def create_staging_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
        task_id: Optional[UUID] = None,
    ) -> StagingWorkspace:
        """
        Create an isolated staging workspace cloned from the approved canonical state.
        """
        ws = await self.workspace_service.get_workspace(workspace_id, user_id)

        staging_id = uuid.uuid4()
        staging_prefix = f"workspaces/{workspace_id}/staging/{staging_id}"
        base_hash = ws.current_snapshot_hash or "empty-root"

        # Clone canonical files to staging directory
        await self.storage.copy_directory(ws.canonical_root_path, staging_prefix)

        staging = StagingWorkspace(
            id=staging_id,
            workspace_id=workspace_id,
            task_id=task_id,
            staging_root_path=staging_prefix,
            base_snapshot_hash=base_hash,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            discarded_at=None,
        )

        _MEMORY_STAGING[staging_id] = staging
        await self._persist_staging(staging)
        return staging

    async def get_staging_workspace(
        self, staging_id: UUID, user_id: UUID
    ) -> StagingWorkspace:
        """Fetch staging workspace ensuring user ownership through parent workspace."""
        staging = await self._load_staging(staging_id)
        if not staging or not staging.is_active:
            raise KeyError(f"Staging workspace '{staging_id}' not found or inactive.")

        # Ownership validation
        await self.workspace_service.get_workspace(staging.workspace_id, user_id)
        return staging

    async def list_staging_files(self, staging_id: UUID, user_id: UUID) -> List[str]:
        """List files in the staging workspace."""
        staging = await self.get_staging_workspace(staging_id, user_id)
        all_paths = await self.storage.list_files(staging.staging_root_path)
        # Strip staging prefix for relative path presentation
        prefix = f"{staging.staging_root_path}/"
        rel_paths = [
            p[len(prefix):] if p.startswith(prefix) else p 
            for p in all_paths
        ]
        return rel_paths

    async def read_staging_file(
        self, staging_id: UUID, relative_path: str, user_id: UUID
    ) -> bytes:
        """Read file from isolated staging workspace."""
        staging = await self.get_staging_workspace(staging_id, user_id)
        clean_rel = _safe_relative_path(relative_path)
        storage_p = f"{staging.staging_root_path}/{clean_rel}"
        return await self.storage.read_file(storage_p)

    async def write_staging_file(
        self, staging_id: UUID, relative_path: str, content: bytes, user_id: UUID
    ) -> int:
        """
        Write or modify file strictly within staging workspace.
        Canonical approved workspace is NEVER touched.
        """
        staging = await self.get_staging_workspace(staging_id, user_id)
        clean_rel = _safe_relative_path(relative_path)
        storage_p = f"{staging.staging_root_path}/{clean_rel}"
        return await self.storage.write_file(storage_p, content)

    async def delete_staging_file(
        self, staging_id: UUID, relative_path: str, user_id: UUID
    ) -> bool:
        """Delete file inside staging workspace."""
        staging = await self.get_staging_workspace(staging_id, user_id)
        clean_rel = _safe_relative_path(relative_path)
        storage_p = f"{staging.staging_root_path}/{clean_rel}"
        return await self.storage.delete_file(storage_p)

    async def discard_staging_workspace(
        self, staging_id: UUID, user_id: UUID
    ) -> None:
        """Tear down staging filesystem and mark discarded."""
        staging = await self.get_staging_workspace(staging_id, user_id)
        staging.is_active = False
        staging.discarded_at = datetime.now(timezone.utc)
        _MEMORY_STAGING[staging_id] = staging
        await self._persist_staging(staging)
        await self.storage.delete_directory(staging.staging_root_path)

    async def _persist_staging(self, staging: StagingWorkspace) -> None:
        sessions = get_sessionmaker()
        if sessions is None:
            return
        async with sessions.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO staging_workspaces (
                        id, workspace_id, task_id, staging_root_path, base_snapshot_hash,
                        is_active, created_at, discarded_at
                    ) VALUES (
                        :id, :workspace_id, :task_id, :staging_root_path, :base_snapshot_hash,
                        :is_active, :created_at, :discarded_at
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        is_active = EXCLUDED.is_active,
                        discarded_at = EXCLUDED.discarded_at
                    """
                ),
                {
                    "id": staging.id,
                    "workspace_id": staging.workspace_id,
                    "task_id": staging.task_id,
                    "staging_root_path": staging.staging_root_path,
                    "base_snapshot_hash": staging.base_snapshot_hash,
                    "is_active": staging.is_active,
                    "created_at": staging.created_at,
                    "discarded_at": staging.discarded_at,
                },
            )

    async def _load_staging(self, staging_id: UUID) -> Optional[StagingWorkspace]:
        cached = _MEMORY_STAGING.get(staging_id)
        if cached is not None:
            return cached
        sessions = get_sessionmaker()
        if sessions is None:
            return None
        async with sessions() as session:
            row = (
                await session.execute(
                    text("SELECT * FROM staging_workspaces WHERE id=:id"),
                    {"id": staging_id},
                )
            ).mappings().first()
        if row is None:
            return None
        created_at = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        discarded_at = row["discarded_at"]
        if discarded_at is not None and discarded_at.tzinfo is None:
            discarded_at = discarded_at.replace(tzinfo=timezone.utc)
        staging = StagingWorkspace(
            id=row["id"],
            workspace_id=row["workspace_id"],
            task_id=row["task_id"],
            staging_root_path=row["staging_root_path"],
            base_snapshot_hash=row["base_snapshot_hash"],
            is_active=row["is_active"],
            created_at=created_at,
            discarded_at=discarded_at,
        )
        _MEMORY_STAGING[staging.id] = staging
        return staging
