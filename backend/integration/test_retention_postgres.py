"""Run only against a disposable, explicitly supplied local/CI database.

Exercises migration 004 and retention SQL with real PostgreSQL, not Supabase services.
"""
import os
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from backend.app.services.artifact_cleanup import ArtifactCleanupRepository


@pytest.mark.asyncio
async def test_retention_migration_and_publication_fencing():
    url = os.environ.get('RLB_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL not configured')
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.execute('''
                CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
                CREATE SCHEMA storage;
                CREATE TABLE workspaces(id uuid PRIMARY KEY, canonical_root_path text NOT NULL);
                CREATE TABLE tasks(id uuid PRIMARY KEY, workspace_id uuid, status text);
                CREATE TABLE staging_workspaces(id uuid PRIMARY KEY, staging_root_path text,
                    task_id uuid, is_active boolean, discarded_at timestamptz);
                CREATE TABLE code_proposals(id uuid PRIMARY KEY, staging_workspace_id uuid);
                CREATE TABLE git_snapshots(id uuid PRIMARY KEY, workspace_id uuid);
                CREATE TABLE storage.objects(bucket_id text,name text,created_at timestamptz,updated_at timestamptz);
            ''')
            # Migration owns its transaction; execute outside this setup transaction below.
        async with engine.connect() as conn:
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.execute((Path(__file__).parents[2] / 'schema/migrations/004_artifact_retention.sql').read_text())
            await conn.commit()
        workspace = uuid4()
        canonical = f'workspaces/{workspace}/canonical'
        orphan = f'workspaces/{workspace}/snapshots/{uuid4()}'
        staging = f'workspaces/{workspace}/staging/{uuid4()}'
        async with engine.begin() as conn:
            await conn.execute(text('INSERT INTO workspaces VALUES (:id,:root)'), {'id':workspace,'root':canonical})
            for root in (canonical, orphan, staging):
                await conn.execute(text("INSERT INTO storage.objects VALUES ('workspace-artifacts',:path,now()-interval '8 days',now()-interval '8 days')"), {'path':root+'/app.py'})
        repo = ArtifactCleanupRepository(engine, 'workspace-artifacts')
        assert set(await repo.candidates(20)) == {canonical, orphan, staging}
        assert not await repo.retire(canonical)
        # Protected roots must not starve other candidates in bounded scans.
        assert (await repo.candidates(1))[0] != canonical
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO tasks VALUES (:id,:workspace,'coding')"), {'id':uuid4(),'workspace':workspace})
        assert not await repo.retire(orphan)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE tasks SET status='completed'"))
        assert await repo.retire(orphan)
        assert await repo.retire(orphan)  # restart/idempotence
        assert await repo.objects(orphan, 1) == [orphan+'/app.py']
        await repo.record(orphan, 0, error='TimeoutError')
        with pytest.raises(Exception, match='Artifact has been retired'):
            async with engine.begin() as conn:
                await conn.execute(text('UPDATE workspaces SET canonical_root_path=:root WHERE id=:id'), {'root':orphan,'id':workspace})
        # A published root stays protected even after replacement.
        published = f'workspaces/{workspace}/snapshots/{uuid4()}'
        async with engine.begin() as conn:
            await conn.execute(text('UPDATE workspaces SET canonical_root_path=:root WHERE id=:id'), {'root':published,'id':workspace})
            await conn.execute(text('UPDATE workspaces SET canonical_root_path=:root WHERE id=:id'), {'root':canonical,'id':workspace})
        assert not await repo.retire(published)
        async with engine.begin() as conn:
            await conn.execute(text('SET LOCAL ROLE authenticated'))
            with pytest.raises(Exception, match='permission denied'):
                await conn.execute(text('SELECT * FROM artifact_cleanup'))
    finally:
        await engine.dispose()
