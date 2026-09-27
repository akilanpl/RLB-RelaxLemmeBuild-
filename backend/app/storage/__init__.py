"""Storage abstraction package."""

from pathlib import Path
from typing import Optional
from backend.app.storage.base import BaseStorageBackend, StorageError, StorageSecurityError
from backend.app.storage.local import LocalStorageBackend

_default_storage: Optional[BaseStorageBackend] = None


def configure_storage_backend(storage: BaseStorageBackend) -> None:
    """Install the production storage adapter at the composition boundary."""
    global _default_storage
    _default_storage = storage


def get_storage_backend(base_path: Optional[str | Path] = None) -> BaseStorageBackend:
    """Factory for obtaining the storage backend instance."""
    global _default_storage
    if base_path is not None:
        return LocalStorageBackend(base_path)

    if _default_storage is None:
        from backend.app.core.config import get_settings
        settings = get_settings()
        if settings.ENVIRONMENT in {"staging", "production"}:
            from backend.app.storage.supabase import SupabaseStorageBackend
            from backend.app.storage.supabase_client import SupabaseStorageClient
            if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
                raise RuntimeError("Hosted workspace storage requires Supabase configuration.")
            _default_storage = SupabaseStorageBackend(
                SupabaseStorageClient(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY),
                settings.SUPABASE_STORAGE_BUCKET,
            )
            return _default_storage
        # Default to storage/ under project root
        project_root = Path(__file__).resolve().parents[3]
        storage_dir = project_root / "storage"
        _default_storage = LocalStorageBackend(storage_dir)

    return _default_storage
