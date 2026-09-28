"""Conservative, restart-safe retention using a durable deletion ledger.

Never mutate storage.objects directly: all deletion goes through Storage API.
Legacy snapshots without artifact paths are retained for audit, not guessed.
"""
import asyncio
import logging
import re
from sqlalchemy import text

ROOT = re.compile(r'^workspaces/([0-9a-f-]{36})/(canonical|(?:staging|snapshots)/[0-9a-f-]{36})$')
log = logging.getLogger(__name__)


def protected(root, workspace, staging, active_tasks, audit_roots, legacy_audit=False):
    """Fail closed for unknown layouts and every canonical/active/audit reference."""
    if not ROOT.fullmatch(root):
        return True
    if workspace and (root == workspace['canonical_root_path'] or root.endswith('/canonical')):
        return True
    if active_tasks or root in audit_roots:
        return True
    if '/snapshots/' in root and legacy_audit:
        return True
    # Task-linked staging is evidence, including after task completion.
    if staging and staging.get('task_id') is not None:
        return True
    return False


class ArtifactCleanupRepository:
    def __init__(self, engine, bucket, retention_days=7):
        self.engine, self.bucket, self.days = engine, bucket, retention_days

    async def candidates(self, limit):
        async with self.engine.connect() as conn:
            # Oldest first, including unfinished tombstones after interrupted deletion.
            return (await conn.execute(text('''
                SELECT root FROM (
                  SELECT root_path AS root, created_at AS age FROM artifact_cleanup
                  WHERE completed_at IS NULL
                  UNION
                  SELECT concat_ws('/', split_part(name,'/',1), split_part(name,'/',2),
                    split_part(name,'/',3), CASE WHEN split_part(name,'/',3) <> 'canonical'
                      THEN split_part(name,'/',4) END) AS root, min(created_at) AS age
                  FROM storage.objects WHERE bucket_id=:bucket AND name LIKE 'workspaces/%'
                  GROUP BY root HAVING max(greatest(created_at,updated_at)) < now() - :days * interval '1 day'
                ) candidates LEFT JOIN artifact_retention_scans scans ON scans.root_path=candidates.root
                ORDER BY coalesce(scans.checked_at,'epoch'::timestamptz),age LIMIT :limit
            '''), {'bucket': self.bucket, 'days': self.days, 'limit': limit})).scalars().all()

    async def retire(self, root):
        match = ROOT.fullmatch(root)
        if not match:
            return False
        async with self.engine.begin() as conn:
            # Same lock as the durable worker: no retirement during active execution.
            if not (await conn.execute(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))'),
                    {'key': 'rlb-workspace-' + match[1]})).scalar():
                return False
            params = {'workspace': match[1], 'root': root}
            await conn.execute(text('INSERT INTO artifact_retention_scans(root_path) VALUES (:root) ON CONFLICT(root_path) DO UPDATE SET checked_at=now()'), params)
            workspace = (await conn.execute(text('SELECT canonical_root_path FROM workspaces WHERE id=CAST(:workspace AS uuid) FOR UPDATE'), params)).mappings().first()
            staging = (await conn.execute(text('SELECT id,task_id FROM staging_workspaces WHERE staging_root_path=:root FOR UPDATE'), params)).mappings().first()
            active = (await conn.execute(text("SELECT EXISTS(SELECT 1 FROM tasks WHERE workspace_id=CAST(:workspace AS uuid) AND status NOT IN ('completed','failed','cancelled'))"), params)).scalar()
            audits = (await conn.execute(text('SELECT artifact_root_path FROM git_snapshots WHERE workspace_id=CAST(:workspace AS uuid) UNION SELECT root_path FROM artifact_audit_roots WHERE workspace_id=CAST(:workspace AS uuid)'), params)).scalars().all()
            if protected(root, workspace, staging, active, audits, None in audits):
                return False
            if staging:
                # Even malformed historical task links must not erase proposal evidence.
                if (await conn.execute(text('SELECT EXISTS(SELECT 1 FROM code_proposals WHERE staging_workspace_id=:id)'), {'id': staging['id']})).scalar():
                    return False
                await conn.execute(text('UPDATE staging_workspaces SET is_active=false, discarded_at=coalesce(discarded_at,now()) WHERE id=:id'), {'id': staging['id']})
            await conn.execute(text('INSERT INTO artifact_cleanup(root_path) VALUES (:root) ON CONFLICT DO NOTHING'), params)
            return True

    async def objects(self, root, limit):
        async with self.engine.connect() as conn:
            return (await conn.execute(text('SELECT name FROM storage.objects WHERE bucket_id=:bucket AND starts_with(name,:prefix) ORDER BY name LIMIT :limit'),
                {'bucket': self.bucket, 'prefix': root + '/', 'limit': limit})).scalars().all()

    async def record(self, root, deleted, error=None, complete=False):
        async with self.engine.begin() as conn:
            await conn.execute(text('''UPDATE artifact_cleanup SET last_attempt_at=now(),
                deleted_objects=deleted_objects+:deleted,last_error=:error,
                completed_at=CASE WHEN :complete THEN now() ELSE NULL END WHERE root_path=:root'''),
                {'root': root, 'deleted': deleted, 'error': error, 'complete': complete})


class ArtifactCleaner:
    def __init__(self, repository, storage):
        self.repository, self.storage = repository, storage

    async def run_once(self, roots=20, objects=100):
        deleted = 0
        for root in await self.repository.candidates(roots):
            if not await self.repository.retire(root):
                continue
            count = 0
            try:
                # Exact paths from the DB, never an unbounded recursive deletion.
                paths = await self.repository.objects(root, objects)
                for path in paths:
                    if not path.startswith(root + '/') or '..' in path.split('/'):
                        raise ValueError('Unsafe cleanup object path')
                    await self.storage.delete_file(path)
                    count += 1
                await self.repository.record(root, count, complete=len(paths) < objects)
            except Exception as exc:
                await self.repository.record(root, count, error=type(exc).__name__)
                log.warning('Artifact cleanup retry root=%s error=%s', root, type(exc).__name__)
            deleted += count
        log.info('Artifact cleanup deleted_objects=%s', deleted)
        return deleted


async def cleanup_loop(engine, storage, settings):
    cleaner = ArtifactCleaner(ArtifactCleanupRepository(engine, settings.SUPABASE_STORAGE_BUCKET,
        settings.ARTIFACT_RETENTION_DAYS), storage)
    while True:
        try:
            async with asyncio.timeout(120):
                await cleaner.run_once()
        except Exception as exc:
            log.error('Artifact cleanup pass failed error=%s', type(exc).__name__)
        await asyncio.sleep(settings.ARTIFACT_CLEANUP_INTERVAL_SECONDS)
