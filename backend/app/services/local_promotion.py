"""Resume a human-approved local promotion after any persisted boundary."""
import asyncio
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from backend.app.models.workspace import Workspace
from backend.app.models.task import ActorType
from backend.app.workflow.states import WorkflowState
from backend.app.services.coder_service import SnapshotConflictError, _same_snapshot, _snapshot
from backend.app.services.workspace_service import _MEMORY_FILES, _MEMORY_WORKSPACES


async def promote_local(coder, workspace, staging, proposal, task, user_id):
    store = coder.workflow.repository._store
    key = "promotion:" + str(proposal.id)
    journal = await store.load(key)
    service = coder.staging_service.workspace_service
    storage = service.storage
    current = await coder.workflow.get_task(task.id, user_id)
    if (current.status != WorkflowState.PROMOTING and not (journal and current.status in {WorkflowState.CANCELLED, WorkflowState.FAILED})) or current.approved_proposal_id != proposal.id:
        raise SnapshotConflictError("Promotion requires the persisted human approval.")
    if journal is None:
        if not _same_snapshot(workspace.current_snapshot_hash, proposal.base_snapshot_hash):
            raise SnapshotConflictError("Approved workspace changed since review.")
        root = f"workspaces/{workspace.id}/snapshots/{uuid4()}"
        prefix = staging.staging_root_path.rstrip('/') + '/'
        contents = {}
        for path in await storage.list_files(staging.staging_root_path):
            relative = path[len(prefix):]
            content = await storage.read_file(path)
            contents[relative] = content
            await storage.write_file(f"{root}/{relative}", content)
        journal = {
            "previous_workspace": workspace.model_dump_json(),
            "previous_files": [dict(item) for item in _MEMORY_FILES.get(workspace.id, [])],
            "root": root, "snapshot_hash": _snapshot(contents.items()), "published": False,
        }
        # The complete immutable intent is committed BEFORE any selected-folder mutation.
        await store.save(key, journal)
    previous = Workspace.model_validate_json(journal["previous_workspace"])
    contents = {}
    prefix = journal["root"].rstrip('/') + '/'
    for path in await storage.list_files(journal["root"]):
        contents[path[len(prefix):]] = await storage.read_file(path)
    if _snapshot(contents.items()) != journal["snapshot_hash"]:
        raise SnapshotConflictError("Persisted promotion snapshot changed.")
    if previous.local_path:
        project = Path(previous.local_path).resolve(strict=True)
        old_hashes = {r["relative_path"]: r["sha256_hash"] for r in journal["previous_files"]}
        new_hashes = {path: hashlib.sha256(value).hexdigest() for path, value in contents.items()}
        # A crash may leave the writer's temporary file before its atomic rename.
        for relative in set(old_hashes) | set(new_hashes):
            destination = service._safe_local_path(project, relative)
            if destination.parent.is_dir():
                for temporary in destination.parent.glob(f".{destination.name}.rlb-*"):
                    if re.fullmatch(re.escape('.' + destination.name + '.rlb-') + '[0-9a-f]{32}', temporary.name):
                        if not temporary.is_symlink() and temporary.is_file():
                            temporary.unlink()
        entries = service._scan_local_project(project)
        actual = {item["relative_path"]: hashlib.sha256(item["content"]).hexdigest() for item in entries}
        for path in set(actual) | set(old_hashes) | set(new_hashes):
            if actual.get(path) not in {old_hashes.get(path), new_hashes.get(path)}:
                raise SnapshotConflictError("The local project changed during promotion; external edits were preserved.")
        await asyncio.to_thread(
            service._write_local_snapshot_files, project, contents, journal["previous_files"],
        )
    # Rebuild snapshot metadata without performing a second selected-folder write.
    candidate = previous.model_copy(update={"canonical_root_path": journal["root"]})
    synced = await service.sync_canonical_metadata(candidate, publish_local=False)
    synced = synced.model_copy(update={"local_path": previous.local_path})
    _MEMORY_WORKSPACES[synced.id] = synced
    service._persist_local_registration(synced, _MEMORY_FILES[synced.id])
    journal["published"] = True
    await store.save(key, journal)
    current = await coder.workflow.get_task(task.id, user_id)
    if current.status not in {WorkflowState.CANCELLED, WorkflowState.FAILED}:
        await coder.workflow.transition(task.id, WorkflowState.TEST_PLANNING, ActorType.SYSTEM, None,
            "Approved local snapshot promoted", {"snapshot": synced.current_snapshot_hash}, expected_version=current.version)
    proposal.status = "applied"
    await coder.proposals.update(proposal)
    return {"proposal_id": proposal.id, "new_snapshot_hash": synced.current_snapshot_hash,
            "files_applied": len(contents), "is_successful": True}
