"""Independent worker for the shared PostgreSQL task queue.

Run from the project root with python -m backend.worker.
"""
import asyncio
import logging
import os
import signal
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.services.supabase_queue import SupabaseQueueAdapter


async def run_worker() -> None:
    from backend.app.services.runtime import get_runtime
    settings = get_settings()
    from backend.app.core.preflight import validate_hosted_configuration
    validate_hosted_configuration("worker")
    runtime = get_runtime("worker")
    if not isinstance(runtime.queue, SupabaseQueueAdapter):
        raise RuntimeError("Standalone workers require staging/production configuration.")
    await runtime.start()
    services = runtime.agents
    worker = runtime.worker(os.getenv("WORKER_ID") or f"worker-{uuid4()}")
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, current.cancel)
    async def heartbeat():
        from backend.app.services.readiness import record_worker_heartbeat
        while True:
            await record_worker_heartbeat(worker.worker_id)
            await asyncio.sleep(20)
    from backend.app.services.artifact_cleanup import cleanup_loop
    from backend.app.db.session import get_engine
    cleanup_task = asyncio.create_task(cleanup_loop(get_engine(), runtime.workspace.storage, settings))
    heartbeat_task = asyncio.create_task(heartbeat())
    consumer_task = asyncio.create_task(_consume(worker, services, settings))
    try:
        done, _ = await asyncio.wait({heartbeat_task, consumer_task}, return_when=asyncio.FIRST_COMPLETED)
        for completed in done:
            await completed
    finally:
        cleanup_task.cancel()
        heartbeat_task.cancel()
        consumer_task.cancel()
        await asyncio.gather(cleanup_task, heartbeat_task, consumer_task, return_exceptions=True)
        await runtime.close()


async def _consume(worker, services, settings):
    while True:
        try:
            if services.resolver is not None:
                await services.resolver.hydrate()
            job = await worker.run_once()
        except Exception as exc:
            logging.getLogger(__name__).error("Worker job failed (%s)", type(exc).__name__)
            job = None
        if job is None:
            await asyncio.sleep(settings.WORKER_POLL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
