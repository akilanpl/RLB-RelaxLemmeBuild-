"""Health and diagnostic API endpoints."""

from pydantic import BaseModel
from fastapi import APIRouter
from backend.app.core.config import get_settings
from backend.app.db.health import check_database_health, DatabaseHealthStatus

router = APIRouter(tags=["health"])


class SystemHealthResponse(BaseModel):
    status: str
    project: str
    environment: str


class FullHealthResponse(BaseModel):
    status: str
    project: str
    environment: str
    database: DatabaseHealthStatus


class DependencyHealthResponse(BaseModel):
    status: str
    configured: bool


@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health():
    """
    Standard liveness and health endpoint.
    Returns ok when the application process is running.
    """
    settings = get_settings()
    return SystemHealthResponse(
        status="ok",
        project=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
    )


@router.get("/health/db", response_model=DatabaseHealthStatus)
async def get_database_health():
    """
    Database diagnostic endpoint.
    Verifies connection to Supabase / PostgreSQL without leaking sensitive connection details.
    """
    return await check_database_health()


@router.get("/health/full", response_model=FullHealthResponse)
async def get_full_health():
    """Combined system and database diagnostic status."""
    settings = get_settings()
    db_health = await check_database_health()
    overall_status = "ok" if (not db_health.configured or db_health.connected) else "degraded"
    return FullHealthResponse(
        status=overall_status,
        project=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        database=db_health,
    )


@router.get("/health/queue", response_model=DependencyHealthResponse)
async def get_queue_health():
    settings = get_settings()
    configured = bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
    return DependencyHealthResponse(status="ok" if configured or settings.ENVIRONMENT != "production" else "degraded",
                                    configured=configured)


@router.get("/health/storage", response_model=DependencyHealthResponse)
async def get_storage_health():
    settings = get_settings()
    configured = bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)
    return DependencyHealthResponse(status="ok" if configured or settings.ENVIRONMENT != "production" else "degraded",
                                    configured=configured)


@router.get("/health/sandbox", response_model=DependencyHealthResponse)
async def get_sandbox_health():
    settings = get_settings()
    configured = bool(settings.DAYTONA_API_KEY and settings.DAYTONA_SANDBOX_IMAGE)
    return DependencyHealthResponse(status="configured" if configured else "not_configured",
                                    configured=configured)
