"""Authenticated device management and outbound device-session APIs."""

from datetime import datetime
import httpx

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.app.core.auth import AuthenticatedUserContext, get_authenticated_user
from backend.app.services.device_control import CommandStatus, CommandType, DeviceStatus
from backend.app.services.runtime import RuntimeRef, get_runtime
from backend.app.services.task_artifacts import MAX_ARTIFACT_BYTES, TaskArtifactService
from backend.app.db.session import get_sessionmaker
from backend.app.core.config import get_settings

router = APIRouter(tags=["devices"])
control = RuntimeRef("devices")


def _artifact_service() -> TaskArtifactService:
    runtime = get_runtime()
    return TaskArtifactService(
        runtime.workspace.storage,
        sessions=get_sessionmaker(),
        retention_days=get_settings().ARTIFACT_RETENTION_DAYS,
    )


def _artifact_response(name: str, content_type: str, content: bytes) -> Response:
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Artifact-Name": name},
    )


class PairRequest(BaseModel):
    pairing_token: str = Field(min_length=20, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=40)
    architecture: str = Field(min_length=1, max_length=40)
    app_version: str = Field(min_length=1, max_length=40)
    runtime_version: str = Field(min_length=1, max_length=40)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    runtime_state: str
    current_task_id: UUID | None = None
    app_version: str
    runtime_version: str
    capabilities: dict[str, Any] = Field(default_factory=dict)


class CreateCommandRequest(BaseModel):
    command_type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=200)
    task_id: UUID | None = None
    ttl_seconds: int | None = Field(None, ge=1, le=604800)


class CommandUpdateRequest(BaseModel):
    status: CommandStatus
    result: dict[str, Any] | None = None
    error: str | None = Field(None, max_length=2000)

class DeviceEventRequest(BaseModel):
    event_id: UUID
    task_id: UUID
    sequence: int = Field(ge=1, le=9_223_372_036_854_775_807)
    event_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    source: str = Field(default="windows_runtime", max_length=80)


class DeviceEventsRequest(BaseModel):
    events: list[DeviceEventRequest] = Field(max_length=200)

class ConfigureConnectionRequest(BaseModel):
    owner_id: UUID | None = None
    control_plane_url: str = Field(min_length=8, max_length=500)
    device_token: str = Field(min_length=40, max_length=200)


def _device_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Device authentication required.")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Device authentication required.")
    return token


