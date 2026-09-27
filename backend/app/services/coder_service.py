"""Coder orchestration, deterministic proposals, and atomic approval application."""

import difflib
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID, uuid4

from backend.app.ai.gateway import AIGateway, AIRequest
from backend.app.ai.groq import GroqGateway
from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.coder import ChangeOperation, CodeChangeSet
from backend.app.models.task import ActorType
from backend.app.models.workflow import CodeProposal, Diff, DiffType
from backend.app.services.coder_context import CoderContextBuilder
from backend.app.services.staging_service import StagingService
from backend.app.services.task_service import workflow_engine
from backend.app.repositories.proposal import (
    InMemoryProposalRepository, PostgresProposalRepository, ProposalRepository,
)
from backend.app.db.session import get_sessionmaker
from backend.app.core.config import get_settings
from backend.app.workflow.states import WorkflowState


def _same_snapshot(left: Optional[str], right: Optional[str]) -> bool:
    def normalize(value: Optional[str]) -> str:
        return value or "empty-root"
    return normalize(left) == normalize(right)


def _snapshot(paths_and_contents) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(paths_and_contents):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


class CoderExecutionError(RuntimeError):
    pass


class SnapshotConflictError(CoderExecutionError):
    pass


class CoderService:
    def __init__(self, gateway: Optional[AIGateway] = None, staging_service=None,
                 context_builder=None, workflow=None, proposal_repository: Optional[ProposalRepository] = None,
                 gateway_resolver=None, runtime_resolver=None):
        self.workflow = workflow or workflow_engine
        self.gateway = gateway or GroqGateway()
        self.gateway_resolver = gateway_resolver
        self.runtime_resolver = runtime_resolver
        self.staging_service = staging_service or StagingService(
            workspace_service=self.workflow.workspace_service
        )
        self.context_builder = context_builder or CoderContextBuilder(self.staging_service)
        sessions = get_sessionmaker()
        if proposal_repository is not None:
            self.proposals = proposal_repository
        elif sessions is not None:
            self.proposals = PostgresProposalRepository(sessions)
        else:
            self.proposals = InMemoryProposalRepository()

    async def execute(self, task_id: UUID, user_id: UUID, staging_id: Optional[UUID] = None,
                      revision_feedback: Optional[str] = None) -> CodeProposal:
        task = await self.workflow.get_task(task_id, user_id)
        if task.status != WorkflowState.CODING:
            raise CoderExecutionError("Task must be in CODING before Coder execution.")
        proposals = await self.proposals.list_by_task(task_id)
        latest = proposals[0] if proposals else None
        if (not revision_feedback and latest is not None
                and latest.status == "ready_for_review"
                and latest.created_at >= task.updated_at):
            return latest
        staging_id = staging_id or task.active_staging_workspace_id
        if staging_id is None:
            raise CoderExecutionError("An active staging workspace is required.")
        try:
            runtime = (self.runtime_resolver.resolve(
                user_id, task.workspace_id, task.id, AgentRole.CODER.value
            ) if self.runtime_resolver else None)
        except (LookupError, PermissionError) as exc:
            raise CoderExecutionError(str(exc)) from exc
        run = await self.workflow.create_agent_run(
            task_id, user_id, AgentRole.CODER,
            **(runtime.run_metadata() if runtime else {}),
        )
        gateway = runtime.gateway if runtime else (
            self.gateway_resolver(task, user_id) if self.gateway_resolver else self.gateway
        )
        await self.workflow.update_agent_run(run.id, ExecutionStatus.RUNNING)
        try:
            context = await self.context_builder.build(task, staging_id)
            context["approved_plans"] = [p.model_dump(mode="json") for p in
                await self.workflow.list_plans(task_id, user_id)]
            response = await gateway.generate(AIRequest(
                system_prompt="Return only JSON matching this schema. Changes are staging-only. " + json.dumps(CodeChangeSet.model_json_schema()),
                user_prompt=json.dumps({"context": context, "revision_feedback": revision_feedback},
                                        sort_keys=True),
            ))
            try:
                change_set = CodeChangeSet.model_validate_json(response.content)
            except (ValueError, TypeError) as exc:
                raise CoderExecutionError("Coder returned invalid structured output.") from exc
            await self._apply_staging_changes(staging_id, user_id, change_set)
            proposal = await self.propose(task, user_id, staging_id, run.id, change_set)
            await self.workflow.update_agent_run(run.id, ExecutionStatus.SUCCESS,
                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
                metadata=response.metadata)
            return proposal
        except Exception as exc:
            await self.workflow.update_agent_run(run.id, ExecutionStatus.FAILED,
                                                 metadata={"error": str(exc)})
            if isinstance(exc, CoderExecutionError):
                raise
            raise CoderExecutionError("Coder execution failed.") from exc

    async def _apply_staging_changes(self, staging_id, user_id, change_set):
        for change in sorted(change_set.changes, key=lambda c: c.path):
            path = change.path.replace("\\", "/").lstrip("/")
            if ".." in path.split("/"):
                raise CoderExecutionError("Unsafe change path.")
            if change.operation == ChangeOperation.DELETE:
                await self.staging_service.delete_staging_file(staging_id, path, user_id)
            else:
                if change.content is None:
                    raise CoderExecutionError(f"Content required for {change.operation.value}.")
                await self.staging_service.write_staging_file(
                    staging_id, path, change.content.encode("utf-8"), user_id)

    async def propose(self, task, user_id, staging_id, run_id, change_set) -> CodeProposal:
        staging = await self.staging_service.get_staging_workspace(staging_id, user_id)
        before = {}
        for path in await self.staging_service.workspace_service.list_workspace_files(task.workspace_id, user_id):
            try:
                before[path["relative_path"]] = await self.staging_service.workspace_service.read_workspace_file(
                    task.workspace_id, path["relative_path"], user_id)
            except FileNotFoundError:
                pass
        after = {path: await self.staging_service.read_staging_file(staging_id, path, user_id)
                 for path in await self.staging_service.list_staging_files(staging_id, user_id)}
        diffs = []
        for path in sorted(set(before) | set(after)):
            old, new = before.get(path), after.get(path)
            if old == new:
                continue
            typ = DiffType.ADDED if old is None else DiffType.DELETED if new is None else DiffType.MODIFIED
            text = "".join(difflib.unified_diff(
                (old or b"").decode("utf-8", "replace").splitlines(True),
                (new or b"").decode("utf-8", "replace").splitlines(True),
                fromfile=f"a/{path}", tofile=f"b/{path}"))
            diffs.append(Diff(id=uuid4(), code_proposal_id=UUID(int=0), file_path=path,
                              diff_type=typ, unified_diff=text,
                              additions_count=sum(1 for l in text.splitlines() if l.startswith("+") and not l.startswith("+++")),
                              deletions_count=sum(1 for l in text.splitlines() if l.startswith("-") and not l.startswith("---")),
                              created_at=datetime.now(timezone.utc),
                              before_content=(old or b"").decode("utf-8", "replace"),
                              after_content=(new or b"").decode("utf-8", "replace")))
        proposal_id = uuid4()
        diffs = [d.model_copy(update={"code_proposal_id": proposal_id}) for d in diffs]
        proposal = CodeProposal(
            id=proposal_id, task_id=task.id, agent_run_id=run_id,
            staging_workspace_id=staging_id, summary=change_set.summary,
            commit_message=change_set.commit_message, diffs=diffs,
            base_snapshot_hash=staging.base_snapshot_hash,
            impact=change_set.impact.model_dump(mode="json"),
            created_at=datetime.now(timezone.utc),
        )
        return await self.proposals.add(proposal)

    async def approve_and_apply(self, proposal_id: UUID, user_id: UUID):
        proposal = await self.proposals.get(proposal_id)
        if not proposal:
            raise CoderExecutionError("Code proposal not found.")
        if proposal.status == "applied":
            raise CoderExecutionError("Code proposal has already been applied.")
        task = await self.workflow.get_task(proposal.task_id, user_id)
        if task.status != WorkflowState.CODE_REVIEW or proposal.status != "ready_for_review":
            raise CoderExecutionError("Code proposal is not awaiting approval.")
        staging = await self.staging_service.get_staging_workspace(proposal.staging_workspace_id, user_id)
        ws = await self.staging_service.workspace_service.get_workspace(task.workspace_id, user_id)
        if not _same_snapshot(ws.current_snapshot_hash, proposal.base_snapshot_hash):
            raise SnapshotConflictError("Approved workspace changed since staging was created.")
        storage = self.staging_service.storage
        sessions = get_sessionmaker()
        if sessions is not None:
            from backend.app.services.cloud_promotion import promote_snapshot
            try:
                return await promote_snapshot(sessions, storage, ws, staging, proposal, task, user_id)
            except ValueError as exc:
                raise SnapshotConflictError(str(exc)) from exc
        canonical = await storage.list_files(ws.canonical_root_path)
        backup = {p: await storage.read_file(p) for p in canonical}
        from backend.app.services.workspace_service import _MEMORY_FILES
        previous_files = [dict(item) for item in _MEMORY_FILES.get(ws.id, [])]
        old_snapshot_hash = ws.current_snapshot_hash
        try:
            staged = await storage.list_files(staging.staging_root_path)
            for p in canonical:
                await storage.delete_file(p)
            for p in staged:
                rel = p[len(staging.staging_root_path) + 1:]
                await storage.write_file(f"{ws.canonical_root_path}/{rel}", await storage.read_file(p))
            new_files = [(p[len(ws.canonical_root_path) + 1:], await storage.read_file(p)) for p in await storage.list_files(ws.canonical_root_path)]
            ws.current_snapshot_hash = _snapshot(new_files) if new_files else (ws.current_snapshot_hash or "empty-root")
            ws.updated_at = datetime.now(timezone.utc)
            synced = await self.staging_service.workspace_service.sync_canonical_metadata(ws)
            ws.current_snapshot_hash = synced.current_snapshot_hash
            ws.file_count = synced.file_count
            ws.total_size_bytes = synced.total_size_bytes
            await self.workflow.record_approval(task.id, user_id, "code", "approved", None)
            proposal.status = "applied"
            await self.proposals.update(proposal)
            return {"proposal_id": proposal_id, "new_snapshot_hash": ws.current_snapshot_hash,
                    "files_applied": len(staged), "is_successful": True}
        except Exception:
            for p in await storage.list_files(ws.canonical_root_path):
                await storage.delete_file(p)
            for p, content in backup.items():
                await storage.write_file(p, content)
            ws.current_snapshot_hash = old_snapshot_hash
            await self.staging_service.workspace_service.replace_tracked_files(
                ws, previous_files, old_snapshot_hash
            )
            proposal.status = "failed"
            await self.proposals.update(proposal)
            raise

    async def request_revision(self, proposal_id: UUID, user_id: UUID, feedback: str):
        proposal = await self.proposals.get(proposal_id)
        if proposal is None:
            raise CoderExecutionError("Code proposal not found.")
        task = await self.workflow.get_task(proposal.task_id, user_id)
        if task.status != WorkflowState.CODE_REVIEW:
            raise CoderExecutionError("Code proposal is not awaiting review.")
        await self.workflow.record_approval(
            task.id, user_id, "code", "revision_requested", feedback
        )
        proposal.status = "revision_requested"
        await self.proposals.update(proposal)
        return proposal

    async def reject(self, proposal_id: UUID, user_id: UUID):
        proposal = await self.proposals.get(proposal_id)
        if proposal is None:
            raise CoderExecutionError("Code proposal not found.")
        task = await self.workflow.get_task(proposal.task_id, user_id)
        await self.workflow.record_approval(task.id, user_id, "code", "rejected", None)
        proposal.status = "rejected"
        await self.proposals.update(proposal)
        await self.staging_service.discard_staging_workspace(
            proposal.staging_workspace_id, user_id
        )
        return proposal


coder_service = CoderService()
