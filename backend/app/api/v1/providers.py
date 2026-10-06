"""Authenticated provider, credential and loadout configuration APIs.

The in-memory store is a safe local adapter; production deployments can replace
it with repositories without changing the HTTP contract.
"""
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.app.core.auth import AuthenticatedUserContext, get_authenticated_user
from backend.app.models.provider import AgentWorkerMapping
from backend.app.services.credential_service import CredentialService
from backend.app.db.session import get_sessionmaker
from backend.app.repositories.provider import PostgresProviderRepository
from backend.app.providers.identity import (
    CANONICAL_PROVIDERS,
    UnsupportedProviderError,
    masked_fingerprint,
    resolve_provider_identity,
    worker_id_for,
    worker_owned_by,
)
from backend.app.providers.adapters import ADAPTER_REGISTRY
from backend.app.models.agent import AgentRole

router = APIRouter(prefix="/providers", tags=["providers"])
_credentials: dict[tuple[UUID, str], dict[str, Any]] = {}
_providers: dict[str, dict[str, Any]] = {}
_workers: dict[str, dict[str, Any]] = {}
_workspace_loadouts: dict[tuple[UUID, UUID], UUID] = {}
_loadouts: dict[UUID, dict[str, Any]] = {}
_overrides: dict[tuple[UUID, UUID, str], dict[str, Any]] = {}

_LLM_ROLES = {AgentRole.PLANNER.value, AgentRole.CODER.value, AgentRole.TEST_ARCHITECT.value, AgentRole.REVIEWER.value}


def _repository():
    sessions = get_sessionmaker()
    if sessions:
        return PostgresProviderRepository(sessions)
    from backend.app.services.runtime import get_runtime
    return get_runtime().agents.resolver.repository


