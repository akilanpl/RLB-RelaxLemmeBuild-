"""Proposal persistence ports and adapters.

The in-memory adapter is intended for tests; configured production services use
the PostgreSQL adapter.
"""

import json
from typing import Dict, Optional, Protocol, List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models.workflow import CodeProposal


class ProposalRepository(Protocol):
    async def add(self, proposal: CodeProposal) -> CodeProposal: ...
    async def get(self, proposal_id: UUID) -> Optional[CodeProposal]: ...
    async def list_by_task(self, task_id: UUID) -> List[CodeProposal]: ...
    async def update(self, proposal: CodeProposal) -> CodeProposal: ...


class InMemoryProposalRepository:
    def __init__(self):
        self.proposals: Dict[UUID, CodeProposal] = {}

    async def add(self, proposal):
        self.proposals[proposal.id] = proposal
        return proposal

    async def get(self, proposal_id):
        return self.proposals.get(proposal_id)

    async def update(self, proposal):
        self.proposals[proposal.id] = proposal
        return proposal

    async def list_by_task(self, task_id):
        return sorted(
            (proposal for proposal in self.proposals.values() if proposal.task_id == task_id),
            key=lambda proposal: proposal.created_at,
            reverse=True,
        )


class PostgresProposalRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def add(self, proposal):
        async with self.sessions.begin() as session:
            await session.execute(text("""INSERT INTO code_proposals
                (id, task_id, agent_run_id, staging_workspace_id, summary, commit_message,
                 revision_number, base_snapshot_hash, status, impact, warnings, created_at)
                VALUES (:id,:task_id,:agent_run_id,:staging_workspace_id,:summary,:commit_message,
                 :revision_number,:base_snapshot_hash,:status,:impact,:warnings,:created_at)"""), {
                "id": proposal.id, "task_id": proposal.task_id, "agent_run_id": proposal.agent_run_id,
                "staging_workspace_id": proposal.staging_workspace_id, "summary": proposal.summary,
                "commit_message": proposal.commit_message, "revision_number": proposal.revision_number,
                "base_snapshot_hash": proposal.base_snapshot_hash, "status": proposal.status,
                "impact": json.dumps(proposal.impact), "warnings": json.dumps(proposal.warnings),
                "created_at": proposal.created_at,
            })
            for diff in proposal.diffs:
                await session.execute(text("""INSERT INTO diffs
                    (id,code_proposal_id,file_path,diff_type,unified_diff,additions_count,
                     deletions_count,created_at,before_content,after_content)
                    VALUES (:id,:proposal_id,:path,:kind,:diff,:additions,:deletions,:created_at,:before,:after)"""), {
                    "id": diff.id, "proposal_id": proposal.id, "path": diff.file_path,
                    "kind": diff.diff_type.value, "diff": diff.unified_diff,
                    "additions": diff.additions_count, "deletions": diff.deletions_count,
                    "created_at": diff.created_at, "before": diff.before_content,
                    "after": diff.after_content,
                })
        return proposal

    async def get(self, proposal_id):
        async with self.sessions() as session:
            row = (await session.execute(text("SELECT * FROM code_proposals WHERE id=:id"),
                                         {"id": proposal_id})).mappings().first()
            if not row:
                return None
            from datetime import timezone
            diffs = (await session.execute(text(
                "SELECT * FROM diffs WHERE code_proposal_id=:id ORDER BY created_at"
            ), {"id": proposal_id})).mappings().all()
            from backend.app.models.workflow import Diff, DiffType
            return CodeProposal(
                id=row["id"], task_id=row["task_id"], agent_run_id=row["agent_run_id"],
                staging_workspace_id=row["staging_workspace_id"], summary=row["summary"],
                commit_message=row["commit_message"], revision_number=row["revision_number"],
                base_snapshot_hash=row.get("base_snapshot_hash"),
                status=row.get("status") or "ready_for_review",
                impact=row.get("impact") or {}, warnings=row.get("warnings") or [],
                diffs=[Diff(id=d["id"], code_proposal_id=d["code_proposal_id"],
                            file_path=d["file_path"], diff_type=DiffType(d["diff_type"]),
                            unified_diff=d["unified_diff"],
                            additions_count=d["additions_count"],
                            deletions_count=d["deletions_count"],
                            created_at=d["created_at"],
                            before_content=d.get("before_content") or "",
                            after_content=d.get("after_content") or "") for d in diffs],
                created_at=row["created_at"],
            )

    async def update(self, proposal):
        async with self.sessions.begin() as session:
            await session.execute(text("""UPDATE code_proposals
                SET status=:status WHERE id=:id"""),
                {"id": proposal.id, "status": proposal.status})
        return proposal

    async def list_by_task(self, task_id):
        proposals = []
        async with self.sessions() as session:
            rows = (await session.execute(
                text("SELECT id FROM code_proposals WHERE task_id=:task_id ORDER BY created_at DESC"),
                {"task_id": task_id},
            )).scalars().all()
        for proposal_id in rows:
            proposal = await self.get(proposal_id)
            if proposal:
                proposals.append(proposal)
        return proposals
