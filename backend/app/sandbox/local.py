"""Constrained local process driver used by the Windows runtime."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.sandbox.base import BaseSandboxDriver
from backend.app.sandbox.types import SandboxCommand, SandboxExecutionResult, SandboxLimits


class LocalWindowsSandboxDriver(BaseSandboxDriver):
    """Run commands below a selected project root without exposing a shell API."""

    def __init__(self):
        self._roots: dict[str, Path] = {}

    async def create_sandbox(self, workspace_id: UUID, staging_root_path: str,
                             limits: SandboxLimits) -> str:
        root = Path(staging_root_path).resolve()
        if not root.is_dir():
            raise ValueError("Execution root must be an existing directory.")
        handle = str(uuid4())
        self._roots[handle] = root
        return handle

    def _cwd(self, sandbox_id: str, command: SandboxCommand) -> Path:
        root = self._roots.get(sandbox_id)
        if root is None:
            raise ValueError("Unknown local execution context.")
        candidate = (root / (command.cwd or ".")).resolve()
        if os.path.commonpath((str(root), str(candidate))) != str(root):
            raise ValueError("Execution directory escapes the project root.")
        if not candidate.is_dir():
            raise ValueError("Execution directory does not exist.")
        return candidate

    async def execute_command(self, sandbox_id: str, command: SandboxCommand) -> SandboxExecutionResult:
        cwd = self._cwd(sandbox_id, command)
        started = time.monotonic()
        timeout = command.timeout_seconds or 600
        creationflags = getattr(asyncio.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        process = await asyncio.create_subprocess_shell(
            command.cmd, cwd=str(cwd), env={**os.environ, **command.env},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt", creationflags=creationflags,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2)
            except asyncio.TimeoutError:
                if os.name == "nt":
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill", "/PID", str(process.pid), "/T", "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.wait()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = await process.communicate()
        return SandboxExecutionResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode(errors="replace"), stderr=stderr.decode(errors="replace"),
            duration_ms=int((time.monotonic() - started) * 1000), timed_out=timed_out,
        )

    async def stream_command_output(self, sandbox_id: str, command: SandboxCommand):
        result = await self.execute_command(sandbox_id, command)
        for line in result.stdout.splitlines():
            yield line
        for line in result.stderr.splitlines():
            yield line

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        self._roots.pop(sandbox_id, None)
