"""Main FastAPI application entrypoint."""

import asyncio
import hmac
import logging
import os
from urllib.parse import urlsplit
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
    artifact_cleanup_task = None
    embedded = settings.RUN_EMBEDDED_WORKER
    if embedded is None:
        embedded = settings.ENVIRONMENT in {"development", "desktop", "test"}
    if services is not None and embedded:
        worker = runtime.worker(os.getenv("WORKER_ID", "local-worker"))
        worker_task = asyncio.create_task(_consume_queue(worker, stop))
    if settings.ENVIRONMENT in {"staging", "production"}:
        from backend.app.db.session import get_engine
        from backend.app.services.artifact_cleanup import cleanup_loop
        artifact_cleanup_task = asyncio.create_task(
            cleanup_loop(get_engine(), runtime.workspace.storage, settings)
        )
    app.state.worker_task = worker_task
    yield
    stop.set()
    if artifact_cleanup_task is not None:
        artifact_cleanup_task.cancel()
        try:
            await artifact_cleanup_task
        except asyncio.CancelledError:
            pass
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
    cors_origins = [] if settings.ENVIRONMENT == "desktop" else list(settings.BACKEND_CORS_ORIGINS)
    desktop_origin = settings.RLB_DESKTOP_ORIGIN
    if desktop_origin:
        parsed_origin = urlsplit(desktop_origin)
        if (parsed_origin.scheme != "http"
                or parsed_origin.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed_origin.username or parsed_origin.password
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.query or parsed_origin.fragment):
            raise ValueError("RLB_DESKTOP_ORIGIN must be an HTTP loopback origin.")
        cors_origins.append(desktop_origin.rstrip("/"))

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def protect_local_api(request, call_next):
        if (settings.RLB_CONTROL_PLANE_ONLY and request.method not in {"GET", "HEAD", "OPTIONS"}
                and any(request.url.path.startswith(settings.API_V1_PREFIX + prefix)
                        for prefix in ("/tasks", "/workspaces", "/providers"))):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Execution and project configuration belong to your paired PC. Use device commands."}, status_code=409)
        token = os.environ.get("RLB_LOCAL_API_TOKEN")
        if (settings.ENVIRONMENT in {"development", "desktop"} and token
                and request.url.path.startswith(settings.API_V1_PREFIX)
                and request.method != "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in {item.rstrip("/") for item in cors_origins}:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Local API origin is not allowed."}, status_code=403)
            supplied = request.headers.get("x-rlb-local-token", "")
            if not hmac.compare_digest(token, supplied):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "Local runtime authentication required."}, status_code=401)
        return await call_next(request)

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
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
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
