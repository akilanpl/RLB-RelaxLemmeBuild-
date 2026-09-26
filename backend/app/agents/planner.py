"""Planner agent contract: read-only analysis and implementation plan generation."""

from backend.app.agents.base import BaseAgent, AgentExecutionContext
from backend.app.models.agent import AgentRole
from backend.app.models.planner import PersistedPlan
from backend.app.services.planner_service import PlannerService


class PlannerAgent(BaseAgent):
    """
    PLANNER Role:
    - Analyzes codebase and user request.
    - Generates an implementation plan.
    - Strict Invariant: Cannot modify files or execute commands.
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.PLANNER

    async def execute(self, context: AgentExecutionContext) -> PersistedPlan:
        if context.user_id is None:
            raise ValueError("Planner execution requires an authenticated user.")
        return await self.service.execute(context.task_id, context.user_id)
    def __init__(self, service: PlannerService | None = None):
        self.service = service or PlannerService()
