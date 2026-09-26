"""Main FastAPI application entrypoint."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import get_settings
from backend.app.api.v1.api import api_v1_router
from backend.app.api.v1.health import (
    get_system_health, get_database_health, get_full_health,
    get_queue_health, get_storage_health, get_sandbox_health,
)
from backend.app.services.composition import build_agent_services
from backend.app.api.v1.tasks import configure_agent_services, job_queue, testing_repository
from backend.app.services.durable_worker import build_default_worker
from backend.app.services.test_orchestrator import TestOrchestrationService


async def _consume_queue(worker, stop: asyncio.Event) -> None:
    logger = logging.getLogger(__name__)
    while not stop.is_set():
        try:
            job = await worker.run_once()
        except Exception:
            logger.exception("Durable worker failed a job")
            job = None
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.4)
            except asyncio.TimeoutError:
                continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    settings = get_settings()
    services = getattr(app.state, "agent_services", None)
    if services and services.resolver and services.resolver.repository:
        try:
            await services.resolver.hydrate()
        except Exception as exc:
            if settings.ENVIRONMENT == "production":
                raise RuntimeError("Provider configuration hydration failed; refusing startup.") from exc
            logging.getLogger(__name__).warning(
                "Provider configuration hydration failed (%s); continuing in %s so health diagnostics remain available.",
                type(exc).__name__,
                settings.ENVIRONMENT,
            )
    stop = asyncio.Event()
    worker_task = None
    if services is not None:
        orchestrator = TestOrchestrationService(job_queue.workflow, testing_repository, sandbox=None)
        worker = build_default_worker(
            job_queue,
            os.getenv("WORKER_ID", "local-worker"),
            services.planner,
            services.coder,
            services.reviewer,
            orchestrator,
        )
        worker_task = asyncio.create_task(_consume_queue(worker, stop))
    yield
    stop.set()
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()
    # Construct one resolver for all production LLM-backed agents.
    services = build_agent_services()
    configure_agent_services(services)

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        lifespan=lifespan,
    )
    app.state.agent_services = services

    # Configure CORS
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Root health endpoints
    app.add_api_route("/health", get_system_health, methods=["GET"], tags=["health"])
    app.add_api_route("/health/db", get_database_health, methods=["GET"], tags=["health"])
    app.add_api_route("/health/full", get_full_health, methods=["GET"], tags=["health"])
    app.add_api_route("/health/queue", get_queue_health, methods=["GET"], tags=["health"])
    app.add_api_route("/health/storage", get_storage_health, methods=["GET"], tags=["health"])
    app.add_api_route("/health/sandbox", get_sandbox_health, methods=["GET"], tags=["health"])

    # API v1 prefix router
    app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
