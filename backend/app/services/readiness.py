"""Safe hosted readiness probes; configuration is distinct from connectivity."""
import asyncio
from sqlalchemy import text
from backend.app.core.config import get_settings
from backend.app.db.session import get_engine


async def record_worker_heartbeat(worker_id):
    engine = get_engine()
    if engine is None:
        return
    async with engine.begin() as conn:
        await conn.execute(text('''INSERT INTO worker_heartbeats (worker_id, seen_at)
            VALUES (:worker, now()) ON CONFLICT (worker_id) DO UPDATE SET seen_at=now()'''),
            {'worker': worker_id})


async def readiness():
    settings = get_settings()
    if settings.ENVIRONMENT not in {'staging', 'production'}:
        return {'status': 'local', 'database': 'optional', 'queue': 'local', 'storage': 'local',
                'worker': 'embedded' if settings.RUN_EMBEDDED_WORKER is not False else 'disabled',
                'sandbox': 'configured' if settings.DAYTONA_API_KEY and settings.DAYTONA_SANDBOX_IMAGE else 'unavailable',
                'provider': 'per-user configuration required'}
    result = {'database': 'unavailable', 'queue': 'unavailable', 'worker': 'unavailable', 'storage': 'unavailable',
              'sandbox': 'worker-managed; requires execution validation', 'provider': 'per-user configuration required'}
    try:
        async with asyncio.timeout(5):
            async with get_engine().connect() as conn:
                await conn.execute(text('SELECT ai_call_count FROM tasks LIMIT 0'))
                result['database'] = 'ready'
                queues = (await conn.execute(text('SELECT queue_name FROM pgmq.list_queues()'))).scalars().all()
                result['queue'] = 'ready' if settings.SUPABASE_QUEUE_NAME in queues else 'missing'
                alive = (await conn.execute(text("SELECT EXISTS(SELECT 1 FROM worker_heartbeats WHERE seen_at > now() - interval '90 seconds')"))).scalar()
                result['worker'] = 'ready' if alive else 'stale'
    except Exception:
        pass  # Response intentionally contains no exception text or connection data.
    try:
        from backend.app.storage.supabase_client import SupabaseStorageClient
        from urllib.parse import quote
        async with asyncio.timeout(5):
            client = SupabaseStorageClient(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
            bucket = (await client._request('GET', '/bucket/' + quote(settings.SUPABASE_STORAGE_BUCKET, safe=''))).json()
            result['storage'] = 'ready' if bucket.get('public') is False else 'unsafe_public_bucket'
    except Exception:
        pass
    result['status'] = 'ready' if all(result[key] == 'ready' for key in ('database', 'queue', 'worker', 'storage')) else 'not_ready'
    return result
