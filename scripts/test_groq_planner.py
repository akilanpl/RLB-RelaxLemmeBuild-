"""Optional manual Groq Planner smoke test.

Run from the repository root only when GROQ_API_KEY is configured.
"""

import asyncio
import json
import os
import sys

from backend.app.ai.gateway import AIRequest
from backend.app.ai.groq import GroqGateway
from backend.app.models.planner import ImplementationPlan


async def main() -> None:
    if not os.getenv("GROQ_API_KEY"):
        print("GROQ_API_KEY is not configured; smoke test not run.")
        return
    response = await GroqGateway().generate(AIRequest(
        system_prompt="Return only valid JSON matching the ImplementationPlan schema.",
        user_prompt=json.dumps({
            "objective": "Add a health-check endpoint.",
            "context": {"relevant_source": [], "codebase": {"languages": ["Python"]}},
        }),
    ))
    plan = ImplementationPlan.model_validate_json(response.content)
    print(json.dumps({
        "provider": response.metadata.get("provider"),
        "model": response.model,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "steps": len(plan.implementation_steps),
        "affected_files": len(plan.affected_files),
    }))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Groq Planner smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
