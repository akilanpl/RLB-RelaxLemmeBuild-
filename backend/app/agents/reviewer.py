"""Reviewer agent contract: strictly read-only final audit."""

import json
from typing import Optional
from backend.app.agents.base import BaseAgent, AgentExecutionContext
from backend.app.ai.gateway import AIGateway, AIRequest
from backend.app.models.agent import AgentRole


class ReviewerAgent(BaseAgent):
    """
    REVIEWER Role:
    - Impartial, read-only final auditor.
    - Permitted to inspect:
        - Approved workspace files
        - Staging proposed diff
        - Approved implementation plan
        - Test plan and test execution results
        - Sandbox build and execution logs
        - Previous agent run transcripts
    - Generates a descriptive ReviewerReport (never a numeric score).
    - Strict Invariants:
        - Cannot write or edit files (approved or staging).
        - Cannot execute shell commands or tests.
        - Cannot install dependencies.
        - Cannot switch loadouts or workers.
        - Cannot approve its own review.
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.REVIEWER

    async def execute(self, context: AgentExecutionContext):
        if self.gateway is None:
            raise RuntimeError("ReviewerAgent requires an AIGateway.")
        response = await self.gateway.generate(AIRequest(
            system_prompt=("You are a read-only final software reviewer. Return only JSON with "
                           "summary, task_understanding, implementation_summary, changed_files, "
                           "requirements_coverage, behavior_verified, tests_summary, test_failures, "
                           "repair_summary, remaining_risks, unresolved_items, evidence, "
                           "final_status, strengths, concerns, security_audit, recommendation. "
                           "Use only supplied evidence. Do not assign a score."),
            user_prompt=context.user_prompt,
        ))
        data = json.loads(response.content)
        data.pop("overall_score", None)
        return {"report": data, "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens, "metadata": response.metadata}
    def __init__(self, gateway: Optional[AIGateway] = None):
        self.gateway = gateway
