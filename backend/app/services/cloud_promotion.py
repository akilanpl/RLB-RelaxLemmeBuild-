"""Publish immutable artifact snapshots with a transactional database pointer swap."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import text
from backend.app.models.task import ActorType, TransitionRecord
from backend.app.workflow.states import WorkflowState


async def promote_snapshot(sessions, storage, workspace, staging, proposal, task, user_id):
    # Write to a fresh prefix. No existing approved object is overwritten/deleted.
    root = f'workspaces/{workspace.id}/snapshots/{uuid4()}'
    files = []
    digest = hashlib.sha256()
    prefix = staging.staging_root_path.rstrip('/') + '/'
    try:
        for path in sorted(await storage.list_files(staging.staging_root_path)):
            if not path.startswith(prefix):
                raise ValueError('Staging file escaped snapshot prefix.')
            relative = path[len(prefix):]
            content = await storage.read_file(path)
            await storage.write_file(f'{root}/{relative}', content)
            digest.update(relative.encode() + b'\0' + content + b'\0')
            files.append({'path': relative, 'size': len(content), 'hash': hashlib.sha256(content).hexdigest()})
    except BaseException:
        # No database pointer exists yet: only this unpublished prefix is safe to remove.
        try:
            await storage.delete_directory(root)
        except Exception:
            pass  # Retention tooling can retry unreferenced objects later.
        raise
    snapshot = digest.hexdigest()
    now = datetime.now(timezone.utc)
    transition = TransitionRecord(id=uuid4(), task_id=task.id,
        previous_state=task.status, new_state=WorkflowState.TEST_PLANNING,
        actor_type=ActorType.SYSTEM if task.status == WorkflowState.PROMOTING else ActorType.USER, actor_id=user_id, reason='approved code',
        metadata={'proposal_id': str(proposal.id), 'snapshot': snapshot}, timestamp=now,
        task_version_before=task.version, task_version_after=task.version + 1)
    async with sessions.begin() as session:
        current = (await session.execute(text('''
            SELECT w.current_snapshot_hash, t.status, t.version, p.status AS proposal_status
            FROM workspaces w JOIN tasks t ON t.workspace_id=w.id
            JOIN code_proposals p ON p.task_id=t.id
            WHERE w.id=:workspace AND w.user_id=:user AND t.id=:task AND p.id=:proposal
            FOR UPDATE OF w, t, p
        '''), {'workspace': workspace.id, 'user': user_id, 'task': task.id,
               'proposal': proposal.id})).mappings().first()
        if (not current or current['status'] != task.status.value or current['version'] != task.version
                or current['proposal_status'] != 'ready_for_review'
                or (current['current_snapshot_hash'] or 'empty-root') != (proposal.base_snapshot_hash or 'empty-root')):
            raise ValueError('Workspace or proposal changed before approval. Reload the review.')
        await session.execute(text('''UPDATE workspaces SET canonical_root_path=:root,
            current_snapshot_hash=:hash, file_count=:count, total_size_bytes=:size,
            updated_at=:now WHERE id=:id'''), {'root': root, 'hash': snapshot,
            'count': len(files), 'size': sum(f['size'] for f in files), 'now': now, 'id': workspace.id})
        await session.execute(text('UPDATE files SET is_deleted=TRUE WHERE workspace_id=:id'), {'id': workspace.id})
        for file in files:
            await session.execute(text('''INSERT INTO files
                (id,workspace_id,relative_path,file_type,size_bytes,sha256_hash,is_deleted)
                VALUES (:id,:workspace,:path,'file',:size,:hash,FALSE)
                ON CONFLICT (workspace_id,relative_path) DO UPDATE SET
                    size_bytes=EXCLUDED.size_bytes,sha256_hash=EXCLUDED.sha256_hash,
                    is_deleted=FALSE,updated_at=NOW()'''), {**file, 'id': uuid4(), 'workspace': workspace.id})
        if task.status == WorkflowState.CODE_REVIEW:
            await session.execute(text('''INSERT INTO approvals
                (id,task_id,gate_type,status,reviewed_by,created_at,resolved_at)
                VALUES (:id,:task,'code','approved',:user,:now,:now)'''),
                {'id': uuid4(), 'task': task.id, 'user': user_id, 'now': now})
        await session.execute(text("UPDATE code_proposals SET status='applied' WHERE id=:id"), {'id': proposal.id})
        await session.execute(text('''UPDATE tasks SET status='test_planning', version=version+1,
            approved_snapshot_hash=:hash, updated_at=:now WHERE id=:id'''),
            {'id': task.id, 'hash': snapshot, 'now': now})
        await session.execute(text('''INSERT INTO execution_logs (id,task_id,source,stream,log_line,logged_at)
            VALUES (:id,:task,'system','workflow',:line,:now)'''),
            {'id': uuid4(), 'task': task.id, 'line': transition.model_dump_json(), 'now': now})
        await session.execute(text('''INSERT INTO git_snapshots
            (id,workspace_id,task_id,commit_sha,tree_sha,parent_commit_sha,message)
            VALUES (:id,:workspace,:task,:hash,:hash,:parent,:message)'''),
            {'id': uuid4(), 'workspace': workspace.id, 'task': task.id, 'hash': snapshot,
             'parent': workspace.current_snapshot_hash, 'message': proposal.commit_message})
    return {'proposal_id': proposal.id, 'new_snapshot_hash': snapshot,
            'files_applied': len(files), 'is_successful': True}
