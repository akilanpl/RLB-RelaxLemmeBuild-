"""Single lazy composition root shared by HTTP and worker entrypoints.

Importing a route or service never constructs infrastructure. Hosted configuration
is validated before any dependency can be resolved; tests may inject service ports.
"""
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RuntimeRef:
    def __init__(self, path):
        self.path = path

    def __getattr__(self, name):
        value = get_runtime()
        for part in self.path.split('.'):
            value = getattr(value, part)
        return getattr(value, name)


@dataclass
class Runtime:
    workflow: Any
    workspace: Any
    staging: Any
    analysis: Any
    agents: Any
    testing: Any
    queue: Any
    sandbox: Any
    orchestrator: Any
    devices: Any = None
    device_connection: Any = None
    device_task: Any = None

    def worker(self, worker_id):
        from backend.app.services.durable_worker import build_default_worker
        return build_default_worker(self.queue, worker_id, self.agents.planner,
                                    self.agents.coder, self.agents.reviewer, self.orchestrator)

    async def start(self):
        from backend.app.core.config import get_settings
        for resource in (self.workflow.repository, self.queue):
            load = getattr(resource, "load", None)
            if load:
                await load()
        if self.devices is not None:
            await self.devices.start()
        if self.agents.resolver.repository:
            await self.agents.resolver.hydrate()
        if get_settings().ENVIRONMENT in {'staging', 'production'}:
            from urllib.parse import quote
            from sqlalchemy import text
            from backend.app.db.session import get_engine
            async with get_engine().connect() as connection:
                version = (await connection.execute(text('SELECT version FROM rlb_schema_versions WHERE version=8'))).scalar()
                if version != 8:
                    raise RuntimeError('Hosted migration 008 is required.')
                await connection.execute(text('SELECT root_path FROM artifact_cleanup LIMIT 0'))
                await connection.execute(text('SELECT root_path FROM artifact_audit_roots LIMIT 0'))
                await connection.execute(text('SELECT attempts FROM queue_delivery_attempts LIMIT 0'))
                await connection.execute(text('SELECT artifact_root_path FROM git_snapshots LIMIT 0'))
                await connection.execute(text('SELECT object_path FROM rlb_task_artifacts LIMIT 0'))
            storage = self.workspace.storage
            bucket = (await storage.client._request('GET', '/bucket/' + quote(storage.bucket, safe=''))).json()
            if bucket.get('public') is not False:
                raise RuntimeError('Workspace artifact bucket must be private.')
        if self.device_connection is not None:
            await self._start_device_connection()

    async def configure_device_connection(self, api_url: str, device_token: str) -> None:
        from backend.app.services.device_connection import DeviceConnectionManager
        from backend.app.core.config import get_settings
        if self.device_task is not None:
            self.device_task.cancel()
            try:
                await self.device_task
            except asyncio.CancelledError:
                pass
            self.device_task = None
        if self.device_connection is not None:
            await self.device_connection.close()
        settings = get_settings()
        self.device_connection = DeviceConnectionManager(
            api_url, device_token, Path(settings.LOCAL_DATA_DIR) / "device-connection.sqlite3",
            command_handler=lambda command: None,
        )
        await self._start_device_connection()

    async def _start_device_connection(self) -> None:
        from backend.app.services.remote_command_router import RemoteCommandRouter
        self.device_connection.command_handler = RemoteCommandRouter(self)
        if hasattr(self.workflow.repository, "pending_events"):
            self.device_connection.event_source = self.workflow.repository
        await self.device_connection.start()
        self.device_task = asyncio.create_task(self.device_connection.run(self.connection_status))

    def connection_status(self):
        from backend.app.core.config import get_settings
        jobs = getattr(self.queue, "jobs", {}).values()
        jobs = list(jobs)
        active_statuses = {"pending", "running", "waiting"}
        current = next((job for job in reversed(jobs)
                        if getattr(job.status, "value", "") == "running"), None)
        if current is None:
            current = next((job for job in reversed(jobs)
                            if getattr(job.status, "value", "") in active_statuses), None)
        paused = current is not None and current.task_id in getattr(self.queue, "paused_tasks", set())
        if paused:
            runtime_state = "paused"
        elif current is None:
            runtime_state = "stopped"
        elif getattr(current.status, "value", "") == "running":
            runtime_state = "running"
        else:
            runtime_state = "starting"
        return {
            "runtime_state": runtime_state,
            "current_task_id": current.task_id if current else None,
            "app_version": get_settings().RLB_APP_VERSION,
            "runtime_version": get_settings().RLB_RUNTIME_VERSION,
            "capabilities": {"local_execution": True, "workflow": True},
        }

    async def close(self):
        if self.device_task is not None:
            self.device_task.cancel()
            try:
                await self.device_task
            except asyncio.CancelledError:
                pass
        if self.device_connection is not None:
            await self.device_connection.close()
        if self.sandbox is not None:
            if hasattr(self.sandbox, "client"):
                await self.sandbox.client.close()
        if hasattr(self.queue, 'client'):
            await self.queue.client.close()
        for resource in (self.workflow.repository, self.queue):
            close = getattr(resource, "close", None)
            if close:
                await close()
        if self.devices is not None:
            await self.devices.close()


