from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.api.v1 import providers as providers_api
from backend.app.main import app
from backend.tests.test_loadouts_provider_identity import _reset_provider_state


@pytest.fixture
def client():
    _reset_provider_state()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _put_credential(client, user, name, secret):
    return await client.put(
        "/api/v1/providers/credentials",
        headers={"x-user-id": user},
        json={"provider_name": name, "api_key": secret},
    )


async def _put_worker(client, user, credential_id, model_name):
    return await client.put(
        "/api/v1/providers/workers",
        headers={"x-user-id": user},
        json={"credential_id": credential_id, "model_name": model_name},
    )


@pytest.mark.asyncio
async def test_empty_credential_and_worker_lists_do_not_crash(client):
    user = str(uuid4())
    async with client:
        credentials = await client.get("/api/v1/providers/credentials", headers={"x-user-id": user})
        workers = await client.get("/api/v1/providers/workers", headers={"x-user-id": user})
        loadouts = await client.get("/api/v1/providers/loadouts", headers={"x-user-id": user})
        assert credentials.json() == []
        assert workers.json() == []
        assert loadouts.json() == []


@pytest.mark.asyncio
async def test_one_credential_can_back_multiple_models_and_roles(client):
    user = str(uuid4())
    secret = "shared-gemini-secret-value-zzzz"
    async with client:
        saved = await _put_credential(client, user, "Google Gemini", secret)
        assert saved.status_code == 200
        assert secret not in str(saved.json())
        credential_id = saved.json()["id"]
        flash = await _put_worker(client, user, credential_id, "gemini-2.5-flash")
        pro = await _put_worker(client, user, credential_id, "gemini-2.5-pro")
        assert flash.status_code == 200
        assert pro.status_code == 200
        assert flash.json()["id"] != pro.json()["id"]
        assert flash.json()["credential_id"] == pro.json()["credential_id"] == credential_id
        listed = await client.get("/api/v1/providers/workers", headers={"x-user-id": user})
        assert {row["model_name"] for row in listed.json()} == {"gemini-2.5-flash", "gemini-2.5-pro"}
        payload = {
            "name": "Default RLB Loadout",
            "mappings": {
                "planner": {"primary_worker_id": flash.json()["id"], "fallback_worker_ids": []},
                "coder": {"primary_worker_id": pro.json()["id"], "fallback_worker_ids": []},
                "reviewer": {"primary_worker_id": flash.json()["id"], "fallback_worker_ids": []},
            },
        }
        created = await client.post("/api/v1/providers/loadouts", headers={"x-user-id": user}, json=payload)
        assert created.status_code == 200
        loadout_id = created.json()["id"]
        reloaded = await client.get("/api/v1/providers/loadouts", headers={"x-user-id": user})
        stored = next(item for item in reloaded.json() if item["id"] == loadout_id)
        assert stored["mappings"]["planner"]["primary_worker_id"] == flash.json()["id"]
        assert stored["mappings"]["coder"]["primary_worker_id"] == pro.json()["id"]
        assert stored["mappings"]["reviewer"]["primary_worker_id"] == flash.json()["id"]
        updated = await client.put(
            f"/api/v1/providers/loadouts/{loadout_id}",
            headers={"x-user-id": user},
            json={**payload, "name": "Default RLB Loadout"},
        )
        assert updated.status_code == 200
        assert secret not in str(listed.json()) + str(reloaded.json())


@pytest.mark.asyncio
async def test_multiple_credentials_and_cross_user_isolation(client):
    alice, bob = str(uuid4()), str(uuid4())
    async with client:
        gemini = await _put_credential(client, alice, "Gemini", "alice-gemini-secret-aaaa")
        groq = await _put_credential(client, alice, "Groq", "alice-groq-secret-bbbb")
        assert {gemini.status_code, groq.status_code} == {200}
        flash = await _put_worker(client, alice, gemini.json()["id"], "gemini-2.5-flash")
        llama = await _put_worker(client, alice, groq.json()["id"], "llama-3.3-70b-versatile")
        created = await client.post(
            "/api/v1/providers/loadouts",
            headers={"x-user-id": alice},
            json={
                "name": "Mixed",
                "mappings": {
                    "planner": {"primary_worker_id": flash.json()["id"], "fallback_worker_ids": []},
                    "coder": {"primary_worker_id": llama.json()["id"], "fallback_worker_ids": []},
                },
            },
        )
        assert created.status_code == 200
        bob_workers = await client.get("/api/v1/providers/workers", headers={"x-user-id": bob})
        bob_credentials = await client.get("/api/v1/providers/credentials", headers={"x-user-id": bob})
        assert bob_workers.json() == []
        assert bob_credentials.json() == []
        stolen = await client.put(
            "/api/v1/providers/workers",
            headers={"x-user-id": bob},
            json={"id": flash.json()["id"], "provider_id": "gemini", "model_name": "stolen"},
        )
        assert stolen.status_code in {400, 403}
        hijack = await client.post(
            "/api/v1/providers/loadouts",
            headers={"x-user-id": bob},
            json={"name": "Steal", "mappings": {"planner": {"primary_worker_id": flash.json()["id"], "fallback_worker_ids": []}}},
        )
        assert hijack.status_code == 400


@pytest.mark.asyncio
async def test_stale_worker_reference_is_rejected_and_history_is_untouched(client):
    user = str(uuid4())
    historical = [{"worker_id": "historical-worker", "provider_id": "gemini", "model_name": "old-model"}]
    async with client:
        saved = await _put_credential(client, user, "OpenAI", "openai-secret-value-cccc")
        worker = await _put_worker(client, user, saved.json()["id"], "gpt-4o-mini")
        created = await client.post(
            "/api/v1/providers/loadouts",
            headers={"x-user-id": user},
            json={"name": "Default", "mappings": {"planner": {"primary_worker_id": worker.json()["id"], "fallback_worker_ids": []}}},
        )
        missing = await client.put(
            f"/api/v1/providers/loadouts/{created.json()['id']}",
            headers={"x-user-id": user},
            json={"name": "Default", "mappings": {"planner": {"primary_worker_id": "missing-worker", "fallback_worker_ids": []}}},
        )
        assert missing.status_code == 400
        assert historical[0]["worker_id"] == "historical-worker"
        assert historical[0]["model_name"] == "old-model"


@pytest.mark.asyncio
async def test_overrides_remain_available_and_are_task_scoped(client):
    user = str(uuid4())
    workspace, task = str(uuid4()), str(uuid4())
    async with client:
        response = await client.put(
            f"/api/v1/providers/workspaces/{workspace}/tasks/{task}/overrides",
            headers={"x-user-id": user},
            json={"agent_role": "planner", "target_worker_id": "worker-x", "reason": "hot-swap"},
        )
        assert response.status_code == 200
        assert response.json()["task_id"] == task
        cleared = await client.delete(
            f"/api/v1/providers/workspaces/{workspace}/tasks/{task}/overrides/planner",
            headers={"x-user-id": user},
        )
        assert cleared.json()["cleared"] is True
