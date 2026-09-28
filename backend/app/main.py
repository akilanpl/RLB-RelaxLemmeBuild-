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
    get_queue_health, get_storage_health, get_sandbox_health, get_readiness,
)


async def _consume_queue(worker, stop: asyncio.Event) -> None:
    logger = logging.getLogger(__name__)
    while not stop.is_set():
        try:
            job = await worker.run_once()
        except Exception as exc:
            logger.error("Worker job failed (%s)", type(exc).__name__)
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
    from backend.app.core.preflight import validate_hosted_configuration
    validate_hosted_configuration("api")
    from backend.app.services.runtime import get_runtime
    runtime = get_runtime()
    services = runtime.agents
    app.state.runtime = runtime
    await runtime.start()
    stop = asyncio.Event()
    worker_task = None
    embedded = settings.RUN_EMBEDDED_WORKER
    if embedded is None:
        embedded = settings.ENVIRONMENT in {"development", "test"}
    if services is not None and embedded:
        worker = runtime.worker(os.getenv("WORKER_ID", "local-worker"))
        worker_task = asyncio.create_task(_consume_queue(worker, stop))
    yield
    stop.set()
    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    await runtime.close()


def create_app() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        lifespan=lifespan,
    )

    from fastapi.responses import JSONResponse
    from backend.app.services.task_service import WorkflowConflictError, InvalidWorkflowTransitionError

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({'detail': 'Resource access denied.'}, status_code=403)

    @app.exception_handler(WorkflowConflictError)
    @app.exception_handler(InvalidWorkflowTransitionError)
    async def conflict(request, exc):
        return JSONResponse({'detail': 'Workflow state changed or action is not allowed. Reload the task.'}, status_code=409)

    # Configure CORS
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_api_route("/ready", get_readiness, methods=["GET"], tags=["health"])

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
