"""Abstract driver protocol for isolated execution sandboxes."""

from abc import ABC, abstractmethod
from typing import AsyncIterator
from uuid import UUID
from backend.app.sandbox.types import SandboxLimits, SandboxCommand, SandboxExecutionResult


class BaseSandboxDriver(ABC):
    """
    Abstract driver for containerized/microVM sandboxes (e.g. gVisor, Docker, Firecracker).
    Guarantees isolation from the host machine.
    """

    @abstractmethod
    async def create_sandbox(
        self, 
        workspace_id: UUID, 
        staging_root_path: str, 
        limits: SandboxLimits
    ) -> str:
        """Provision an isolated execution environment; returns sandbox handle ID."""
        pass

    @abstractmethod
    async def execute_command(
        self, 
        sandbox_id: str, 
        command: SandboxCommand
    ) -> SandboxExecutionResult:
        """Run an isolated command within the sandbox."""
        pass

    async def execute_command_observed(self, sandbox_id, command, on_output):
        """Compatibility path; drivers with live output override this method."""
        result = await self.execute_command(sandbox_id, command)
        await on_output('stdout', result.stdout)
        await on_output('stderr', result.stderr)
        return result

    @abstractmethod
    async def stream_command_output(
        self, 
        sandbox_id: str, 
        command: SandboxCommand
    ) -> AsyncIterator[str]:
        """Stream command stdout/stderr line by line."""
        pass

    @abstractmethod
    async def destroy_sandbox(self, sandbox_id: str) -> None:
        """Tear down container/microVM and free system resources."""
        pass
