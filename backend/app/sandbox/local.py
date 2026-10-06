"""Local process execution with disposable project copies and bounded evidence."""
from __future__ import annotations

import asyncio
import os
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.sandbox.base import BaseSandboxDriver
from backend.app.sandbox.types import SandboxCommand, SandboxExecutionResult, SandboxLimits


class LocalWindowsSandboxDriver(BaseSandboxDriver):
    """Execute approved project checks locally without modifying approved source."""

    def __init__(self):
        self._roots: dict[str, Path] = {}
        self._temporary: dict[str, tempfile.TemporaryDirectory] = {}
        self._limits: dict[str, SandboxLimits] = {}
        self._python_paths: dict[str, str] = {}

    async def create_sandbox(self, workspace_id: UUID, staging_root_path: str,
                             limits: SandboxLimits) -> str:
        source = Path(staging_root_path).resolve()
        if not source.is_dir():
            raise ValueError("Execution root must be an existing directory.")
        temporary = tempfile.TemporaryDirectory(prefix="rlb-execution-")
        root = Path(temporary.name) / "project"
        try:
            def copy():
                for current, directories, files in os.walk(source, followlinks=False):
                    for name in [*directories, *files]:
                        entry = Path(current) / name
                        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                            raise ValueError("Execution snapshots cannot contain filesystem links.")
                shutil.copytree(source, root)
            copying = asyncio.create_task(asyncio.to_thread(copy))
            try:
                await asyncio.shield(copying)
            except asyncio.CancelledError:
                await copying
                raise
            # Python dependencies belong to a disposable environment, not the user's interpreter.
            python = os.environ.get("RLB_PROJECT_PYTHON") or shutil.which("python") or shutil.which("python3")
            python_path = None
            if python:
                result = await asyncio.create_subprocess_exec(
                    python, "-m", "venv", str(Path(temporary.name) / "python-env"),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    env={**{key: value for key, value in os.environ.items() if key in {"PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}},
                         "HOME": temporary.name, "USERPROFILE": temporary.name,
                         "TMP": temporary.name, "TEMP": temporary.name, "TMPDIR": temporary.name},
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
                try:
                    await asyncio.wait_for(result.wait(), timeout=60)
                except BaseException:
                    await self._terminate(result)
                    raise
                if result.returncode != 0:
                    raise RuntimeError("Could not create the local Python test environment.")
                python_path = str(Path(temporary.name) / "python-env" / ("Scripts" if os.name == "nt" else "bin"))
        except BaseException:
            temporary.cleanup()
            raise
        handle = str(uuid4())
        self._temporary[handle] = temporary
        self._roots[handle] = root.resolve()
        self._limits[handle] = limits
        if python_path:
            self._python_paths[handle] = python_path
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

    async def _terminate(self, process):
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                shutil.which("taskkill") or str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"),
                "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
            if process.returncode is None:
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await process.wait()

    async def execute_command(self, sandbox_id: str, command: SandboxCommand) -> SandboxExecutionResult:
        async def discard(stream, chunk):
            pass
        return await self.execute_command_observed(sandbox_id, command, discard)

    async def execute_command_observed(self, sandbox_id, command, on_output):
        cwd = self._cwd(sandbox_id, command)
        started = time.monotonic()
        timeout = min(command.timeout_seconds or 600, self._limits[sandbox_id].timeout_seconds)
        # Provider, device, database, and desktop credentials must never reach project commands.
        allowed = {"PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL"}
        env = {key: value for key, value in os.environ.items() if key in allowed}
        home = self._temporary[sandbox_id].name
        env.update(HOME=home, USERPROFILE=home, TMP=home, TEMP=home, TMPDIR=home, CI="true")
        tooling = os.environ.get("RLB_PROJECT_NODE_DIR")
        if tooling:
            env["PATH"] = tooling + os.pathsep + env.get("PATH", "")
        if sandbox_id in self._python_paths:
            env["PATH"] = self._python_paths[sandbox_id] + os.pathsep + env.get("PATH", "")
        env.update(command.env)
        process = await asyncio.create_subprocess_shell(
            command.cmd, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        output = {"stdout": bytearray(), "stderr": bytearray()}

        async def drain(name, stream):
            while chunk := await stream.read(8192):
                remaining = max(0, 64000 - len(output[name]))
                kept = chunk[:remaining]
                output[name].extend(kept)
                if kept:
                    await on_output(name, kept.decode(errors="replace"))

        readers = [asyncio.create_task(drain("stdout", process.stdout)),
                   asyncio.create_task(drain("stderr", process.stderr))]
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.gather(process.wait(), *readers), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await self._terminate(process)
        except BaseException:
            await self._terminate(process)
            raise
        finally:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
        return SandboxExecutionResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=output["stdout"].decode(errors="replace"), stderr=output["stderr"].decode(errors="replace"),
            duration_ms=int((time.monotonic() - started) * 1000), timed_out=timed_out,
        )

    async def stream_command_output(self, sandbox_id: str, command: SandboxCommand):
        result = await self.execute_command(sandbox_id, command)
        for line in (result.stdout + result.stderr).splitlines():
            yield line

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        self._roots.pop(sandbox_id, None)
        self._limits.pop(sandbox_id, None)
        self._python_paths.pop(sandbox_id, None)
        temporary = self._temporary.pop(sandbox_id, None)
        if temporary:
            await asyncio.to_thread(temporary.cleanup)
