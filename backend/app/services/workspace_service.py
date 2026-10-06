"""Approved Workspace management service.

Handles workspace provisioning, canonical storage isolation, file tracking,
and read-only inspection conforming to Phase 0 contracts.
"""

import asyncio
import re
import uuid
import os
import hashlib
import json
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID
from pydantic import BaseModel
from backend.app.models.workspace import (
    Workspace,
    WorkspaceStatus,
    EnvironmentMode,
    FileRecord,
    FileMetadata,
)
from backend.app.storage import get_storage_backend
from backend.app.storage.base import BaseStorageBackend
from backend.app.services.zip_import import ZipImportService, ZipValidationError
from backend.app.db.session import get_sessionmaker
from sqlalchemy import text


class WorkspaceAccessDeniedError(PermissionError):
    """Raised when a user attempts to access a workspace they do not own."""
    pass


class WorkspaceNotFoundError(KeyError):
    """Raised when the requested workspace does not exist."""
    pass


# Global thread-safe in-process workspace catalog for local storage persistence
# When database connection is active, queries sync with PostgreSQL; otherwise cached here.
_MEMORY_WORKSPACES: Dict[UUID, Workspace] = {}
_MEMORY_FILES: Dict[UUID, List[Dict[str, Any]]] = {}


def generate_slug(name: str) -> str:
    """Generate a clean URL-safe slug from a workspace name."""
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "-", s) or "workspace"


