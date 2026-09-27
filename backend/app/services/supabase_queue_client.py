"""Trusted server-side Supabase Queue client using the pgmq extension.

Session advisory locks fence duplicate deliveries for a task and its workspace.
They are released on acknowledgement, failure, or a disconnected worker. Use the
Supabase direct or session-pooler connection, never the transaction pooler.
"""
import json
from uuid import UUID
from sqlalchemy import text


class SupabaseQueueClient:
    def __init__(self, engine, visibility_seconds=60):
        self.engine = engine
        self.visibility_seconds = visibility_seconds
        self.claims = {}

    async def send(self, name, payload):
        async with self.engine.begin() as conn:
            return (await conn.execute(text('SELECT pgmq.send(:name, CAST(:payload AS jsonb))'),
                                       {'name': name, 'payload': json.dumps(payload)})).scalar()

    async def claim(self, name, worker):
        conn = await self.engine.connect()
        retained = False
        try:
            row = (await conn.execute(text('SELECT * FROM pgmq.read(:name, :seconds, 1)'),
                                      {'name': name, 'seconds': self.visibility_seconds})).mappings().first()
            if not row:
                await conn.commit()
                return None
            receipt = row['msg_id']
            payload = row['message']
            if isinstance(payload, str):
                payload = json.loads(payload)
            try:
                task_id = UUID(payload['task_id'])
            except (KeyError, ValueError, TypeError):
                await conn.execute(text('SELECT pgmq.archive(:name, :id)'), {'name': name, 'id': receipt})
                await conn.commit()
                return None
            task = (await conn.execute(text('SELECT user_id, workspace_id FROM tasks WHERE id=:id'),
                                       {'id': task_id})).mappings().first()
            if not task:
                await conn.execute(text('SELECT pgmq.archive(:name, :id)'), {'name': name, 'id': receipt})
                await conn.commit()
                return None
            # A workspace cannot be promoted by one task while another codes it.
            locked = (await conn.execute(text('SELECT pg_try_advisory_lock(hashtextextended(:key, 0))'),
                                         {'key': 'rlb-workspace-' + str(task['workspace_id'])})).scalar()
            if not locked:
                await conn.execute(text('SELECT pgmq.set_vt(:name, :id, 5)'), {'name': name, 'id': receipt})
                await conn.commit()
                return None
            await conn.commit()
            self.claims[receipt] = (conn, worker)
            retained = True
            return {'receipt': receipt, 'message': payload, 'user_id': task['user_id'],
                    'attempts': row['read_ct']}
        finally:
            if not retained:
                try:
                    await conn.rollback()
                    await conn.execute(text('SELECT pg_advisory_unlock_all()'))
                    await conn.commit()
                finally:
                    await conn.close()

    async def extend(self, name, receipt, visibility_timeout):
        conn, _ = self.claims[receipt]
        result = (await conn.execute(text('SELECT * FROM pgmq.set_vt(:name, :id, :seconds)'),
                                    {'name': name, 'id': receipt, 'seconds': visibility_timeout})).first()
        await conn.commit()
        if result is None:
            raise RuntimeError('Queue message is no longer available.')

    async def _finish(self, name, receipt, archive):
        conn, _ = self.claims.pop(receipt)
        try:
            if archive:
                await conn.execute(text('SELECT pgmq.archive(:name, :id)'), {'name': name, 'id': receipt})
            else:
                await conn.execute(text('SELECT pgmq.set_vt(:name, :id, 5)'), {'name': name, 'id': receipt})
            await conn.commit()
        finally:
            try:
                await conn.rollback()
                await conn.execute(text('SELECT pg_advisory_unlock_all()'))
                await conn.commit()
            finally:
                await conn.close()

    async def ack(self, name, receipt):
        await self._finish(name, receipt, True)

    async def release(self, name, receipt, error):
        # A failed delivery remains retryable; approval pauses are acknowledged
        # by the adapter because the approval transaction emits a new message.
        await self._finish(name, receipt, False)

    async def close(self):
        for receipt in list(self.claims):
            conn, _ = self.claims.pop(receipt)
            try:
                await conn.rollback()
                await conn.execute(text('SELECT pg_advisory_unlock_all()'))
                await conn.commit()
            finally:
                await conn.close()
