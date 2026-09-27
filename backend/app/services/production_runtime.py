"""Production runtime composition seam for cloud infrastructure clients."""

from dataclasses import dataclass
from typing import Any

from backend.app.core.config import get_settings
from backend.app.sandbox.daytona import DaytonaSandboxDriver
from backend.app.services.supabase_queue import SupabaseQueueAdapter
from backend.app.storage.supabase import SupabaseStorageBackend


@dataclass(frozen=True)
class ProductionRuntime:
    queue: SupabaseQueueAdapter
    storage: SupabaseStorageBackend
    sandbox: DaytonaSandboxDriver


def build_production_runtime(supabase_queue_client: Any, supabase_storage_client: Any,
                             daytona_client: Any) -> ProductionRuntime:
    settings = get_settings()
    if settings.ENVIRONMENT not in {"staging", "production"}:
        raise RuntimeError("Production runtime composition requires ENVIRONMENT=production.")
    return ProductionRuntime(
        queue=SupabaseQueueAdapter(supabase_queue_client, settings.SUPABASE_QUEUE_NAME),
        storage=SupabaseStorageBackend(supabase_storage_client, settings.SUPABASE_STORAGE_BUCKET),
        sandbox=DaytonaSandboxDriver(daytona_client),
    )



def build_configured_sandbox(storage=None):
    """No cloud requests or SDK imports in an unconfigured local environment."""
    settings = get_settings()
    if not (settings.DAYTONA_API_KEY and settings.DAYTONA_SANDBOX_IMAGE):
        return None
    from daytona import AsyncDaytona, DaytonaConfig
    from backend.app.sandbox.daytona_client import DaytonaRuntimeClient
    from backend.app.storage import get_storage_backend
    sdk = AsyncDaytona(DaytonaConfig(
        api_key=settings.DAYTONA_API_KEY,
        api_url=settings.DAYTONA_API_URL or "https://app.daytona.io/api",
        target=settings.DAYTONA_TARGET,
    ))
    return DaytonaSandboxDriver(DaytonaRuntimeClient(
        sdk, storage or get_storage_backend(), settings.DAYTONA_SANDBOX_IMAGE,
    ))
