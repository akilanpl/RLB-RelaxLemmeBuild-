"""Daytona sandbox adapter. The SDK client is injected to keep tests offline."""

import asyncio
from typing import Any, AsyncIterator
from uuid import UUID

from backend.app.sandbox.base import BaseSandboxDriver
from backend.app.sandbox.types import SandboxCommand, SandboxExecutionResult, SandboxLimits


class DaytonaSandboxDriver(BaseSandboxDriver):
    def __init__(self, client: Any):
        self.client = client

    async def create_sandbox(self, workspace_id: UUID, staging_root_path: str,
                             limits: SandboxLimits) -> str:
        sandbox = await self.client.create(
            labels={"workspace_id": str(workspace_id)},
            resources=limits.model_dump(),
            network_enabled=limits.network_enabled,
        )
        try:
            await sandbox.mkdir("/workspace")
            await self.client.restore_snapshot(sandbox, staging_root_path, "/workspace")
            return sandbox.id
        except BaseException:
            await self.destroy_sandbox(sandbox.id)
            raise

    async def execute_command(self, sandbox_id: str, command: SandboxCommand) -> SandboxExecutionResult:
        result = await self.client.execute(
            sandbox_id, command.cmd, cwd=command.cwd or "/workspace",
            env=command.env, timeout=command.timeout_seconds,
        )
        return SandboxExecutionResult(
            exit_code=result.exit_code, stdout=result.stdout or "",
            stderr=result.stderr or "", duration_ms=result.duration_ms,
            timed_out=getattr(result, "timed_out", False),
        )

    async def stream_command_output(self, sandbox_id: str,
                                    command: SandboxCommand) -> AsyncIterator[str]:
        async for line in self.client.stream(
            sandbox_id, command.cmd, cwd=command.cwd or "/workspace",
            env=command.env, timeout=command.timeout_seconds,
        ):
            yield line

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        await asyncio.wait_for(self.client.destroy(sandbox_id), timeout=30)
