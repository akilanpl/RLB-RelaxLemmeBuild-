"""Independent worker for the shared PostgreSQL task queue.

Run from the project root with python -m backend.worker.
"""
import asyncio
import logging
import os
import signal
from uuid import uuid4

from backend.app.api.v1.tasks import configure_agent_services, job_queue, testing_repository
from backend.app.core.config import get_settings
from backend.app.services.composition import build_agent_services
from backend.app.services.durable_worker import build_default_worker
from backend.app.services.supabase_queue import SupabaseQueueAdapter
from backend.app.services.test_orchestrator import TestOrchestrationService
from backend.app.services.production_runtime import build_configured_sandbox


async def run_worker() -> None:
    if not isinstance(job_queue, SupabaseQueueAdapter):
        raise RuntimeError("Standalone workers require staging/production configuration and the Supabase Queue migration.")
    settings = get_settings()
    from backend.app.core.preflight import validate_hosted_configuration
    validate_hosted_configuration("worker")
    services = build_agent_services()
    configure_agent_services(services)
    orchestrator = TestOrchestrationService(job_queue.workflow, testing_repository, sandbox=build_configured_sandbox(), runtime_resolver=services.resolver)
    worker = build_default_worker(
        job_queue, os.getenv("WORKER_ID") or f"worker-{uuid4()}",
        services.planner, services.coder, services.reviewer, orchestrator,
    )
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, current.cancel)
    try:
        await _consume(worker, services, settings)
    finally:
        await job_queue.client.close()
        if orchestrator.sandbox is not None:
            await orchestrator.sandbox.client.close()


async def _consume(worker, services, settings):
    while True:
        try:
            if services.resolver is not None:
                await services.resolver.hydrate()
            job = await worker.run_once()
        except Exception:
            logging.getLogger(__name__).exception("Worker job failed")
            job = None
        if job is None:
            await asyncio.sleep(settings.WORKER_POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
