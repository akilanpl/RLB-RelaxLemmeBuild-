from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.app.sandbox.daytona import DaytonaSandboxDriver
from backend.app.sandbox.types import SandboxCommand, SandboxLimits
from backend.app.services.production_runtime import build_production_runtime
from backend.app.services.supabase_queue import SupabaseQueueAdapter
from backend.app.storage.supabase import SupabaseStorageBackend


class FakeQueueClient:
    def __init__(self):
        self.sent = []
        self.acked = []

    async def send(self, name, payload):
        self.sent.append((name, payload))

    async def claim(self, name, worker):
        return {"receipt": "r", "message": self.sent[0][1]} if self.sent else None

    async def extend(self, *args):
        return None

    async def ack(self, name, receipt):
        self.acked.append(receipt)

    async def release(self, *args):
        return None


class FakeStorageClient:
    def __init__(self):
        self.files = {}

    async def upload(self, bucket, path, content, upsert=True):
        self.files[(bucket, path)] = content

    async def download(self, bucket, path):
        return self.files[(bucket, path)]

    async def remove(self, bucket, paths):
        for path in paths:
            self.files.pop((bucket, path), None)

    async def list(self, bucket, prefix):
        return [path for (stored_bucket, path) in self.files if stored_bucket == bucket and path.startswith(prefix)]


class FakeSandbox:
    id = "sandbox-1"
    def __init__(self):
        self.commands = []
        self.destroyed = False

    async def mkdir(self, path): return None

    async def create(self, **kwargs): return self

    async def restore_snapshot(self, *args): return None

    async def execute(self, sandbox_id, command, **kwargs):
        self.commands.append(command)
        return type("Result", (), {"exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 2})()

    async def stream(self, *args, **kwargs):
        yield "ok"

    async def destroy(self, sandbox_id):
        self.destroyed = True


@pytest.mark.asyncio
async def test_supabase_queue_payload_and_ack_contract():
    client = FakeQueueClient()
    adapter = SupabaseQueueAdapter(client)
    task_id = uuid4()
    payload = await adapter.enqueue(task_id, uuid4(), 7)
    assert payload["task_id"] == str(task_id)
    assert payload["task_version"] == 7
    assert set(payload) == {"task_id", "task_version", "requested_at"}
    await adapter.complete("r")
    assert client.acked == ["r"]


@pytest.mark.asyncio
async def test_supabase_storage_snapshot_and_artifact_isolation():
    storage = SupabaseStorageBackend(FakeStorageClient(), "artifacts")
    await storage.write_file("workspace-1/snapshot/app.py", b"ok")
    assert await storage.read_file("workspace-1/snapshot/app.py") == b"ok"
    stats = await storage.get_file_stats("workspace-1/snapshot/app.py")
    assert stats["size_bytes"] == 2
    with pytest.raises(Exception):
        await storage.write_file("../secret", b"no")


@pytest.mark.asyncio
async def test_daytona_contract_maps_execution_and_cleanup():
    client = FakeSandbox()
    driver = DaytonaSandboxDriver(client)
    sandbox_id = await driver.create_sandbox(uuid4(), "staging/root", SandboxLimits())
    result = await driver.execute_command(sandbox_id, SandboxCommand(cmd="pytest"))
    assert result.exit_code == 0
    assert result.stdout == "ok"
    await driver.destroy_sandbox(sandbox_id)
    assert client.destroyed is True


def test_production_composition_selects_cloud_boundaries(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")
    from backend.app.core.config import get_settings
    get_settings.cache_clear()
    runtime = build_production_runtime(FakeQueueClient(), FakeStorageClient(), FakeSandbox())
    assert isinstance(runtime.queue, SupabaseQueueAdapter)
    assert isinstance(runtime.storage, SupabaseStorageBackend)
    assert isinstance(runtime.sandbox, DaytonaSandboxDriver)
    get_settings.cache_clear()
