"""Workflow engine protocol: orchestrates transitions and approval gates."""

from abc import ABC, abstractmethod
from uuid import UUID
from typing import Optional
from backend.app.workflow.states import WorkflowState, WorkflowEvent
from backend.app.models.workflow import Task


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is requested."""
    pass


class BaseWorkflowEngine(ABC):
    """Interface for driving tasks through the approval-gated state machine."""

    @abstractmethod
    async def transition(
        self, 
        task_id: UUID, 
        event: WorkflowEvent, 
        payload: Optional[dict] = None
    ) -> Task:
        """Advance the task state machine deterministically."""
        pass

    @abstractmethod
    async def get_current_state(self, task_id: UUID) -> WorkflowState:
        """Fetch the current persisted state of a task."""
        pass
