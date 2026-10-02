import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app


@pytest.mark.asyncio
async def test_desktop_local_api_requires_ephemeral_token_and_allowed_origin(monkeypatch):
    settings = Settings(
        ENVIRONMENT="development",
        BACKEND_CORS_ORIGINS=["http://127.0.0.1:3000"],
    )
    monkeypatch.setattr("backend.app.main.get_settings", lambda: settings)
    monkeypatch.setenv("RLB_LOCAL_API_TOKEN", "local-session-secret")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://127.0.0.1:8000",
    )

    no_token = await client.get("/api/v1/openapi.json")
    assert no_token.status_code == 401
    wrong_origin = await client.get(
        "/api/v1/openapi.json",
        headers={"X-RLB-Local-Token": "local-session-secret", "Origin": "https://attacker.example"},
    )
    assert wrong_origin.status_code == 403
    allowed = await client.get(
        "/api/v1/openapi.json",
        headers={"X-RLB-Local-Token": "local-session-secret", "Origin": "http://127.0.0.1:3000"},
    )
    assert allowed.status_code == 200
    health = await client.get("/health")
    assert health.status_code == 200
    await client.aclose()


@pytest.mark.asyncio
async def test_desktop_origin_accepts_only_loopback(monkeypatch):
    desktop_settings = Settings(
        ENVIRONMENT="development",
        RLB_DESKTOP_ORIGIN="http://127.0.0.1:43210",
    )
    monkeypatch.setattr(
        "backend.app.main.get_settings",
        lambda: desktop_settings,
    )
    monkeypatch.setenv("RLB_LOCAL_API_TOKEN", "desktop-token")
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://127.0.0.1:8000",
    )
    response = await client.get(
        "/api/v1/openapi.json",
        headers={
            "Origin": "http://127.0.0.1:43210",
            "X-RLB-Local-Token": "desktop-token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:43210"
    await client.aclose()

    monkeypatch.setattr(
        "backend.app.main.get_settings",
        lambda: Settings(ENVIRONMENT="development", RLB_DESKTOP_ORIGIN="https://attacker.example"),
    )
    with pytest.raises(ValueError, match="loopback"):
        create_app()
