"""Authoritative backend-only Agent Role -> Loadout -> Worker resolver."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from backend.app.ai.gateway import ProviderGateway, QuotaGuardedGateway
from backend.app.models.agent import AgentRole
from backend.app.models.provider import Loadout, Worker
from backend.app.providers.adapters import ADAPTER_REGISTRY
from backend.app.providers.types import EncryptedCredentials
from backend.app.services.credential_service import CredentialService, EncryptedSecret


@dataclass(frozen=True)
class ResolvedRuntime:
    role: str
    worker_id: str
    provider_id: str
    model_name: str
    loadout_id: UUID | None
    override_worker_id: str | None
    gateway: ProviderGateway

    def run_metadata(self) -> dict[str, Any]:
        return {
            "loadout_id": str(self.loadout_id) if self.loadout_id else None,
            "worker_id": self.worker_id,
            "provider_id": self.provider_id,
            "model_name": self.model_name,
            "temporary_override_worker_id": self.override_worker_id,
        }


class RuntimeResolver:
    """Resolves configuration without returning plaintext credentials."""

    def __init__(self, credential_service: CredentialService | None = None, repository=None,
                 max_calls: int = 20, max_output_tokens: int = 8192):
        self.credential_service = credential_service or CredentialService()
        self.repository = repository
        self.workflow = None
        self.max_calls = max_calls
        self.max_output_tokens = max_output_tokens
        self.workers: dict[str, Worker] = {}
        self.credentials: dict[tuple[UUID, str], EncryptedCredentials] = {}
        self.loadouts: dict[UUID, tuple[UUID | None, Loadout]] = {}
        self.active_loadouts: dict[UUID, UUID] = {}
        self.overrides: dict[tuple[UUID, str], tuple[str, datetime]] = {}
        self.audit_records: list[dict[str, Any]] = []
        self._quota_gateways: dict[tuple[UUID, str, UUID, str], QuotaGuardedGateway] = {}

    async def hydrate(self) -> None:
        """Atomically replace cached configuration from the configured repository."""
        if self.repository is None:
            return
        configuration = await self.repository.runtime_configuration()
        workers: dict[str, Worker] = {}
        credentials: dict[tuple[UUID, str], EncryptedCredentials] = {}
        loadouts: dict[UUID, tuple[UUID | None, Loadout]] = {}
        active: dict[UUID, UUID] = {}
        for row in configuration["workers"]:
            workers[row["id"]] = Worker.model_validate(row)
        for row in configuration["credentials"]:
            encrypted = row["encrypted_api_key"]
            if isinstance(encrypted, str):
                import json
                encrypted = json.loads(encrypted)
            credentials[(row["user_id"], row["provider_id"])] = EncryptedCredentials(
                provider_id=row["provider_id"], **encrypted
            )
        for row in configuration["loadouts"]:
            mappings = row["mappings"]
            if isinstance(mappings, str):
                import json
                mappings = json.loads(mappings)
            loadouts[row["id"]] = (
                row.get("user_id"),
                Loadout.model_validate({**row, "mappings": mappings}),
            )
        for row in configuration["active_loadouts"]:
            active[row["workspace_id"]] = row["active_loadout_id"]
        self.workers, self.credentials, self.loadouts, self.active_loadouts = (
            workers, credentials, loadouts, active
        )
        self.overrides.clear()
        far_future = datetime.max.replace(tzinfo=timezone.utc)
        for row in configuration.get("task_overrides") or []:
            raw = row.get("worker_overrides") or {}
            if isinstance(raw, str):
                import json
                raw = json.loads(raw)
            if not isinstance(raw, dict):
                continue
            for role, worker_id in raw.items():
                self.overrides[(row["id"], str(role))] = (str(worker_id), far_future)
        # Preserve per-task quota counters when refreshing configuration.

    def register_worker(self, worker: Worker) -> None:
        self.workers[worker.id] = worker

    def register_credential(self, user_id: UUID, provider_id: str, secret: EncryptedSecret) -> None:
        self.credentials[(user_id, provider_id)] = EncryptedCredentials(
            provider_id=provider_id,
            ciphertext=secret.ciphertext,
            iv=secret.iv,
            tag=secret.tag,
        )

    def register_loadout(self, owner_id: UUID | None, loadout: Loadout) -> None:
        self.loadouts[loadout.id] = (owner_id, loadout)

    def switch_loadout(self, user_id: UUID, workspace_id: UUID, loadout_id: UUID) -> None:
        entry = self.loadouts.get(loadout_id)
        if entry is None or (entry[0] not in (None, user_id)):
            raise PermissionError("Loadout is not accessible")
        loadout = entry[1]
        for mapping in loadout.mappings.values():
            for worker_id in [mapping.primary_worker_id, *mapping.fallback_worker_ids]:
                self._validate_worker(user_id, worker_id)
        self.active_loadouts[workspace_id] = loadout_id
        self.audit_records.append({
            "event": "loadout_switch",
            "user_id": str(user_id),
            "workspace_id": str(workspace_id),
            "loadout_id": str(loadout_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def set_override(
        self, user_id: UUID, task_id: UUID, role: str, worker_id: str, expires_at: datetime
    ) -> None:
        self._validate_worker(user_id, worker_id)
        self.overrides[(task_id, role)] = (worker_id, expires_at)

    def hot_swap(self, user_id: UUID, workspace_id: UUID, role: str, worker_id: str,
                 reason: str | None = None) -> None:
        loadout_id = self.active_loadouts.get(workspace_id)
        if loadout_id is None or loadout_id not in self.loadouts:
            raise LookupError("No active loadout")
        owner, loadout = self.loadouts[loadout_id]
        if owner not in (None, user_id):
            raise PermissionError("Loadout is not accessible")
        previous = loadout.mappings.get(AgentRole(role))
        if previous is None:
            raise LookupError(f"No worker mapping for role {role}")
        self._validate_worker(user_id, worker_id)
        loadout.mappings[AgentRole(role)] = previous.model_copy(update={"primary_worker_id": worker_id})
        self.audit_records.append({
            "event": "agent_hot_swap", "agent_role": role,
            "previous_worker_id": previous.primary_worker_id, "new_worker_id": worker_id,
            "user_id": str(user_id), "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        })

    def resolve(self, user_id: UUID, workspace_id: UUID, task_id: UUID, role: str) -> ResolvedRuntime:
        role_enum = AgentRole(role)
        candidate_ids: list[UUID] = []
        active = self.active_loadouts.get(workspace_id)
        if active is not None:
            candidate_ids.append(active)
        for loadout_id, (owner, loadout) in self.loadouts.items():
            if self._loadout_visible(owner, loadout, user_id) and loadout_id not in candidate_ids:
                candidate_ids.append(loadout_id)

        selected: tuple[UUID, Loadout] | None = None
        for loadout_id in candidate_ids:
            entry = self.loadouts.get(loadout_id)
            if entry is None:
                continue
            owner, loadout = entry
            if not self._loadout_visible(owner, loadout, user_id):
                continue
            if role_enum in loadout.mappings:
                selected = (loadout_id, loadout)
                break
        if selected is None:
            raise LookupError("No active loadout")
        loadout_id, loadout = selected
        self.active_loadouts[workspace_id] = loadout_id
        mapping = loadout.mappings[role_enum]
        override = self.overrides.get((task_id, role))
        override_id = None
        worker_id = mapping.primary_worker_id
        if override:
            candidate, expires_at = override
            if expires_at > datetime.now(timezone.utc):
                worker_id, override_id = candidate, candidate
            else:
                self.overrides.pop((task_id, role), None)
        from backend.app.ai.failover import FailoverGateway
        worker = self._validate_worker(user_id, worker_id)
        candidates = []
        for candidate in dict.fromkeys([worker_id, *mapping.fallback_worker_ids]):
            selected_worker = self._validate_worker(user_id, candidate)
            credential = self.credentials[(user_id, selected_worker.provider_id)]
            adapter_type = ADAPTER_REGISTRY.get(selected_worker.provider_id)
            if adapter_type is None:
                raise LookupError("Provider adapter is not registered")
            candidates.append(({'worker_id': selected_worker.id, 'provider_id': selected_worker.provider_id,
                                'model_name': selected_worker.model_name},
                ProviderGateway(adapter_type(self.credential_service), credential, selected_worker.model_name)))
        async def reserve():
            await self.workflow.reserve_ai_call(task_id, user_id)
        async def record(evidence):
            await self.workflow.repository.record_provider_call(task_id, {**evidence, 'role': role})
        resolved = FailoverGateway(candidates, reserve if self.workflow else None,
                                   record if self.workflow else None)
        gateway_key = (task_id, role, loadout.id, worker.id)
        gateway = self._quota_gateways.get(gateway_key)
        if gateway is None:
            gateway = QuotaGuardedGateway(resolved, self.max_calls, self.max_output_tokens)
            self._quota_gateways[gateway_key] = gateway
        else:
            gateway.gateway = resolved
        return ResolvedRuntime(
            role=role,
            worker_id=worker.id,
            provider_id=worker.provider_id,
            model_name=worker.model_name,
            loadout_id=loadout.id,
            override_worker_id=override_id,
            gateway=gateway,
        )

    @staticmethod
    def _loadout_visible(owner: UUID | None, loadout: Loadout, user_id: UUID) -> bool:
        return bool(loadout.is_system_preset) or owner in (None, user_id)

    def _validate_worker(self, user_id: UUID, worker_id: str) -> Worker:
        worker = self.workers.get(worker_id)
        if worker is None:
            raise LookupError("Worker is not configured")
        if (user_id, worker.provider_id) not in self.credentials:
            raise PermissionError("Credential is not configured for provider")
        return worker
