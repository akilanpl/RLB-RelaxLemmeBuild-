"""Coder agent contract: staging-scoped file modifications and diff generation."""

from backend.app.agents.base import BaseAgent, AgentExecutionContext
from backend.app.models.agent import AgentRole
from backend.app.models.workflow import CodeProposal


class CoderAgent(BaseAgent):
    """
    CODER Role:
    - Reads approved plan and codebase.
    - Creates/edits files strictly inside the Staging Workspace.
    - Produces a proposed diff for human review.
    - Strict Invariant: Cannot write to Approved Workspace or execute shell commands.
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.CODER

    async def execute(self, context: AgentExecutionContext) -> CodeProposal:
        from backend.app.services.runtime import get_runtime
        return await get_runtime().agents.coder.execute(context.task_id, context.user_id)