_runtime = None


def get_runtime(role="api"):
    global _runtime
    if _runtime is None:
        _runtime = build_runtime(role)
    return _runtime


def build_runtime(role="api"):
    from backend.app.core.config import get_settings
    from backend.app.core.preflight import validate_hosted_configuration
    from backend.app.db.session import get_sessionmaker, get_engine
    from backend.app.storage import get_storage_backend
    from backend.app.services.workspace_service import WorkspaceService
    from backend.app.services.staging_service import StagingService
    from backend.app.analysis.service import CodebaseAnalysisService
    from backend.app.services.task_service import WorkflowEngine
    from backend.app.repositories.task import PostgresTaskRepository, InMemoryTaskRepository
    from backend.app.repositories.sqlite_task import SQLiteTaskRepository
    from backend.app.repositories.testing import PostgresTestingRepository, InMemoryTestingRepository
    from backend.app.services.composition import build_agent_services
    from backend.app.services.job_queue import LocalJobQueue
    from backend.app.services.local_queue import SQLiteJobQueue
    from backend.app.services.supabase_queue import SupabaseQueueAdapter
    from backend.app.services.supabase_queue_client import SupabaseQueueClient
    from backend.app.services.production_runtime import build_configured_sandbox
    from backend.app.services.test_orchestrator import TestOrchestrationService
    from backend.app.services.device_control import DeviceControlService

    settings = get_settings()
    validate_hosted_configuration(role)
    running_tests = settings.ENVIRONMENT == "test" or "pytest" in sys.modules
    sessions = get_sessionmaker()
    devices = DeviceControlService(
        Path(settings.LOCAL_DATA_DIR) / "rlb.sqlite3"
        if settings.ENVIRONMENT == "development" and not running_tests else
        ":memory:" if running_tests else None,
        sessions=sessions if settings.ENVIRONMENT in {"staging", "production"} else None,
    )
    device_connection = None
    if (settings.ENVIRONMENT == "development"
            and settings.RLB_CONTROL_PLANE_URL and settings.RLB_DEVICE_TOKEN):
        from backend.app.services.device_connection import DeviceConnectionManager
        device_connection = DeviceConnectionManager(
            settings.RLB_CONTROL_PLANE_URL, settings.RLB_DEVICE_TOKEN,
            Path(settings.LOCAL_DATA_DIR) / "device-connection.sqlite3",
            command_handler=lambda command: None,
        )
    storage = get_storage_backend(
        Path(settings.LOCAL_DATA_DIR) / "workspace-storage"
        if settings.ENVIRONMENT == "development" and not running_tests else None
    )
    workspace = WorkspaceService(storage)
    staging = StagingService(workspace, storage)
    local_persistence = settings.ENVIRONMENT == "development" and not running_tests
    repository = (
        PostgresTaskRepository(sessions) if sessions else
        SQLiteTaskRepository(Path(settings.LOCAL_DATA_DIR) / "rlb.sqlite3")
        if local_persistence else InMemoryTaskRepository()
    )
    workflow = WorkflowEngine(workspace, repository)
    agents = build_agent_services(workflow=workflow, staging=staging)
    testing = PostgresTestingRepository(sessions) if sessions else InMemoryTestingRepository()
    agents.reviewer.context_builder.proposals = agents.coder.proposals
    agents.reviewer.context_builder.testing = testing
    queue = (SupabaseQueueAdapter(SupabaseQueueClient(get_engine()), settings.SUPABASE_QUEUE_NAME, workflow)
             if settings.ENVIRONMENT in {'staging', 'production'} else
             SQLiteJobQueue(workflow, Path(settings.LOCAL_DATA_DIR) / "rlb.sqlite3")
             if local_persistence else LocalJobQueue(workflow))
    # The API never creates a hosted sandbox client; only the worker composes it.
    if settings.ENVIRONMENT in {'staging', 'production'}:
        sandbox = build_configured_sandbox(storage) if role == "worker" else None
    else:
        from backend.app.sandbox.local import LocalWindowsSandboxDriver
        sandbox = LocalWindowsSandboxDriver()
    return Runtime(workflow, workspace, staging, CodebaseAnalysisService(workspace_service=workspace),
                   agents, testing, queue, sandbox,
                   TestOrchestrationService(workflow, testing, sandbox, agents.resolver, agents.coder.proposals),
                   devices, device_connection)
