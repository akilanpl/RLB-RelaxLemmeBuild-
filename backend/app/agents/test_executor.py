"""Test Executor agent contract: mandatory baseline checks and test execution in sandbox."""

from backend.app.agents.base import BaseAgent, AgentExecutionContext
from backend.app.models.agent import AgentRole
from backend.app.models.test import TestExecution
from backend.app.repositories.testing import InMemoryTestingRepository, TestingRepository
from backend.app.sandbox.base import BaseSandboxDriver
from backend.app.services.testing_service import TestExecutorService


class TestExecutorAgent(BaseAgent):
    """
    TEST EXECUTOR Role:
    - Runs in isolated sandbox environment.
    - Non-negotiable mandatory execution order:
        1. Mandatory Baseline Verification:
           a. Dependency install validation
           b. Static type checking
           c. Linting
           d. Production build
           e. Baseline unit tests
           f. Baseline integration tests
           g. Application startup / health check
        2. Test Architect custom test suites.
    - Records all commands, logs, and outputs.
    - Emits structured FailureReport upon failure for Coder loopback.
    - Strict Invariant: Cannot silently edit approved production files.
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.TEST_EXECUTOR

    def __init__(self, repository: TestingRepository | None = None,
                 sandbox: BaseSandboxDriver | None = None):
        self.repository = repository or InMemoryTestingRepository()
        self.sandbox = sandbox

    async def execute(self, context: AgentExecutionContext) -> TestExecution:
        if self.sandbox is None:
            raise RuntimeError("Test Executor requires an isolated sandbox driver.")
        if not context.staging_root:
            raise RuntimeError("Test Executor requires an isolated staging workspace.")
        return await TestExecutorService(self.repository, self.sandbox).execute(
            task_id=context.task_id, agent_run_id=context.agent_run_id,
            workspace_id=context.workspace_id or context.task_id,
            staging_root=context.staging_root,
        )