def _row_to_workspace(row: Any) -> Workspace:
    return Workspace(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        slug=row["slug"],
        description=row.get("description"),
        environment_mode=EnvironmentMode(row["environment_mode"]),
        status=WorkspaceStatus(row["status"]),
        canonical_root_path=row["canonical_root_path"],
        file_count=int(row["file_count"] or 0),
        total_size_bytes=int(row["total_size_bytes"] or 0),
        current_snapshot_hash=row.get("current_snapshot_hash"),
        git_remote_url=row.get("git_remote_url"),
        is_archived=bool(row.get("is_archived")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class WorkspaceService:
    """Service governing canonical Approved Workspace lifecycle."""

    def __init__(
        self,
        storage: Optional[BaseStorageBackend] = None,
        local_registry_path: Optional[str | Path] = None,
    ):
        self.storage = storage or get_storage_backend()
        if local_registry_path is None:
            from backend.app.core.config import get_settings
            local_registry_path = Path(get_settings().LOCAL_DATA_DIR) / "rlb.sqlite3"
        self.local_registry_path = Path(local_registry_path)

    def _open_local_registry(self):
        self.local_registry_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.local_registry_path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS local_workspace_registry (
                workspace_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                workspace_json TEXT NOT NULL,
                files_json TEXT NOT NULL
            )
            """
        )
        return connection

    def _persist_local_registration(
        self, workspace: Workspace, file_records: List[Dict[str, Any]]
    ) -> None:
        if not workspace.local_path:
            return
        with closing(self._open_local_registry()) as connection, connection:
            connection.execute(
                """
                INSERT INTO local_workspace_registry
                    (workspace_id, user_id, workspace_json, files_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    workspace_json=excluded.workspace_json,
                    files_json=excluded.files_json
                """,
                (
                    str(workspace.id),
                    str(workspace.user_id),
                    workspace.model_dump_json(),
                    json.dumps(file_records, separators=(",", ":")),
                ),
            )

    def _load_local_registrations(self, user_id: Optional[UUID] = None) -> None:
        if not self.local_registry_path.is_file():
            return
        try:
            with closing(sqlite3.connect(self.local_registry_path)) as connection:
                rows = connection.execute(
                    """
                    SELECT workspace_json, files_json FROM local_workspace_registry
                    WHERE (? IS NULL OR user_id = ?)
                    """,
                    (str(user_id) if user_id else None, str(user_id) if user_id else None),
                ).fetchall()
            for workspace_json, files_json in rows:
                try:
                    workspace = Workspace.model_validate_json(workspace_json)
                    files = json.loads(files_json)
                except (ValueError, TypeError):
                    continue
                _MEMORY_WORKSPACES[workspace.id] = workspace
                _MEMORY_FILES[workspace.id] = files
        except (sqlite3.Error, OSError):
            # The task/queue database may predate workspace registration.
            return

    @staticmethod
    def _scan_local_project(root: Path) -> List[Dict[str, Any]]:
        """Read a bounded project snapshot without following symlinks."""
        from backend.app.services.zip_import import ZipImportService

        ignored = {
            ".git", "node_modules", ".venv", "venv", "__pycache__", ".next",
            "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        }
        entries: List[Dict[str, Any]] = []
        total = 0
        def raise_walk_error(error: OSError) -> None:
            raise ZipValidationError("The selected local folder contains an unreadable directory.") from error

        for current, directories, filenames in os.walk(
            root, followlinks=False, onerror=raise_walk_error
        ):
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if name not in ignored and not WorkspaceService._is_directory_link(current_path / name)
            ]
            for filename in filenames:
                source = current_path / filename
                if (
                    source.is_symlink()
                    or filename == ".DS_Store"
                    or (filename.startswith(".") and ".rlb-" in filename)
                ):
                    continue
                try:
                    resolved = source.resolve(strict=True)
                    if os.path.commonpath((str(root), str(resolved))) != str(root):
                        continue
                    if not resolved.is_file():
                        continue
                    size = resolved.stat().st_size
                    if size > ZipImportService.MAX_UNCOMPRESSED_BYTES:
                        raise ZipValidationError("A local project file exceeds the 100 MB import limit.")
                    relative = WorkspaceService._normalize_import_path(
                        resolved.relative_to(root).as_posix()
                    )
                    content = resolved.read_bytes()
                except ValueError:
                    continue
                except OSError as exc:
                    raise ZipValidationError("The selected local folder contains an unreadable file.") from exc
                total += len(content)
                if total > ZipImportService.MAX_UNCOMPRESSED_BYTES:
                    raise ZipValidationError("Local project exceeds the 100 MB import limit.")
                entries.append({
                    "relative_path": relative,
                    "content": content,
                })
                if len(entries) > ZipImportService.MAX_FILE_COUNT:
                    raise ZipValidationError("Local project exceeds the 5,000 file limit.")
        return entries

    @staticmethod
    def _is_directory_link(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())

    @staticmethod
    def _snapshot_hash(entries: List[Dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for item in sorted(entries, key=lambda entry: entry["relative_path"]):
            digest.update(item["relative_path"].encode())
            digest.update(b"\0")
            digest.update(item["content"])
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _safe_local_path(root: Path, relative_path: str) -> Path:
        clean = WorkspaceService._normalize_import_path(relative_path)
        candidate = root
        for component in Path(clean).parts:
            candidate = candidate / component
            if candidate.is_symlink():
                raise ValueError("A local project path now contains a symbolic link.")
            if os.path.commonpath((str(root), str(candidate.resolve(strict=False)))) != str(root):
                raise ValueError("A local project path escapes the selected folder.")
        return candidate

    async def _publish_local_snapshot(
        self,
        workspace: Workspace,
        file_contents: Dict[str, bytes],
        previous_records: List[Dict[str, Any]],
    ) -> None:
        """Write an approved canonical snapshot back to its registered project."""
        if not workspace.local_path:
            return
        root = Path(workspace.local_path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("The registered local project folder is unavailable.")
        current_entries = await asyncio.to_thread(self._scan_local_project, root)
        if (
            workspace.current_snapshot_hash
            and self._snapshot_hash(current_entries) != workspace.current_snapshot_hash
        ):
            raise ValueError("The local project changed after this task started; refresh and retry.")
        await asyncio.to_thread(
            self._write_local_snapshot_files, root, file_contents, previous_records
        )

    @staticmethod
    def _write_local_snapshot_files(
        root: Path,
        file_contents: Dict[str, bytes],
        previous_records: List[Dict[str, Any]],
    ) -> None:
        for relative, content in file_contents.items():
            destination = WorkspaceService._safe_local_path(root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination = WorkspaceService._safe_local_path(root, relative)
            if not destination.exists() or destination.read_bytes() != content:
                temporary = destination.with_name(f".{destination.name}.rlb-{uuid.uuid4().hex}")
                try:
                    temporary.write_bytes(content)
                    os.replace(temporary, destination)
                finally:
                    if temporary.exists():
                        temporary.unlink()

        retained = set(file_contents)
        for record in previous_records:
            relative = record.get("relative_path")
            if not relative or relative in retained:
                continue
            destination = WorkspaceService._safe_local_path(root, str(relative))
            if destination.is_file():
                destination.unlink()

    @staticmethod
    def _local_git_metadata(root: Path) -> Dict[str, Optional[str]]:
        def run(*args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, timeout=4, check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""

        try:
            branch = run("rev-parse", "--abbrev-ref", "HEAD")
            if not branch:
                return {"git_remote_url": None, "git_branch": None, "git_status": None}
            remote = run("remote", "get-url", "origin") or None
            if remote and remote.startswith(("http://", "https://")):
                try:
                    parsed = urlsplit(remote)
                    hostname = parsed.hostname
                    port = parsed.port
                except ValueError:
                    remote = None
                else:
                    if not hostname:
                        remote = None
                    else:
                        hostname = f"[{hostname}]" if ":" in hostname else hostname
                        netloc = f"{hostname}:{port}" if port else hostname
                        remote = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
            changes = run("status", "--porcelain")
            status = "clean" if not changes else f"{len(changes.splitlines())} uncommitted change(s)"
            return {
                "git_remote_url": remote,
                "git_branch": branch,
                "git_status": status,
            }
        except (OSError, subprocess.SubprocessError):
            return {"git_remote_url": None, "git_branch": None, "git_status": None}

    async def register_local_workspace(
        self,
        user_id: UUID,
        name: str,
        local_path: str,
        description: Optional[str] = None,
    ) -> Workspace:
        """Register a selected local project and persist a safe snapshot and its path."""
        if not name.strip():
            raise ValueError("Workspace name is required.")
        try:
            root = Path(local_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("The selected local folder is unavailable.") from exc
        if not root.is_dir():
            raise ValueError("The selected local path must be a directory.")
        self._load_local_registrations(user_id)
        existing = next(
            (
                workspace for workspace in _MEMORY_WORKSPACES.values()
                if workspace.user_id == user_id and workspace.local_path == str(root)
            ),
            None,
        )
        if existing is not None:
            return await self.refresh_local_workspace(existing.id, user_id)
        entries = await asyncio.to_thread(self._scan_local_project, root)
        metadata = await asyncio.to_thread(self._local_git_metadata, root)
        workspace = await self.create_workspace(user_id=user_id, name=name, description=description)
        snapshot_root = f"workspaces/{workspace.id}/snapshots/{uuid.uuid4()}"
        file_records: List[Dict[str, Any]] = []
        try:
            for item in sorted(entries, key=lambda entry: entry["relative_path"]):
                content = item["content"]
                relative = item["relative_path"]
                await self.storage.write_file(f"{snapshot_root}/{relative}", content)
                file_hash = hashlib.sha256(content).hexdigest()
                file_records.append({
                    "id": str(uuid.uuid4()),
                    "workspace_id": str(workspace.id),
                    "relative_path": relative,
                    "file_type": "file",
                    "size_bytes": len(content),
                    "sha256_hash": file_hash,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            workspace = workspace.model_copy(update={
                "canonical_root_path": snapshot_root,
                "file_count": len(file_records),
                "total_size_bytes": sum(item["size_bytes"] for item in file_records),
                "current_snapshot_hash": self._snapshot_hash(entries),
                "local_path": str(root),
                **metadata,
                "updated_at": datetime.now(timezone.utc),
            })
            _MEMORY_WORKSPACES[workspace.id] = workspace
            _MEMORY_FILES[workspace.id] = file_records
            await self._persist_workspace(workspace, file_records)
            self._persist_local_registration(workspace, file_records)
        except BaseException:
            await self.storage.delete_directory(snapshot_root)
            await self.storage.delete_directory(f"workspaces/{workspace.id}/canonical")
            _MEMORY_WORKSPACES.pop(workspace.id, None)
            _MEMORY_FILES.pop(workspace.id, None)
            raise
        return workspace

    async def refresh_local_workspace(self, workspace_id: UUID, user_id: UUID) -> Workspace:
        """Refresh a registered folder snapshot before a task is created."""
        workspace = await self.get_workspace(workspace_id, user_id)
        if not workspace.local_path:
            return workspace
        root = Path(workspace.local_path).resolve(strict=True)
        entries = await asyncio.to_thread(self._scan_local_project, root)
        metadata = await asyncio.to_thread(self._local_git_metadata, root)
        # Publish a new immutable storage snapshot without routing through the
        # empty-workspace import contract.
        extracted = []
        for item in entries:
            content = item["content"]
            extracted.append({
                **item,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            })
        root_prefix = f"workspaces/{workspace.id}/snapshots/{uuid.uuid4()}"
        file_records: List[Dict[str, Any]] = []
        for item in extracted:
            await self.storage.write_file(
                f"{root_prefix}/{item['relative_path']}", item["content"]
            )
            file_records.append({
                "id": str(uuid.uuid4()),
                "workspace_id": str(workspace.id),
                "relative_path": item["relative_path"],
                "file_type": "file",
                "size_bytes": item["size_bytes"],
                "sha256_hash": item["sha256"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        updated = workspace.model_copy(update={
            "canonical_root_path": root_prefix,
            "file_count": len(file_records),
            "total_size_bytes": sum(item["size_bytes"] for item in extracted),
            "current_snapshot_hash": self._snapshot_hash(extracted),
            **metadata,
            "updated_at": datetime.now(timezone.utc),
        })
        _MEMORY_WORKSPACES[workspace.id] = updated
        _MEMORY_FILES[workspace.id] = file_records
        await self._persist_workspace(updated, file_records)
        self._persist_local_registration(updated, file_records)
        return updated

    async def _persist_workspace(self, workspace: Workspace, file_records: List[Dict[str, Any]]) -> None:
        """Best-effort Postgres sync so tasks/analysis FK constraints succeed."""
        sessions = get_sessionmaker()
        if sessions is None:
            return
        async with sessions.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO users (id, email, display_name)
                    VALUES (:id, :email, :display_name)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": workspace.user_id,
                    "email": f"{workspace.user_id}@rlb.local",
                    "display_name": "RLB User",
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO workspaces (
                        id, user_id, name, slug, description, environment_mode, status,
                        canonical_root_path, file_count, total_size_bytes, current_snapshot_hash,
                        git_remote_url, is_archived, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :name, :slug, :description, :environment_mode, :status,
                        :canonical_root_path, :file_count, :total_size_bytes, :current_snapshot_hash,
                        :git_remote_url, :is_archived, :created_at, :updated_at
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        canonical_root_path = EXCLUDED.canonical_root_path,
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        status = EXCLUDED.status,
                        file_count = EXCLUDED.file_count,
                        total_size_bytes = EXCLUDED.total_size_bytes,
                        current_snapshot_hash = EXCLUDED.current_snapshot_hash,
                        updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "id": workspace.id,
                    "user_id": workspace.user_id,
                    "name": workspace.name,
                    "slug": workspace.slug,
                    "description": workspace.description,
                    "environment_mode": workspace.environment_mode.value,
                    "status": workspace.status.value,
                    "canonical_root_path": workspace.canonical_root_path,
                    "file_count": workspace.file_count,
                    "total_size_bytes": workspace.total_size_bytes,
                    "current_snapshot_hash": workspace.current_snapshot_hash,
                    "git_remote_url": workspace.git_remote_url,
                    "is_archived": workspace.is_archived,
                    "created_at": workspace.created_at,
                    "updated_at": workspace.updated_at,
                },
            )
            loadout_id = (
                await session.execute(
                    text(
                        """
                        SELECT id FROM loadouts
                        WHERE user_id = :user_id OR is_system_preset = TRUE
                        ORDER BY CASE WHEN user_id = :user_id THEN 0 ELSE 1 END, created_at
                        LIMIT 1
                        """
                    ),
                    {"user_id": workspace.user_id},
                )
            ).scalar()
            if loadout_id is None:
                loadout_id = uuid.uuid4()
                await session.execute(
                    text(
                        """
                        INSERT INTO loadouts (id, user_id, name, description, is_system_preset, mappings)
                        VALUES (:id, :user_id, :name, :description, FALSE, CAST(:mappings AS jsonb))
                        """
                    ),
                    {
                        "id": loadout_id,
                        "user_id": workspace.user_id,
                        "name": "Default Loadout",
                        "description": "Auto-created so workspace tasks can resolve a Planner/Coder loadout.",
                        "mappings": "{}",
                    },
                )
            await session.execute(
                text(
                    """
                    INSERT INTO workspace_settings (workspace_id, active_loadout_id)
                    VALUES (:workspace_id, :loadout_id)
                    ON CONFLICT (workspace_id) DO UPDATE SET
                        active_loadout_id = COALESCE(workspace_settings.active_loadout_id, EXCLUDED.active_loadout_id),
                        updated_at = NOW()
                    """
                ),
                {"workspace_id": workspace.id, "loadout_id": loadout_id},
            )
            for record in file_records:
                created_at = record.get("created_at") or workspace.updated_at
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    except ValueError:
                        created_at = workspace.updated_at
                await session.execute(
                    text(
                        """
                        INSERT INTO files (
                            id, workspace_id, relative_path, file_type, size_bytes, sha256_hash, created_at, updated_at
                        ) VALUES (
                            :id, :workspace_id, :relative_path, :file_type, :size_bytes, :sha256_hash, :created_at, NOW()
                        )
                        ON CONFLICT (workspace_id, relative_path) DO UPDATE SET
                            size_bytes = EXCLUDED.size_bytes,
                            sha256_hash = EXCLUDED.sha256_hash,
                            is_deleted = FALSE,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "id": UUID(str(record["id"])),
                        "workspace_id": workspace.id,
                        "relative_path": record["relative_path"],
                        "file_type": record.get("file_type") or "file",
                        "size_bytes": record.get("size_bytes") or 0,
                        "sha256_hash": record.get("sha256_hash") or "",
                        "created_at": created_at,
                    },
                )

    async def _load_workspace_from_db(self, workspace_id: UUID) -> Optional[Workspace]:
        sessions = get_sessionmaker()
        if sessions is None:
            return None
        async with sessions() as session:
            row = (
                await session.execute(
                    text("SELECT * FROM workspaces WHERE id = :id"),
                    {"id": workspace_id},
                )
            ).mappings().first()
            if not row:
                return None
            files = (
                await session.execute(
                    text(
                        """
                        SELECT id, workspace_id, relative_path, file_type, size_bytes, sha256_hash, created_at
                        FROM files
                        WHERE workspace_id = :id AND is_deleted = FALSE
                        ORDER BY relative_path
                        """
                    ),
                    {"id": workspace_id},
                )
            ).mappings().all()
            ws = _row_to_workspace(row)
            _MEMORY_WORKSPACES[workspace_id] = ws
            _MEMORY_FILES[workspace_id] = [
                {
                    "id": str(f["id"]),
                    "workspace_id": str(f["workspace_id"]),
                    "relative_path": f["relative_path"],
                    "file_type": f["file_type"],
                    "size_bytes": f["size_bytes"],
                    "sha256_hash": f["sha256_hash"],
                    "created_at": f["created_at"].isoformat() if hasattr(f["created_at"], "isoformat") else str(f["created_at"]),
                }
                for f in files
            ]
            return ws

    async def create_workspace(
        self,
        user_id: UUID,
        name: str,
        description: Optional[str] = None,
        environment_mode: EnvironmentMode = EnvironmentMode.SANDBOXED,
        zip_bytes: Optional[bytes] = None,
    ) -> Workspace:
        """
        Provision an approved workspace. If zip_bytes is provided, ingest project files safely.
        """
        workspace_id = uuid.uuid4()
        slug = f"{generate_slug(name)}-{str(workspace_id)[:8]}"
        canonical_prefix = f"workspaces/{workspace_id}/canonical"

        file_count = 0
        total_bytes = 0
        status = WorkspaceStatus.PROVISIONING
        file_records: List[Dict[str, Any]] = []

        try:
            if zip_bytes:
                zf = ZipImportService.validate_zip_stream(zip_bytes)
                entries = ZipImportService.sanitize_and_inspect_members(zf)
                extracted_files = ZipImportService.extract_entries(zf, entries)

                for item in extracted_files:
                    rel_p = item["relative_path"]
                    content = item["content"]
                    storage_p = f"{canonical_prefix}/{rel_p}"

                    await self.storage.write_file(storage_p, content)
                    file_count += 1
                    total_bytes += item["size_bytes"]

                    file_records.append({
                        "id": str(uuid.uuid4()),
                        "workspace_id": str(workspace_id),
                        "relative_path": rel_p,
                        "file_type": "file",
                        "size_bytes": item["size_bytes"],
                        "sha256_hash": item["sha256"],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })

                status = WorkspaceStatus.READY
            else:
                # Empty workspace
                status = WorkspaceStatus.READY

        except Exception as e:
            status = WorkspaceStatus.IMPORT_FAILED
            # Clean up partial storage
            await self.storage.delete_directory(canonical_prefix)
            if isinstance(e, ZipValidationError):
                raise
            raise ZipValidationError("Import failed during extraction.") from e

        workspace = Workspace(
            id=workspace_id,
            user_id=user_id,
            name=name.strip(),
            slug=slug,
            description=description.strip() if description else None,
            environment_mode=environment_mode,
            status=status,
            canonical_root_path=canonical_prefix,
            file_count=file_count,
            total_size_bytes=total_bytes,
            current_snapshot_hash=f"init-{str(workspace_id)[:8]}" if file_count > 0 else None,
            is_archived=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        _MEMORY_WORKSPACES[workspace_id] = workspace
        _MEMORY_FILES[workspace_id] = file_records
        await self._persist_workspace(workspace, file_records)
        return workspace

    async def sync_canonical_metadata(self, workspace: Workspace, *, publish_local=True) -> Workspace:
        """Rebuild file metadata, counts, size, and snapshot hash from canonical storage."""
        prefix = workspace.canonical_root_path.rstrip("/")
        stored_paths = await self.storage.list_files(prefix)
        records: List[Dict[str, Any]] = []
        file_contents: Dict[str, bytes] = {}
        total_bytes = 0
        digest = hashlib.sha256()
        for path in sorted(stored_paths):
            relative = path[len(prefix) + 1:] if path.startswith(prefix + "/") else path
            content = await self.storage.read_file(path)
            file_contents[relative] = content
            total_bytes += len(content)
            file_hash = hashlib.sha256(content).hexdigest()
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
            records.append({
                "id": str(uuid.uuid4()),
                "workspace_id": str(workspace.id),
                "relative_path": relative,
                "file_type": "file",
                "size_bytes": len(content),
                "sha256_hash": file_hash,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        previous_records = [
            dict(item) for item in _MEMORY_FILES.get(workspace.id, [])
        ]
        if publish_local:
            await self._publish_local_snapshot(workspace, file_contents, previous_records)
        previous = {
            item["relative_path"]
            for item in previous_records
            if item.get("relative_path")
        }
        removed = previous - {item["relative_path"] for item in records}
        updated = workspace.model_copy(update={
            "file_count": len(records),
            "total_size_bytes": total_bytes,
            "current_snapshot_hash": digest.hexdigest(),
            "updated_at": datetime.now(timezone.utc),
        })
        _MEMORY_WORKSPACES[workspace.id] = updated
        _MEMORY_FILES[workspace.id] = records
        await self._persist_workspace(updated, records)
        self._persist_local_registration(updated, records)
        await self._mark_files_deleted(workspace.id, removed)
        return updated

    async def replace_tracked_files(
        self, workspace: Workspace, records: List[Dict[str, Any]], snapshot_hash: Optional[str]
    ) -> Workspace:
        """Restore previously tracked file metadata after a failed promotion."""
        total_bytes = sum(int(item.get("size_bytes") or 0) for item in records)
        updated = workspace.model_copy(update={
            "file_count": len(records),
            "total_size_bytes": total_bytes,
            "current_snapshot_hash": snapshot_hash,
            "updated_at": datetime.now(timezone.utc),
        })
        _MEMORY_WORKSPACES[workspace.id] = updated
        _MEMORY_FILES[workspace.id] = records
        await self._persist_workspace(updated, records)
        self._persist_local_registration(updated, records)
        sessions = get_sessionmaker()
        if sessions is not None:
            kept = {item["relative_path"] for item in records}
            async with sessions.begin() as session:
                rows = (await session.execute(
                    text("SELECT relative_path FROM files WHERE workspace_id=:id AND is_deleted=FALSE"),
                    {"id": workspace.id},
                )).scalars().all()
                for relative_path in rows:
                    if relative_path not in kept:
                        await session.execute(
                            text(
                                """
                                UPDATE files SET is_deleted=TRUE, updated_at=NOW()
                                WHERE workspace_id=:workspace_id AND relative_path=:relative_path
                                """
                            ),
                            {"workspace_id": workspace.id, "relative_path": relative_path},
                        )
        return updated

    async def _mark_files_deleted(self, workspace_id: UUID, relative_paths: set[str]) -> None:
        if not relative_paths:
            return
        sessions = get_sessionmaker()
        if sessions is None:
            return
        async with sessions.begin() as session:
            for relative_path in relative_paths:
                await session.execute(
                    text(
                        """
                        UPDATE files SET is_deleted = TRUE, updated_at = NOW()
                        WHERE workspace_id = :workspace_id AND relative_path = :relative_path
                        """
                    ),
                    {"workspace_id": workspace_id, "relative_path": relative_path},
                )

    async def get_workspace(self, workspace_id: UUID, user_id: UUID) -> Workspace:
        """Fetch workspace verifying that user owns it."""
        # Separate Railway processes must see the current canonical pointer.
        self._load_local_registrations(user_id)
        cached = _MEMORY_WORKSPACES.get(workspace_id)
        ws = cached if cached and cached.local_path else None
        if ws is None and get_sessionmaker() is not None:
            ws = await self._load_workspace_from_db(workspace_id)
        if ws is None:
            ws = cached
        if not ws:
            raise WorkspaceNotFoundError(f"Workspace '{workspace_id}' not found.")
        if ws.user_id != user_id:
            raise WorkspaceAccessDeniedError("Access Denied: You do not have permission to view this workspace.")
        return ws

    async def list_user_workspaces(self, user_id: UUID) -> List[Workspace]:
        """List all non-archived workspaces owned by the user."""
        self._load_local_registrations(user_id)
        sessions = get_sessionmaker()
        if sessions is not None:
            async with sessions() as session:
                rows = (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM workspaces
                            WHERE user_id = :user_id AND is_archived = FALSE
                            ORDER BY updated_at DESC
                            """
                        ),
                        {"user_id": user_id},
                    )
                ).mappings().all()
                for row in rows:
                    ws = _row_to_workspace(row)
                    existing = _MEMORY_WORKSPACES.get(ws.id)
                    if existing is None or not existing.local_path:
                        _MEMORY_WORKSPACES[ws.id] = ws
        return sorted([
            ws for ws in _MEMORY_WORKSPACES.values()
            if ws.user_id == user_id and not ws.is_archived
        ], key=lambda item: item.updated_at, reverse=True)

    async def list_workspace_files(self, workspace_id: UUID, user_id: UUID) -> List[Dict[str, Any]]:
        """Return the list of tracked files for an approved workspace."""
        await self.get_workspace(workspace_id, user_id)
        return _MEMORY_FILES.get(workspace_id, [])

    async def read_workspace_file(
        self, workspace_id: UUID, relative_path: str, user_id: UUID
    ) -> bytes:
        """
        Read file bytes from canonical storage.
        Enforces user ownership, path validation, and read-only boundaries.
        """
        ws = await self.get_workspace(workspace_id, user_id)
        clean_rel = self._normalize_import_path(relative_path)
        storage_p = f"{ws.canonical_root_path}/{clean_rel}"
        return await self.storage.read_file(storage_p)

    @staticmethod
    def _normalize_import_path(raw_path: str) -> str:
        raw_name = (raw_path or "").replace("\\", "/")
        if not raw_name or raw_name.endswith("/"):
            raise ZipValidationError("Empty or directory-only paths are not importable as files.")
        if raw_name.startswith("/") or (len(raw_name) > 1 and raw_name[1] == ":"):
            raise ZipValidationError(f"Absolute paths are prohibited: '{raw_path}'")
        normalized = os.path.normpath(raw_name).replace("\\", "/")
        parts = normalized.split("/")
        if ".." in parts or normalized.startswith("/") or normalized in {".", ""}:
            raise ZipValidationError(f"Path traversal detected: '{raw_path}'")
        if "__MACOSX" in parts or parts[-1] == ".DS_Store":
            raise ZipValidationError(f"Unsupported metadata path: '{raw_path}'")
        return normalized

    async def import_project_into_empty_workspace(self, workspace_id, user_id, *, zip_bytes=None, files=None):
        from backend.app.services.workspace_lock import workspace_import_lock
        import asyncio
        async with asyncio.timeout(600):
            async with workspace_import_lock(workspace_id):
                return await self._import_project_into_empty_workspace(
                    workspace_id, user_id, zip_bytes=zip_bytes, files=files)

    async def _import_project_into_empty_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
        *,
        zip_bytes: Optional[bytes] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> Workspace:
        """Initialize an empty approved workspace with a project import.

        Allowed only when the workspace currently has zero files so an active
        approved tree is never silently overwritten. Reuses ZipImportService
        validation for archives and the same path-safety rules for loose files.
        """
        ws = await self.get_workspace(workspace_id, user_id)
        existing = _MEMORY_FILES.get(workspace_id, [])
        if ws.file_count > 0 or existing:
            raise ZipValidationError(
                "Project import is only allowed for empty workspaces. "
                "Use staging/approval for changes to an active approved project."
            )

        extracted: List[Dict[str, Any]] = []
        if zip_bytes is not None:
            zf = ZipImportService.validate_zip_stream(zip_bytes)
            entries = ZipImportService.sanitize_and_inspect_members(zf)
            extracted = ZipImportService.extract_entries(zf, entries)
        elif files:
            total = 0
            seen: set[str] = set()
            for item in files:
                rel = self._normalize_import_path(str(item.get("relative_path") or ""))
                if rel in seen:
                    raise ZipValidationError(f"Duplicate import path: '{rel}'")
                seen.add(rel)
                content = item.get("content") or b""
                if not isinstance(content, (bytes, bytearray)):
                    raise ZipValidationError("File content must be binary.")
                total += len(content)
                if total > ZipImportService.MAX_UNCOMPRESSED_BYTES:
                    raise ZipValidationError("Import exceeds uncompressed size quota.")
                if len(seen) > ZipImportService.MAX_FILE_COUNT:
                    raise ZipValidationError("Import exceeds file count quota.")
                extracted.append({
                    "relative_path": rel,
                    "content": bytes(content),
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                })
        else:
            raise ZipValidationError("No project files were provided for import.")

        if not extracted:
            raise ZipValidationError("Import contained no files.")

        file_records: List[Dict[str, Any]] = []
        total_bytes = 0
        root = f"workspaces/{workspace_id}/snapshots/{uuid.uuid4()}"
        for item in extracted:
            rel_p = item["relative_path"]
            content = item["content"]
            storage_p = f"{root}/{rel_p}"
            await self.storage.write_file(storage_p, content)
            total_bytes += item["size_bytes"]
            file_records.append({
                "id": str(uuid.uuid4()),
                "workspace_id": str(workspace_id),
                "relative_path": rel_p,
                "file_type": "file",
                "size_bytes": item["size_bytes"],
                "sha256_hash": item["sha256"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

        updated = ws.model_copy(update={
            "canonical_root_path": root,
            "file_count": len(file_records),
            "total_size_bytes": total_bytes,
            "status": WorkspaceStatus.READY,
            "current_snapshot_hash": f"import-{str(workspace_id)[:8]}",
            "updated_at": datetime.now(timezone.utc),
        })
        await self._persist_workspace(updated, file_records)
        _MEMORY_WORKSPACES[workspace_id] = updated
        _MEMORY_FILES[workspace_id] = file_records
        self._persist_local_registration(updated, file_records)
        return updated
