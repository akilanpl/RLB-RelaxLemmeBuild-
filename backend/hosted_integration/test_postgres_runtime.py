"""Disposable PostgreSQL + real pgmq contract checks; no cloud credentials."""
import asyncio
import os
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.app.services.workspace_service import WorkspaceService
from backend.app.storage.local import LocalStorageBackend
from backend.app.repositories.task import PostgresTaskRepository
from backend.app.repositories.testing import PostgresTestingRepository
from backend.app.services.task_service import WorkflowEngine
from backend.app.services.supabase_queue_client import SupabaseQueueClient
from backend.app.models.task import ActorType
from backend.app.models.agent import AgentRole
from backend.app.models.test import TestExecution as Execution
from backend.app.workflow.states import WorkflowState as State
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_real_postgres_queue_events_approval_and_rls(tmp_path, monkeypatch):
    url = os.environ.get('RLB_TEST_DATABASE_URL')
    if not url: pytest.skip('Disposable pgmq PostgreSQL not configured')
    engine = create_async_engine(url, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    root = Path(__file__).parents[2]
    try:
        async with engine.connect() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.execute('''CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
                CREATE SCHEMA auth; CREATE SCHEMA storage;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO authenticated;
                CREATE TABLE auth.users(id uuid PRIMARY KEY,email text,raw_user_meta_data jsonb);
                CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
                $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
                CREATE TABLE storage.objects(bucket_id text,name text,created_at timestamptz,updated_at timestamptz);
            ''')
            await raw.execute((root/'schema/supabase_schema.sql').read_text())
            await raw.execute('GRANT USAGE ON SCHEMA public,auth TO authenticated; GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated;')
            for path in sorted((root/'schema/migrations').glob('*.sql')):
                await raw.execute(path.read_text())
        monkeypatch.setattr('backend.app.services.workspace_service.get_sessionmaker',lambda:sessions)
        workspaces = WorkspaceService(LocalStorageBackend(tmp_path))
        owner, other = uuid4(), uuid4()
        workspace = await workspaces.create_workspace(owner,'SQL contract')
        foreign = await workspaces.create_workspace(other,'Other tenant')
        workflow = WorkflowEngine(workspaces, PostgresTaskRepository(sessions))
        task = await workflow.create_task(workspace,owner,'SQL','Verify durable recovery')
        queue = SupabaseQueueClient(engine)
        duplicate = SupabaseQueueClient(engine)
        delivery = await queue.claim('task_execution','one')
        assert delivery['message']['task_id'] == str(task.id)
        await queue.extend('task_execution',delivery['receipt'],60)
        await queue.send('task_execution',delivery['message'])
        assert await duplicate.claim('task_execution','two') is None
        await queue.close()  # Abrupt process disconnect releases its advisory lock.
        async with engine.begin() as conn:
            await conn.execute(text("SELECT pgmq.set_vt('task_execution',:id,0)"),{'id':delivery['receipt']})
        reclaimed = await duplicate.claim('task_execution','restarted')
        assert reclaimed['receipt'] == delivery['receipt']
        assert reclaimed['attempts'] == 2
        await duplicate.ack('task_execution',reclaimed['receipt'])
        recovered = WorkflowEngine(workspaces, PostgresTaskRepository(sessions))
        assert (await recovered.get_task(task.id,owner)).status == State.READY
        await recovered.transition(task.id,State.PLANNING,ActorType.SYSTEM,None,'plan')
        await recovered.transition(task.id,State.PLAN_REVIEW,ActorType.SYSTEM,None,'review')
        results = await asyncio.gather(*[recovered.record_approval(task.id,owner,'plan','approved',None,defer_setup=True) for _ in range(2)],return_exceptions=True)
        assert sum(not isinstance(r,BaseException) for r in results) == 1
        run = await recovered.create_agent_run(task.id,owner,AgentRole.TEST_EXECUTOR)
        repo = PostgresTestingRepository(sessions)
        execution = Execution(id=uuid4(),task_id=task.id,agent_run_id=run.id,created_at=datetime.now(timezone.utc))
        await repo.add_execution(execution)
        command = {'command_id':str(uuid4()),'status':'running','stdout':'first'}
        await repo.add_command_result(execution.id,command)
        command.update(status='success',stdout='done')
        await repo.add_command_result(execution.id,command)
        assert len((await repo.list_executions(task.id))[0].command_results) == 1
        async with engine.connect() as conn:
            events=(await conn.execute(text('SELECT event_type FROM task_events WHERE task_id=:id ORDER BY sequence'),{'id':task.id})).scalars().all()
            assert 'command.running' in events and 'command.success' in events
        # Uncommitted entity events cannot be skipped by a concurrently committed cursor.
        a,b = await engine.connect(),await engine.connect()
        try:
            await a.execute(text("UPDATE test_executions SET total_tests=1 WHERE id=:id"),{'id':execution.id})
            pending=asyncio.create_task(b.execute(text("UPDATE agent_runs SET execution_status='running' WHERE id=:id"),{'id':run.id}))
            await asyncio.sleep(.1)
            assert not pending.done()
            await a.commit();await pending;await b.commit()
        finally:
            await a.close();await b.close()
        async with engine.begin() as conn:
            await conn.execute(text('SET LOCAL ROLE authenticated'))
            await conn.execute(text("SELECT set_config('request.jwt.claim.sub',:id,true)"),{'id':str(other)})
            visible=(await conn.execute(text('SELECT id FROM workspaces'))).scalars().all()
            assert foreign.id in visible and workspace.id not in visible
            assert not (await conn.execute(text('SELECT sequence FROM task_events WHERE task_id=:id'),{'id':task.id})).all()
    finally:
        await engine.dispose()