@router.post("/devices/pairings")
async def create_pairing(auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    return await control.create_pairing(auth.user_id)


@router.post("/devices/pair")
async def pair_device(request: PairRequest):
    try:
        device, token = await control.pair(
            request.pairing_token, name=request.name, platform=request.platform,
            architecture=request.architecture, app_version=request.app_version,
            runtime_version=request.runtime_version, capabilities=request.capabilities,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"device": device, "device_token": token}


@router.get("/devices")
async def list_devices(auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    return [control._freshness(device) for device in await control.list_devices(auth.user_id)]


@router.get("/devices/{device_id}")
async def get_device(device_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        return await control.get_device(device_id, auth.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        return await control.revoke(device_id, auth.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/devices/{device_id}/commands")
async def create_command(device_id: UUID, request: CreateCommandRequest,
                         auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        if request.command_type == CommandType.REQUEST_ARTIFACT_UPLOAD:
            from backend.app.services.task_artifacts import safe_relative_path
            if request.task_id is None:
                raise ValueError("A task_id is required for artifact upload.")
            safe_relative_path(str(request.payload.get("relative_path", "")))
        if request.command_type == CommandType.DOWNLOAD_ARTIFACT_TO_PC:
            if request.task_id is None:
                raise ValueError("A task_id is required for artifact download.")
            try:
                artifact_id = UUID(str(request.payload["artifact_id"]))
            except (KeyError, ValueError) as exc:
                raise ValueError("A valid artifact_id is required.") from exc
            metadata = await _artifact_service().get_metadata(
                artifact_id, auth.user_id, request.task_id, device_id,
            )
            if metadata is None:
                raise LookupError("Artifact not found for this device and task.")
        return await control.enqueue_command(
            device_id, auth.user_id, request.command_type, request.payload,
            request.idempotency_key, request.task_id, request.ttl_seconds,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/devices/{device_id}/commands")
async def list_commands(device_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        return await control.list_commands(device_id, auth.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/devices/{device_id}/events")
async def list_device_events(
    device_id: UUID, limit: int = Query(100, ge=1, le=500),
    after: int | None = Query(None, ge=0),
    auth: AuthenticatedUserContext = Depends(get_authenticated_user),
):
    try:
        return await control.list_event_page(device_id, auth.user_id, limit, after)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/devices/{device_id}/tasks/{task_id}/artifacts")
async def list_device_task_artifacts(device_id: UUID, task_id: UUID,
                                    auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await control.authorize_task_for_device(device_id, auth.user_id, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return await _artifact_service().list_for_task(task_id, auth.user_id, device_id)


@router.get("/devices/{device_id}/tasks/{task_id}/artifacts/{artifact_id}")
async def download_device_task_artifact(device_id: UUID, task_id: UUID, artifact_id: UUID,
                                        auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await control.authorize_task_for_device(device_id, auth.user_id, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    artifact = await _artifact_service().read(artifact_id, auth.user_id, task_id, device_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found or expired.")
    metadata, content = artifact
    return _artifact_response(metadata["name"], metadata["content_type"], content)


@router.get("/tasks/{task_id}/artifacts")
async def list_task_artifacts(task_id: UUID, auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await get_runtime().workflow.get_task(task_id, auth.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Task not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Task access denied.") from exc
    return await _artifact_service().list_for_task(task_id, auth.user_id)


@router.get("/tasks/{task_id}/artifacts/{artifact_id}")
async def download_task_artifact(task_id: UUID, artifact_id: UUID,
                                auth: AuthenticatedUserContext = Depends(get_authenticated_user)):
    try:
        await get_runtime().workflow.get_task(task_id, auth.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Task not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Task access denied.") from exc
    artifact = await _artifact_service().read(artifact_id, auth.user_id, task_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found or expired.")
    metadata, content = artifact
    return _artifact_response(metadata["name"], metadata["content_type"], content)


@router.post("/device-session/tasks/{task_id}/artifacts")
async def upload_task_artifact(task_id: UUID, workspace_id: UUID = Form(...), file: UploadFile = File(...),
                               authorization: str | None = Header(None)):
    try:
        device = await control.authenticate_device(_device_token(authorization))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Device authentication required.") from exc
    try:
        expected_workspace_id = await control.workspace_for_device_task(
            device.id, device.user_id, task_id,
        )
        if expected_workspace_id != workspace_id:
            raise PermissionError("Artifact workspace does not match the task workspace.")
    except LookupError as exc:
        raise HTTPException(status_code=403, detail="Task is not associated with this device.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if file.size is not None and file.size > MAX_ARTIFACT_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="Artifact exceeds the 25 MiB limit.")
    content = await file.read(MAX_ARTIFACT_BYTES + 1)
    if len(content) > MAX_ARTIFACT_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="Artifact exceeds the 25 MiB limit.")
    try:
        return await _artifact_service().create(
            user_id=device.user_id, device_id=device.id, workspace_id=workspace_id,
            task_id=task_id, name=file.filename or "", content_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@router.get("/device-session/tasks/{task_id}/artifacts/{artifact_id}/content")
async def download_task_artifact_to_device(task_id: UUID, artifact_id: UUID,
                                           authorization: str | None = Header(None)):
    try:
        device = await control.authenticate_device(_device_token(authorization))
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail="Device authentication required.") from exc
    artifact = await _artifact_service().read(artifact_id, device.user_id, task_id, device.id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found or expired.")
    metadata, content = artifact
    return _artifact_response(metadata["name"], metadata["content_type"], content)


@router.post("/device-session/heartbeat")
async def device_heartbeat(request: HeartbeatRequest, authorization: str | None = Header(None)):
    try:
        return await control.heartbeat(
            _device_token(authorization), runtime_state=request.runtime_state,
            current_task_id=request.current_task_id, app_version=request.app_version,
            runtime_version=request.runtime_version, capabilities=request.capabilities,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/device-session/events")
async def sync_device_events(request: DeviceEventsRequest, authorization: str | None = Header(None)):
    try:
        accepted = await control.ingest_events(
            _device_token(authorization),
            [event.model_dump(mode="json") for event in request.events],
        )
        return {"accepted_event_ids": accepted}
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/device-session/commands")
async def pull_commands(
    claim_id: UUID = Query(...),
    authorization: str | None = Header(None),
):
    try:
        return await control.claim_commands(_device_token(authorization), claim_id)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/device-session/commands/{command_id}")
async def update_command(command_id: UUID, request: CommandUpdateRequest, authorization: str | None = Header(None)):
    try:
        return await control.update_command(
            _device_token(authorization), command_id, request.status,
            request.result, request.error,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/device-session/disconnect")
async def device_disconnect(authorization: str | None = Header(None)):
    try:
        device = await control.authenticate_device(_device_token(authorization))
        device.status = DeviceStatus.OFFLINE
        device.runtime_state = "stopped"
        await control._persist_device(device)
        return {"status": "OFFLINE"}
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/device-session/configure")
async def configure_device_connection(request: ConfigureConnectionRequest):
    from backend.app.core.config import get_settings
    if get_settings().ENVIRONMENT not in {"development", "desktop"}:
        raise HTTPException(status_code=404, detail="Not found.")
    from backend.app.services.runtime import get_runtime
    try:
        await get_runtime().configure_device_connection(
            request.control_plane_url, request.device_token, request.owner_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Could not authenticate the device with the control plane.") from exc
    return {"connected": True}
