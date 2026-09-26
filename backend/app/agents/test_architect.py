"""Test Architect agent contract: test suite generation from request, plan, and diff."""

from backend.app.agents.base import BaseAgent, AgentExecutionContext
from backend.app.models.agent import AgentRole
from backend.app.models.test import TestPlan
from backend.app.repositories.testing import InMemoryTestingRepository, TestingRepository
from backend.app.services.testing_service import TestArchitectService


class TestArchitectAgent(BaseAgent):
    """
    TEST ARCHITECT Role:
    - Analyzes request, approved plan, current code, and proposed diff.
    - Generates functional, regression, edge-case, and security test cases.
    - Strict Invariants:
        - Read-only; cannot modify production code.
        - Cannot execute tests or commands.
        - Cannot modify or disable the mandatory baseline verification policy.
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.TEST_ARCHITECT

    def __init__(self, repository: TestingRepository | None = None):
        self.repository = repository or InMemoryTestingRepository()

    async def execute(self, context: AgentExecutionContext) -> TestPlan:
        plan = await TestArchitectService(self.repository).get_plan(context.task_id)
        if plan is None:
            raise ValueError("No persisted test plan exists for this task.")
        return plan
