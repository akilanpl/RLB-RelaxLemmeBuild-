import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.app.desktop_lifecycle import install_desktop_lifecycle, parent_alive


def test_live_parent_exists():
    assert parent_alive(os.getpid())


@pytest.mark.asyncio
async def test_authenticated_desktop_shutdown_and_worker_readiness(monkeypatch, tmp_path):
    import base64
    from backend.app.core.config import get_settings
    from backend.app.main import create_app
    monkeypatch.setenv("ENVIRONMENT", "desktop")
    monkeypatch.setenv("RLB_LOCAL_API_TOKEN", "desktop-token")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"a" * 32).decode())
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("RUN_EMBEDDED_WORKER", "true")
    monkeypatch.setenv("RLB_RUNTIME_INSTANCE_ID", "own-instance")
    get_settings.cache_clear()
    app = create_app()
    @asynccontextmanager
    async def lifespan(app):
        app.state.worker_task = asyncio.create_task(asyncio.sleep(100))
        try:
            yield
        finally:
            app.state.worker_task.cancel()
            await asyncio.gather(app.state.worker_task, return_exceptions=True)
    app.router.lifespan_context = lifespan
    server = SimpleNamespace(should_exit=False)
    install_desktop_lifecycle(app, server)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                assert (await client.post('/api/v1/desktop/shutdown')).status_code == 401
                assert not server.should_exit
                headers = {"X-RLB-Local-Token": "desktop-token"}
                response = await client.get('/api/v1/desktop/status', headers=headers)
                assert response.json() == {"instance_id": "own-instance", "worker_ready": True}
                response = await client.post('/api/v1/desktop/shutdown', headers=headers)
                assert response.status_code == 200 and server.should_exit
                app.state.worker_task.cancel()
                await asyncio.gather(app.state.worker_task, return_exceptions=True)
                assert (await client.get('/api/v1/desktop/status', headers=headers)).status_code == 503
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_lost_parent_requests_clean_shutdown(monkeypatch):
    monkeypatch.setenv("RLB_PARENT_PID", "12345")
    monkeypatch.setattr('backend.app.desktop_lifecycle.parent_alive', lambda pid: False)
    app = FastAPI()
    server = SimpleNamespace(should_exit=False)
    install_desktop_lifecycle(app, server)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert server.should_exit