class CredentialInput(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)
    provider_name: str | None = Field(default=None, min_length=1, max_length=120)
    provider_id: str | None = Field(default=None, min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_provider_identity(self) -> "CredentialInput":
        if not (self.provider_name and self.provider_name.strip()) and not (self.provider_id and self.provider_id.strip()):
            raise ValueError("Provider name is required.")
        return self


class LoadoutInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mappings: dict[str, AgentWorkerMapping]
    description: str | None = None


class OverrideInput(BaseModel):
    agent_role: str
    target_worker_id: str
    reason: str | None = None


class WorkerInput(BaseModel):
    model_name: str = Field(min_length=1, max_length=200)
    provider_id: str | None = None
    credential_id: str | None = None
    id: str | None = Field(default=None, max_length=160)
    context_window_tokens: int = Field(default=128000, gt=0)
    max_output_tokens: int = Field(default=8192, gt=0)
    temperature: float = Field(default=0.2, ge=0, le=2)
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None


def _public_credential(record: dict[str, Any], provider_name: str | None = None) -> dict[str, Any]:
    provider_id = str(record["provider_id"])
    canonical = CANONICAL_PROVIDERS.get(provider_id)
    return {
        "id": record["id"],
        "provider_id": provider_id,
        "provider_name": provider_name or record.get("provider_name") or (canonical.name if canonical else provider_id),
        "product_label": canonical.product_label if canonical else (provider_name or provider_id),
        "key_fingerprint": masked_fingerprint(str(record.get("key_fingerprint") or "")),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _contains_secret(payload: Any, secret: str) -> bool:
    if not secret:
        return False
    return secret in json.dumps(payload, default=str)


async def _load_user_credentials(auth: AuthenticatedUserContext, repository) -> list[dict[str, Any]]:
    if repository:
        return await repository.list_credentials(auth.user_id)
    return [record for (uid, _), record in _credentials.items() if uid == auth.user_id]


def _public_worker(worker: dict[str, Any], credential: dict[str, Any] | None) -> dict[str, Any]:
    provider_id = str(worker.get("provider_id") or "")
    canonical = CANONICAL_PROVIDERS.get(provider_id)
    provider_name = (credential or {}).get("provider_name") or (canonical.name if canonical else provider_id)
    return {
        "id": worker["id"],
        "provider_id": provider_id,
        "provider_name": provider_name,
        "product_label": canonical.product_label if canonical else provider_name,
        "model_name": worker.get("model_name"),
        "credential_id": None if not credential else credential.get("id"),
        "context_window_tokens": worker.get("context_window_tokens"),
        "max_output_tokens": worker.get("max_output_tokens"),
        "temperature": worker.get("temperature"),
    }


def _dump_mappings(mappings: dict[str, Any]) -> dict[str, Any]:
    dumped = {}
    for role, mapping in (mappings or {}).items():
        if hasattr(mapping, "model_dump"):
            dumped[role] = mapping.model_dump()
        elif isinstance(mapping, dict):
            dumped[role] = mapping
    return dumped


def _owned_workers(user_id: UUID, workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [worker for worker in workers if worker_owned_by(str(worker.get("id") or ""), user_id)]


@router.get("")
async def list_providers(auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    if repository:
        return await repository.list_providers()
    return [dict(item) for item in _providers.values() if item.get("is_active", True)]


@router.get("/catalog")
async def provider_catalog(auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    catalog = []
    for provider in CANONICAL_PROVIDERS.values():
        adapter = ADAPTER_REGISTRY.get(provider.adapter_id)
        catalog.append({
            "id": provider.id,
            "name": provider.name,
            "product_label": provider.product_label,
            "default_model": getattr(adapter, "default_model", "") if adapter else "",
        })
    return catalog


@router.get("/workers")
async def list_workers(auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    workers = await repository.list_workers() if repository else list(_workers.values())
    credentials = await _load_user_credentials(auth, repository)
    by_provider = {str(item["provider_id"]): item for item in credentials}
    visible = []
    for worker in _owned_workers(auth.user_id, workers):
        credential = by_provider.get(str(worker.get("provider_id")))
        if credential is None:
            continue
        visible.append(_public_worker(worker, _public_credential(credential, credential.get("provider_name"))))
    return visible


@router.put("/workers")
async def save_worker(body: WorkerInput, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    credentials = await _load_user_credentials(auth, repository)
    provider_id = (body.provider_id or "").strip()
    if body.credential_id:
        match = next((item for item in credentials if str(item.get("id")) == str(body.credential_id)), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Credential not found.")
        provider_id = str(match["provider_id"])
    if not provider_id:
        raise HTTPException(status_code=400, detail="Provider or credential is required.")
    owned = next((item for item in credentials if str(item.get("provider_id")) == provider_id), None)
    if owned is None:
        raise HTTPException(status_code=400, detail="Store an API credential for this provider before creating a model configuration.")
    worker_id = body.id or worker_id_for(auth.user_id, provider_id, body.model_name.strip())
    if not worker_owned_by(worker_id, auth.user_id):
        raise HTTPException(status_code=403, detail="Worker is not owned by the authenticated user.")
    record = {
        "id": worker_id,
        "provider_id": provider_id,
        "model_name": body.model_name.strip(),
        "context_window_tokens": body.context_window_tokens,
        "max_output_tokens": body.max_output_tokens,
        "temperature": body.temperature,
        "rate_limit_rpm": body.rate_limit_rpm,
        "rate_limit_tpm": body.rate_limit_tpm,
        "created_at": datetime.now(timezone.utc),
    }
    if repository:
        await repository.save_worker({
            "id": worker_id,
            "provider_id": provider_id,
            "model_name": record["model_name"],
            "context_window_tokens": record["context_window_tokens"],
            "max_output_tokens": record["max_output_tokens"],
            "temperature": record["temperature"],
            "rate_limit_rpm": record["rate_limit_rpm"],
            "rate_limit_tpm": record["rate_limit_tpm"],
        })
    else:
        _workers[worker_id] = record
    return _public_worker(record, _public_credential(owned, owned.get("provider_name")))


@router.delete("/workers/{worker_id}")
async def delete_worker(worker_id: str, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    if not worker_owned_by(worker_id, auth.user_id):
        raise HTTPException(status_code=404, detail="Worker not found.")
    repository = _repository()
    if repository:
        await repository.delete_worker(worker_id)
    else:
        _workers.pop(worker_id, None)
    return {"id": worker_id, "deleted": True}


@router.put("/credentials")
async def save_credential(body: CredentialInput, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    existing_providers = await repository.list_providers() if repository else list(_providers.values())
    try:
        resolved = resolve_provider_identity(body.provider_name or body.provider_id or "", existing_providers)
    except UnsupportedProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    provider_record = {
        "id": resolved.id,
        "name": resolved.name,
        "base_url": resolved.base_url,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "is_active": True,
    }
    if repository:
        await repository.ensure_provider(provider_record)
    else:
        _providers[resolved.id] = {**_providers.get(resolved.id, {}), **provider_record}

    service = CredentialService()
    encrypted = service.encrypt(body.api_key)
    fingerprint = service.fingerprint(body.api_key)
    now = datetime.now(timezone.utc)
    existing = None
    if repository:
        existing = await repository.get_credential(auth.user_id, resolved.id)
    else:
        existing = _credentials.get((auth.user_id, resolved.id))
    record = {
        "id": existing["id"] if existing and existing.get("id") else uuid4(),
        "user_id": auth.user_id,
        "provider_id": resolved.id,
        "provider_name": resolved.name,
        "key_fingerprint": fingerprint,
        "encrypted_api_key": json.dumps(encrypted.__dict__),
        "created_at": existing.get("created_at") if existing else now,
        "updated_at": now,
    }
    if repository:
        await repository.save_credential(auth.user_id, record)
    else:
        _credentials[(auth.user_id, resolved.id)] = record
    public = _public_credential(record, resolved.name)
    if _contains_secret(public, body.api_key) or "encrypted_api_key" in public:
        raise HTTPException(status_code=500, detail="Credential persistence refused to expose secrets.")
    return public


@router.get("/credentials")
async def list_credentials(auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    records = await _load_user_credentials(auth, repository)
    return [_public_credential(record, record.get("provider_name")) for record in records]


@router.delete("/credentials/{provider_id}")
async def delete_credential(provider_id: str, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    if repository:
        deleted = await repository.delete_credential(auth.user_id, provider_id)
    else:
        deleted = _credentials.pop((auth.user_id, provider_id), None) is not None
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found.")
    return {"provider_id": provider_id, "deleted": True}


@router.post("/loadouts")
async def create_loadout(body: LoadoutInput, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    return await _persist_loadout(uuid4(), body, auth)


@router.put("/loadouts/{loadout_id}")
async def update_loadout(loadout_id: UUID, body: LoadoutInput, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    existing = None
    if repository:
        existing = await repository.get_loadout(auth.user_id, loadout_id)
    else:
        candidate = _loadouts.get(loadout_id)
        if candidate and candidate.get("user_id") == auth.user_id:
            existing = candidate
    if existing is None:
        raise HTTPException(status_code=404, detail="Loadout not found.")
    return await _persist_loadout(loadout_id, body, auth, existing)


async def _persist_loadout(loadout_id: UUID, body: LoadoutInput, auth: AuthenticatedUserContext,
                           existing: dict[str, Any] | None = None) -> dict[str, Any]:
    repository = _repository()
    workers = await repository.list_workers() if repository else list(_workers.values())
    owned_ids = {str(item["id"]) for item in _owned_workers(auth.user_id, workers)}
    credentials = await _load_user_credentials(auth, repository)
    credential_providers = {str(item["provider_id"]) for item in credentials}
    workers_by_id = {str(item["id"]): item for item in workers}
    mappings: dict[str, Any] = {}
    for role, mapping in body.mappings.items():
        if role == AgentRole.TEST_EXECUTOR.value:
            continue
        if role not in _LLM_ROLES:
            raise HTTPException(status_code=400, detail="Unknown agent role.")
        for worker_id in [mapping.primary_worker_id, *mapping.fallback_worker_ids]:
            worker = workers_by_id.get(worker_id)
            if worker is None or worker_id not in owned_ids:
                raise HTTPException(status_code=400, detail="Selected model configuration is invalid.")
            if str(worker.get("provider_id")) not in credential_providers:
                raise HTTPException(status_code=400, detail="Credential is not available for the selected model.")
        mappings[role] = mapping
    record = {
        "id": loadout_id,
        "user_id": auth.user_id,
        "name": body.name,
        "description": body.description,
        "is_system_preset": False,
        "mappings": _dump_mappings(mappings),
        "created_at": (existing or {}).get("created_at") or datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    if repository:
        await repository.upsert_loadout(record)
    else:
        _loadouts[loadout_id] = record
    return {**record, "mappings": record["mappings"]}


@router.get("/loadouts")
async def list_loadouts(auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    repository = _repository()
    if repository:
        records = await repository.list_loadouts(auth.user_id)
    else:
        records = [r for r in _loadouts.values() if r["user_id"] == auth.user_id]
    return [{**record, "mappings": _dump_mappings(record.get("mappings") or {})} for record in records]


@router.post("/workspaces/{workspace_id}/loadout/{loadout_id}")
async def switch_loadout(workspace_id: UUID, loadout_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    from backend.app.services.runtime import get_runtime
    from backend.app.services.workspace_service import WorkspaceNotFoundError
    try:
        await get_runtime().workspace.get_workspace(workspace_id, auth.user_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found")
    repository = _repository()
    if repository:
        try:
            await repository.switch_loadout(auth.user_id, workspace_id, loadout_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Loadout not found") from exc
        return {"workspace_id": workspace_id, "active_loadout_id": loadout_id, "switched_at": datetime.now(timezone.utc)}
    record = _loadouts.get(loadout_id)
    if not record or record["user_id"] != auth.user_id:
        raise HTTPException(status_code=404, detail="Loadout not found")
    _workspace_loadouts[(auth.user_id, workspace_id)] = loadout_id
    return {"workspace_id": workspace_id, "active_loadout_id": loadout_id, "switched_at": datetime.now(timezone.utc)}


@router.get("/workspaces/{workspace_id}/loadout")
async def active_loadout(workspace_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    from backend.app.services.runtime import get_runtime
    from backend.app.services.workspace_service import WorkspaceNotFoundError
    try:
        await get_runtime().workspace.get_workspace(workspace_id, auth.user_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found")
    repository = _repository()
    if repository:
        return await repository.active_loadout(auth.user_id, workspace_id)
    loadout_id = _workspace_loadouts.get((auth.user_id, workspace_id))
    return _loadouts.get(loadout_id) if loadout_id else None


@router.put("/workspaces/{workspace_id}/tasks/{task_id}/overrides")
async def set_temporary_override(workspace_id: UUID, task_id: UUID, body: OverrideInput,
                                 auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    """Set a task-scoped worker override; it never mutates the workspace loadout."""
    record = {"workspace_id": workspace_id, "task_id": task_id, **body.model_dump(),
              "user_id": auth.user_id, "created_at": datetime.now(timezone.utc)}
    from backend.app.services.composition import active_agent_services
    from backend.app.services.task_service import TaskAccessDeniedError, TaskNotFoundError, workflow_engine

    try:
        task = await workflow_engine.get_task(task_id, auth.user_id)
    except TaskNotFoundError:
        task = None
    except TaskAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="Task access denied.") from exc
    if task is not None and task.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Task access denied.")
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    services = active_agent_services()
    resolver = services.resolver if services else None
    if resolver is not None:
        if body.target_worker_id in resolver.workers:
            try:
                resolver.set_override(
                    auth.user_id, task_id, body.agent_role, body.target_worker_id, expires_at
                )
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail="Credential is not configured for provider.") from exc
            except LookupError as exc:
                raise HTTPException(status_code=400, detail="Selected model configuration is invalid.") from exc
        else:
            resolver.overrides[(task_id, body.agent_role)] = (body.target_worker_id, expires_at)
    if task is not None:
        setter = getattr(workflow_engine.repository, "set_worker_override", None)
        if setter is not None:
            await setter(task_id, body.agent_role, body.target_worker_id)
    _overrides[(auth.user_id, task_id, body.agent_role)] = record
    return {k: v for k, v in record.items() if k != "user_id"}


@router.delete("/workspaces/{workspace_id}/tasks/{task_id}/overrides/{agent_role}")
async def clear_temporary_override(workspace_id: UUID, task_id: UUID, agent_role: str,
                                   auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    from backend.app.services.composition import active_agent_services
    from backend.app.services.task_service import TaskAccessDeniedError, TaskNotFoundError, workflow_engine

    try:
        task = await workflow_engine.get_task(task_id, auth.user_id)
    except TaskNotFoundError:
        task = None
    except TaskAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="Task access denied.") from exc
    services = active_agent_services()
    if services and services.resolver:
        services.resolver.overrides.pop((task_id, agent_role), None)
    if task is not None:
        setter = getattr(workflow_engine.repository, "set_worker_override", None)
        if setter is not None:
            await setter(task_id, agent_role, None)
    _overrides.pop((auth.user_id, task_id, agent_role), None)
    return {"task_id": task_id, "agent_role": agent_role, "cleared": True}
