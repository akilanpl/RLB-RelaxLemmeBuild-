"""Single lazy composition root shared by HTTP and worker entrypoints.

Importing a route or service never constructs infrastructure. Hosted configuration
is validated before any dependency can be resolved; tests may inject service ports.
"""
from dataclasses import dataclass
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

    def worker(self, worker_id):
        from backend.app.services.durable_worker import build_default_worker
        return build_default_worker(self.queue, worker_id, self.agents.planner,
                                    self.agents.coder, self.agents.reviewer, self.orchestrator)

    async def start(self):
        if self.agents.resolver.repository:
            await self.agents.resolver.hydrate()
        from backend.app.core.config import get_settings
        if get_settings().ENVIRONMENT in {'staging', 'production'}:
            from urllib.parse import quote
            from sqlalchemy import text
            from backend.app.db.session import get_engine
            async with get_engine().connect() as connection:
                version = (await connection.execute(text('SELECT version FROM rlb_schema_versions WHERE version=5'))).scalar()
                if version != 5:
                    raise RuntimeError('Hosted migration 005 is required.')
                await connection.execute(text('SELECT root_path FROM artifact_cleanup LIMIT 0'))
                await connection.execute(text('SELECT root_path FROM artifact_audit_roots LIMIT 0'))
                await connection.execute(text('SELECT attempts FROM queue_delivery_attempts LIMIT 0'))
                await connection.execute(text('SELECT artifact_root_path FROM git_snapshots LIMIT 0'))
            storage = self.workspace.storage
            bucket = (await storage.client._request('GET', '/bucket/' + quote(storage.bucket, safe=''))).json()
            if bucket.get('public') is not False:
                raise RuntimeError('Workspace artifact bucket must be private.')

    async def close(self):
        if self.sandbox is not None:
            await self.sandbox.client.close()
        if hasattr(self.queue, 'client'):
            await self.queue.client.close()


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
    from backend.app.repositories.testing import PostgresTestingRepository, InMemoryTestingRepository
    from backend.app.services.composition import build_agent_services
    from backend.app.services.job_queue import LocalJobQueue
    from backend.app.services.supabase_queue import SupabaseQueueAdapter
    from backend.app.services.supabase_queue_client import SupabaseQueueClient
    from backend.app.services.production_runtime import build_configured_sandbox
    from backend.app.services.test_orchestrator import TestOrchestrationService

    settings = get_settings()
    validate_hosted_configuration(role)
    sessions = get_sessionmaker()
    storage = get_storage_backend()
    workspace = WorkspaceService(storage)
    staging = StagingService(workspace, storage)
    workflow = WorkflowEngine(workspace, PostgresTaskRepository(sessions) if sessions else InMemoryTaskRepository())
    agents = build_agent_services(workflow=workflow, staging=staging)
    testing = PostgresTestingRepository(sessions) if sessions else InMemoryTestingRepository()
    agents.reviewer.context_builder.proposals = agents.coder.proposals
    agents.reviewer.context_builder.testing = testing
    queue = (SupabaseQueueAdapter(SupabaseQueueClient(get_engine()), settings.SUPABASE_QUEUE_NAME, workflow)
             if settings.ENVIRONMENT in {'staging', 'production'} else LocalJobQueue(workflow))
    # The API never creates a hosted sandbox client; only the worker composes it.
    sandbox = (build_configured_sandbox(storage)
               if role == "worker" or settings.ENVIRONMENT not in {'staging', 'production'} else None)
    return Runtime(workflow, workspace, staging, CodebaseAnalysisService(workspace_service=workspace),
                   agents, testing, queue, sandbox,
                   TestOrchestrationService(workflow, testing, sandbox, agents.resolver, agents.coder.proposals))
