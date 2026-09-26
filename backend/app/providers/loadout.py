"""Provider-agnostic worker resolution, failover and run provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping
from uuid import UUID, uuid4

from backend.app.models.provider import AgentWorkerMapping, Loadout, Worker
from backend.app.providers.base import BaseWorker, LoadoutRouterResult
from backend.app.providers.types import CompletionRequest, EncryptedCredentials


class WorkerRuntime(BaseWorker):
    """Concrete stateless worker used by the router and existing agents."""
    def __init__(self, definition: Worker, provider_adapter):
        self.definition = definition
        self._provider_adapter = provider_adapter

    @property
    def worker_id(self): return self.definition.id
    @property
    def provider_adapter(self): return self._provider_adapter
    @property
    def model_name(self): return self.definition.model_name
    @property
    def context_window_tokens(self): return self.definition.context_window_tokens


@dataclass
class AgentRunProvenance:
    id: UUID
    task_id: UUID
    agent_role: str
    loadout_id: UUID | None
    worker_id: str
    provider_id: str
    model_name: str
    started_at: datetime
    completed_at: datetime | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    execution_status: str = "running"


class LoadoutRouter:
    def __init__(self, workers: Mapping[str, BaseWorker], adapters: Mapping[str, object], credentials: Mapping[str, EncryptedCredentials]):
        self.workers, self.adapters, self.credentials = workers, adapters, credentials
        self.runs: list[AgentRunProvenance] = []

    @staticmethod
    def resolve_worker(loadout: Loadout, agent_role: str, *,
                       override_worker_id: str | None = None) -> tuple[str, list[str]]:
        """Resolve primary and fallback IDs without coupling callers to storage."""
        mapping = loadout.mappings.get(agent_role)
        if mapping is None:
            raise ValueError(f"No worker mapping for role {agent_role}")
        if override_worker_id:
            return override_worker_id, []
        return mapping.primary_worker_id, list(mapping.fallback_worker_ids)

    async def dispatch(self, *, task_id: UUID, agent_role: str, loadout: Loadout,
                       request: CompletionRequest, override_worker_id: str | None = None) -> LoadoutRouterResult:
        mapping = loadout.mappings.get(agent_role)
        if mapping is None:
            raise ValueError(f"No worker mapping for role {agent_role}")
        ids = [override_worker_id] if override_worker_id else [mapping.primary_worker_id, *mapping.fallback_worker_ids]
        errors: list[str] = []
        started = datetime.now(timezone.utc)
        for index, worker_id in enumerate(ids):
            worker = self.workers[worker_id]
            try:
                adapter = self.adapters[worker.provider_adapter.provider_id]
                result = await adapter.generate_completion(request.model_copy(update={"model": worker.model_name}), self.credentials[worker.provider_adapter.provider_id])
                reason = "; ".join(errors) or None
                provenance = AgentRunProvenance(uuid4(), task_id, agent_role, loadout.id, worker_id, worker.provider_adapter.provider_id, worker.model_name, started, datetime.now(timezone.utc), index > 0, reason, "completed")
                self.runs.append(provenance)
                return LoadoutRouterResult(result, worker_id, provenance.provider_id, worker.model_name, index > 0, reason, ids[0])
            except Exception as exc:
                errors.append(f"{worker_id}: {type(exc).__name__}: {exc}")
        self.runs.append(AgentRunProvenance(uuid4(), task_id, agent_role, loadout.id, ids[-1], self.workers[ids[-1]].provider_adapter.provider_id, self.workers[ids[-1]].model_name, started, datetime.now(timezone.utc), len(ids) > 1, "; ".join(errors), "failed"))
        raise RuntimeError("All workers failed: " + "; ".join(errors))
