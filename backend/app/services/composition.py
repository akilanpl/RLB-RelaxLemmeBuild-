"""Application composition for production agent services."""

from dataclasses import dataclass

from backend.app.db.session import get_sessionmaker
from backend.app.ai.gateway import QuotaGuardedGateway
from backend.app.ai.groq import GroqGateway
from backend.app.core.config import get_settings
from backend.app.providers.resolver import RuntimeResolver
from backend.app.repositories.provider import PostgresProviderRepository
from backend.app.services.coder_service import CoderService
from backend.app.services.planner_service import PlannerService
from backend.app.services.reviewer_service import ReviewerService


@dataclass(frozen=True)
class AgentServices:
    resolver: RuntimeResolver | None
    planner: PlannerService
    coder: CoderService
    reviewer: ReviewerService


_active_services: AgentServices | None = None


def active_agent_services() -> AgentServices | None:
    return _active_services


def build_agent_services(workflow=None, staging=None) -> AgentServices:
    """Build one resolver and share it across all LLM-backed services."""
    global _active_services
    sessions = get_sessionmaker()
    resolver = RuntimeResolver(
        repository=PostgresProviderRepository(sessions) if sessions else None
    )
    resolver.workflow = workflow
    settings = get_settings()
    resolver.max_calls = settings.MAX_AI_CALLS_PER_TASK
    resolver.max_output_tokens = settings.MAX_AI_OUTPUT_TOKENS
    planner_gateway = QuotaGuardedGateway(
        GroqGateway(),
        settings.MAX_AI_CALLS_PER_TASK, settings.MAX_AI_OUTPUT_TOKENS,
    )
    coder_gateway = QuotaGuardedGateway(
        GroqGateway(),
        settings.MAX_AI_CALLS_PER_TASK, settings.MAX_AI_OUTPUT_TOKENS,
    )
    reviewer_gateway = QuotaGuardedGateway(
        GroqGateway(),
        settings.MAX_AI_CALLS_PER_TASK, settings.MAX_AI_OUTPUT_TOKENS,
    )
    services = AgentServices(
        resolver=resolver,
        planner=PlannerService(gateway=planner_gateway, runtime_resolver=resolver, workflow=workflow),
        coder=CoderService(gateway=coder_gateway, runtime_resolver=resolver, workflow=workflow, staging_service=staging),
        reviewer=ReviewerService(gateway=reviewer_gateway, runtime_resolver=resolver, workflow=workflow),
    )
    _active_services = services
    return services
