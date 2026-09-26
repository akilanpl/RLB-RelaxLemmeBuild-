"""Base contracts for specialized agents."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Set
from uuid import UUID
from pydantic import BaseModel
from backend.app.models.agent import AgentRole


class AgentExecutionContext(BaseModel):
    task_id: UUID
    agent_run_id: UUID
    workspace_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    role: AgentRole
    workspace_root: str
    staging_root: Optional[str] = None
    user_prompt: str


class BaseAgent(ABC):
    """Abstract protocol for specialized agents."""

    @property
    @abstractmethod
    def role(self) -> AgentRole:
        pass

    @property
    def capabilities(self) -> Set[str]:
        return set()

    @property
    def allowed_tools(self) -> Set[str]:
        from backend.app.core.permissions import AgentPermissionGatekeeper
        return AgentPermissionGatekeeper.ROLE_PERMISSIONS[self.role]

    def validate_context(self, context: AgentExecutionContext) -> None:
        if context.role != self.role:
            raise ValueError("Execution context role does not match agent role.")

    async def run(self, context: AgentExecutionContext) -> Dict[str, Any]:
        self.validate_context(context)
        return await self.execute(context)

    @abstractmethod
    async def execute(self, context: AgentExecutionContext) -> Dict[str, Any]:
        """Execute the agent run within its permission-isolated boundary."""
        pass
