"""Authenticated outbound long-poll connection from a local runtime to cloud."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

import httpx

from backend.app.storage.sqlite import SQLiteStateStore

logger = logging.getLogger(__name__)
CommandHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class DeviceConnectionManager:
    """Poll cloud commands over outbound HTTPS; local workers never depend on it."""

    def __init__(self, api_url: str, device_token: str, data_path: str | Path,
                 command_handler: CommandHandler, *, client: httpx.AsyncClient | None = None,
                 heartbeat_seconds: int = 20, max_backoff_seconds: int = 60,
                 event_source: Any | None = None):
        from urllib.parse import urlsplit
        parsed = urlsplit(api_url)
        if (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("Device control must use an HTTPS origin (or a loopback origin during development).")
        self.api_url = api_url.rstrip("/")
        self.device_token = device_token
        self.claim_id = uuid4()
        self.command_handler = command_handler
        self.event_source = event_source
        self.heartbeat_seconds = heartbeat_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._client = client or httpx.AsyncClient(timeout=20)
        self._owns_client = client is None
        self._store = SQLiteStateStore(data_path)
        self._receipts: dict[str, str] = {}
        self._stop = asyncio.Event()
        self._last_heartbeat = 0.0

    async def start(self) -> None:
        self._receipts = await self._store.load("remote_command_receipts", {})

    async def close(self) -> None:
        self._stop.set()
        try:
            await self._request("POST", "/api/v1/device-session/disconnect", timeout=2)
        except (httpx.HTTPError, RuntimeError):
            logger.info("Could not notify cloud about device disconnect; it will expire by heartbeat.")
        await self._store.close()
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, route: str, **kwargs):
        response = await self._client.request(
            method, self.api_url + route,
            headers={"Authorization": f"Bearer {self.device_token}", **kwargs.pop("headers", {})},
            **kwargs,
        )
        response.raise_for_status()
        return response.json() if response.content else None

    async def upload_task_artifact(self, task_id: UUID, workspace_id: UUID, name: str, content: bytes,
                                   content_type: str) -> dict[str, Any]:
        from backend.app.services.task_artifacts import MAX_ARTIFACT_BYTES, safe_artifact_name
        safe_name = safe_artifact_name(name)
        if not content or len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("Artifact must be between 1 byte and 25 MiB.")
        response = await self._client.post(
            self.api_url + f"/api/v1/device-session/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer " + self.device_token},
            files={"file": (safe_name, content, content_type or "application/octet-stream")},
            data={"workspace_id": str(workspace_id)},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    async def download_task_artifact(self, task_id: UUID, artifact_id: UUID) -> tuple[str, str, bytes]:
        response = await self._client.get(
            self.api_url + f"/api/v1/device-session/tasks/{task_id}/artifacts/{artifact_id}/content",
            headers={"Authorization": "Bearer " + self.device_token},
            timeout=60,
        )
        response.raise_for_status()
        name = response.headers.get("x-artifact-name", "")
        content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        return name, content_type, response.content

    async def _heartbeat(self, runtime_state: str, current_task_id: UUID | None,
                         app_version: str, runtime_version: str, capabilities: dict[str, Any]) -> None:
        await self._request("POST", "/api/v1/device-session/heartbeat", json={
            "runtime_state": runtime_state,
            "current_task_id": str(current_task_id) if current_task_id else None,
            "app_version": app_version, "runtime_version": runtime_version,
            "capabilities": capabilities,
        })
        self._last_heartbeat = asyncio.get_running_loop().time()

    async def poll_once(self, *, runtime_state: str = "running",
                        current_task_id: UUID | None = None, app_version: str = "0.1.0",
                        runtime_version: str = "0.1.0",
                        capabilities: dict[str, Any] | None = None) -> int:
        if asyncio.get_running_loop().time() - self._last_heartbeat >= self.heartbeat_seconds:
            await self._heartbeat(runtime_state, current_task_id, app_version, runtime_version, capabilities or {})
        await self._flush_events()
        commands = await self._request(
            "GET", "/api/v1/device-session/commands",
            params={"claim_id": str(self.claim_id)},
        ) or []
        handled = 0
        for command in commands:
            command_id = str(command["id"])
            receipt = self._receipts.get(command_id)
            if isinstance(receipt, dict) and receipt.get("status") in {"SUCCEEDED", "FAILED"}:
                update = {"status": receipt["status"]}
                if receipt["status"] == "SUCCEEDED":
                    update["result"] = receipt.get("result")
                else:
                    update["error"] = receipt.get("error", "Local command failed.")
                await self._request(
                    "POST", f"/api/v1/device-session/commands/{command_id}", json=update,
                )
                continue
            if receipt == "SUCCEEDED":
                continue
            if receipt == "EXECUTING" or (
                isinstance(receipt, dict) and receipt.get("status") == "EXECUTING"
            ):
                await self._request("POST", f"/api/v1/device-session/commands/{command_id}",
                                    json={"status": "FAILED", "error": "Interrupted during prior local execution; not replayed."})
                self._receipts[command_id] = {
                    "status": "FAILED",
                    "error": "Interrupted during prior local execution; not replayed.",
                }
                await self._store.save("remote_command_receipts", self._receipts)
                continue
            if receipt == "FAILED":
                continue
            if command.get("expires_at") and datetime.fromisoformat(command["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                await self._request("POST", f"/api/v1/device-session/commands/{command_id}",
                                    json={"status": "FAILED", "error": "Expired before local execution."})
                continue
            self._receipts[command_id] = {"status": "EXECUTING"}
            await self._store.save("remote_command_receipts", self._receipts)
            await self._request("POST", f"/api/v1/device-session/commands/{command_id}",
                                json={"status": "ACKNOWLEDGED"})
            await self._request("POST", f"/api/v1/device-session/commands/{command_id}",
                                json={"status": "EXECUTING"})
            try:
                result = await self.command_handler(command)
            except Exception as exc:
                logger.exception("Remote command %s failed locally.", command_id)
                from backend.app.analysis.sanitizer import redact_secrets
                message = redact_secrets(str(exc))[:500] if isinstance(exc, (ValueError, PermissionError)) else type(exc).__name__
                self._receipts[command_id] = {
                    "status": "FAILED",
                    "error": message,
                }
                await self._store.save("remote_command_receipts", self._receipts)
                await self._request("POST", f"/api/v1/device-session/commands/{command_id}",
                                    json={"status": "FAILED", "error": message})
            else:
                self._receipts[command_id] = {"status": "SUCCEEDED", "result": result}
                await self._store.save("remote_command_receipts", self._receipts)
                await self._request("POST", f"/api/v1/device-session/commands/{command_id}",
                                    json={"status": "SUCCEEDED", "result": result})
            handled += 1
        return handled

    async def _flush_events(self) -> None:
        if self.event_source is None:
            return
        events = await self.event_source.pending_events(200)
        if not events:
            return
        response = await self._request("POST", "/api/v1/device-session/events", json={"events": events})
        accepted = response.get("accepted_event_ids", []) if isinstance(response, dict) else []
        if accepted:
            await self.event_source.acknowledge_events(accepted)

    async def run(self, status_provider: Callable[[], dict[str, Any]]) -> None:
        delay = 1
        while not self._stop.is_set():
            try:
                current = status_provider()
                await self.poll_once(**current)
                delay = 1
                await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_seconds / 2)
            except asyncio.TimeoutError:
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    logger.error("Device control credential was rejected; explicit re-pairing is required.")
                    self._stop.set()
                    return
                logger.warning("Device control returned HTTP %s; reconnecting.", exc.response.status_code)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.max_backoff_seconds)
            except (httpx.HTTPError, RuntimeError, ValueError, OSError):
                logger.warning("Device control connection unavailable; retrying with backoff.")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.max_backoff_seconds)
