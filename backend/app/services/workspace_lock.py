"""Fence API imports against other imports and the hosted workspace worker."""
import asyncio
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary
from sqlalchemy import text
from backend.app.db.session import get_engine

_locks = WeakValueDictionary()


@asynccontextmanager
async def workspace_import_lock(workspace_id):
    engine = get_engine()
    if engine is None:
        lock = _locks.setdefault(workspace_id, asyncio.Lock())
        async with lock:
            yield
        return
    async with engine.connect() as conn:
        locked = False
        try:
            locked = (await conn.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key,0))'),
                {'key': 'rlb-workspace-' + str(workspace_id)})).scalar()
            await conn.commit()
            if not locked:
                from backend.app.services.task_service import WorkflowConflictError
                raise WorkflowConflictError('Workspace is busy. Retry the import.')
            yield
        finally:
            await conn.rollback()
            if locked:
                await conn.execute(text('SELECT pg_advisory_unlock_all()'))
                await conn.commit()
