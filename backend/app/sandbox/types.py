"""Sandbox execution types and resource limit specifications."""

from typing import Optional, Dict
from pydantic import BaseModel, Field


class SandboxLimits(BaseModel):
    cpu_cores: float = 2.0
    memory_mb: int = 4096
    timeout_seconds: int = 600
    disk_limit_mb: int = 10240
    network_enabled: bool = False


class SandboxCommand(BaseModel):
    cmd: str = Field(..., description="Shell command string to execute inside sandbox")
    cwd: Optional[str] = Field(None, description="Relative working directory inside sandbox")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    timeout_seconds: Optional[int] = None


class SandboxExecutionResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
