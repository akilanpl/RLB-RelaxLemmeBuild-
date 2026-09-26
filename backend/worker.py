"""Local worker entrypoint.

The API process consumes the in-memory queue. This module builds the same
handler map so a co-located worker does not start with an empty registry.
"""

import asyncio
import os

from backend.app.api.v1.tasks import configure_agent_services, job_queue, testing_repository
from backend.app.services.composition import build_agent_services
from backend.app.services.durable_worker import build_default_worker
from backend.app.services.test_orchestrator import TestOrchestrationService


async def run_worker() -> None:
    """Run the composed local worker until the shared queue is idle."""
    services = build_agent_services()
    configure_agent_services(services)
    orchestrator = TestOrchestrationService(
        job_queue.workflow, testing_repository, sandbox=None
    )
    worker = build_default_worker(
        job_queue,
        os.getenv("WORKER_ID", "local-worker"),
        services.planner,
        services.coder,
        services.reviewer,
        orchestrator,
    )
    await worker.run_until_idle()


if __name__ == "__main__":
    asyncio.run(run_worker())
