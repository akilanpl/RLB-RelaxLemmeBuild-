"""Atomicity and Staging Promotion Interfaces.

Establishes the lifecycle contracts and promotion boundaries:
  APPROVED -> create staging -> modify staging -> generate diff -> human approval -> atomically apply changes

Guarantees that:
1. The Approved Workspace represents canonical accepted state and is never modified directly by Coder runs.
2. Changes occur strictly within an isolated Staging Workspace.
3. Only upon explicit human code approval is the staging diff promoted to canonical storage.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from backend.app.models.workflow import Diff, CodeProposal, DiffType


class StagingDiffReport(BaseModel):
    """Unified diff report comparing Staging Workspace against Approved Canonical Workspace."""
    workspace_id: UUID
    staging_id: UUID
    base_snapshot_hash: str
    diffs: List[Diff] = []
    total_additions: int = 0
    total_deletions: int = 0
    modified_files_count: int = 0


class PromotionResult(BaseModel):
    """Result of atomically applying an approved code proposal to the canonical workspace."""
    workspace_id: UUID
    proposal_id: UUID
    new_snapshot_hash: str
    files_applied: int
    is_successful: bool
    error_message: Optional[str] = None


class BaseAtomicityService(ABC):
    """
    Service contract for computing staging diffs and applying atomic promotions.
    Full promotion state machine is orchestrated in Phase 5; this defines the core interfaces.
    """

    @abstractmethod
    async def generate_staging_diff(
        self, workspace_id: UUID, staging_id: UUID, user_id: UUID
    ) -> StagingDiffReport:
        """
        Compare the ephemeral staging workspace against canonical approved storage.
        Produces structured file diffs without mutating either workspace.
        """
        pass

    @abstractmethod
    async def apply_approved_proposal(
        self, workspace_id: UUID, staging_id: UUID, proposal_id: UUID, user_id: UUID
    ) -> PromotionResult:
        """
        Atomically promote approved staging changes into the canonical Approved Workspace.
        If promotion fails, transaction rolls back cleanly preserving previous canonical state.
        """
        pass
