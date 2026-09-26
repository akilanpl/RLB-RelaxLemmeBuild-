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
    if settings.ENVIRONMENT != "production":
        raise RuntimeError("Production runtime composition requires ENVIRONMENT=production.")
    return ProductionRuntime(
        queue=SupabaseQueueAdapter(supabase_queue_client, settings.SUPABASE_QUEUE_NAME),
        storage=SupabaseStorageBackend(supabase_storage_client, settings.SUPABASE_STORAGE_BUCKET),
        sandbox=DaytonaSandboxDriver(daytona_client),
    )
