"""Database health check and diagnostic service."""

import time
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import text
from backend.app.core.config import get_settings
from backend.app.db.session import get_engine


class DatabaseHealthStatus(BaseModel):
    configured: bool
    connected: bool
    latency_ms: Optional[float] = None
    message: str


async def check_database_health() -> DatabaseHealthStatus:
    """
    Verify backend connectivity to Supabase/PostgreSQL.
    Crucially: NEVER exposes database URLs, passwords, or secrets in the response.
    """
    settings = get_settings()

    if not settings.DATABASE_URL:
        return DatabaseHealthStatus(
            configured=False,
            connected=False,
            latency_ms=None,
            message="DATABASE_URL is not configured. Database features are currently idle.",
        )

    engine = get_engine()
    if engine is None:
        return DatabaseHealthStatus(
            configured=True,
            connected=False,
            latency_ms=None,
            message="Failed to initialize database engine.",
        )

    start_time = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return DatabaseHealthStatus(
            configured=True,
            connected=True,
            latency_ms=duration_ms,
            message="Database connection established successfully.",
        )
    except Exception as e:
        # Sanitize exception message to ensure no connection credentials leak
        error_type = type(e).__name__
        return DatabaseHealthStatus(
            configured=True,
            connected=False,
            latency_ms=None,
            message=f"Database connection failed ({error_type}). Ensure host is reachable and credentials are valid.",
        )
