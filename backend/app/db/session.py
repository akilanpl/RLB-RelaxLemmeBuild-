"""Database engine and session management."""

import os
import ssl
import sys
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from backend.app.core.config import get_settings

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> Optional[AsyncEngine]:
    """Lazy initialize and return the async database engine if DATABASE_URL is configured."""
    global _engine, _sessionmaker
    settings = get_settings()

    if not settings.DATABASE_URL:
        return None

    # Automated tests are in-memory unless explicitly opted in. Never reuse the
    # developer's live Supabase URL inside pytest.
    if "pytest" in sys.modules and os.environ.get("USE_REAL_DATABASE_IN_TESTS") != "1":
        return None

    if _engine is None:
        # Normalize postgres:// to postgresql+asyncpg:// if needed
        db_url = settings.DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        parsed = urlparse(db_url)
        hostname = (parsed.hostname or "").lower()
        connect_args: dict = {}
        if hostname.endswith((".supabase.com", ".supabase.co")) or "pooler.supabase" in hostname:
            try:
                import certifi
                ssl_context = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ssl_context = ssl.create_default_context()
            # Local networks sometimes intercept TLS with a private CA.
            # Keep encryption on; only skip CA verification outside production.
            if settings.ENVIRONMENT in {"development", "test"}:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ssl_context

        _engine = create_async_engine(
            db_url,
            echo=settings.DEBUG,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        _sessionmaker = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    return _engine


def get_sessionmaker() -> Optional[async_sessionmaker[AsyncSession]]:
    """Return the configured factory for repository adapters."""
    get_engine()
    return _sessionmaker


async def get_db() -> AsyncGenerator[Optional[AsyncSession], None]:
    """Dependency for providing database sessions to request handlers."""
    engine = get_engine()
    if engine is None or _sessionmaker is None:
        yield None
        return

    async with _sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
