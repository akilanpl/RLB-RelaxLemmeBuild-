import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.api.v1 import providers as providers_api
from backend.app.main import app
from backend.app.providers.identity import (
    UnsupportedProviderError,
    resolve_provider_identity,
)
from backend.app.services.credential_service import CredentialService, EncryptedSecret


def test_gemini_aliases_resolve_to_gemini_adapter():
    for name in ("Gemini", "Google Gemini", "Google AI Studio", "google"):
        resolved = resolve_provider_identity(name)
        assert resolved.id == "gemini"
        assert resolved.adapter_id == "gemini"
        assert resolved.name == "Google Gemini"


def test_known_providers_resolve_to_their_adapters():
    assert resolve_provider_identity("Groq").id == "groq"
    assert resolve_provider_identity("OpenAI").id == "openai"
    assert resolve_provider_identity("OpenRouter").id == "openrouter"


def test_unsupported_provider_names_are_rejected():
    with pytest.raises(UnsupportedProviderError):
        resolve_provider_identity("Anthropic")
    with pytest.raises(UnsupportedProviderError):
        resolve_provider_identity("")


def test_existing_custom_openai_compatible_provider_is_allowed_only_with_base_url():
    existing = [{"id": "custom", "name": "My Gateway", "base_url": "https://llm.example/v1"}]
    resolved = resolve_provider_identity("My Gateway", existing)
    assert resolved.id == "custom"
    assert resolved.adapter_id == "custom_openai_compatible"
    with pytest.raises(UnsupportedProviderError):
        resolve_provider_identity("My Gateway", [{"id": "custom", "name": "My Gateway", "base_url": ""}])


def _reset_provider_state():
    providers_api._credentials.clear()
    providers_api._providers.clear()
    providers_api._workers.clear()
    providers_api._loadouts.clear()
    providers_api._workspace_loadouts.clear()
    providers_api._overrides.clear()


@pytest.fixture
def client():
    _reset_provider_state()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_empty_provider_catalog_does_not_break_loadouts(client):
    user = str(uuid4())
    async with client:
        providers = await client.get("/api/v1/providers", headers={"x-user-id": user})
        credentials = await client.get("/api/v1/providers/credentials", headers={"x-user-id": user})
        assert providers.status_code == 200
        assert credentials.status_code == 200
        assert providers.json() == []
        assert credentials.json() == []


@pytest.mark.asyncio
async def test_manual_provider_name_saves_encrypted_gemini_credential(client):
    user = str(uuid4())
    secret = "gemini-test-secret-value-not-for-logs"
    async with client:
        response = await client.put(
            "/api/v1/providers/credentials",
            headers={"x-user-id": user},
            json={"provider_name": "Google Gemini", "api_key": secret},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["provider_id"] == "gemini"
        assert body["provider_name"] == "Google Gemini"
        assert "encrypted_api_key" not in body
        assert secret not in str(body)
        listed = await client.get("/api/v1/providers/credentials", headers={"x-user-id": user})
        rows = listed.json()
        assert len(rows) == 1
        assert rows[0]["provider_id"] == "gemini"
        assert secret not in str(rows)


@pytest.mark.asyncio
async def test_duplicate_aliases_update_the_same_provider_credential(client):
    user = str(uuid4())
    async with client:
        first = await client.put(
            "/api/v1/providers/credentials",
            headers={"x-user-id": user},
            json={"provider_name": "Gemini", "api_key": "first-secret-key-aaaa"},
        )
        second = await client.put(
            "/api/v1/providers/credentials",
            headers={"x-user-id": user},
            json={"provider_name": "Google Gemini", "api_key": "second-secret-key-bbbb"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["provider_id"] == second.json()["provider_id"] == "gemini"
        listed = await client.get("/api/v1/providers/credentials", headers={"x-user-id": user})
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == second.json()["id"]
        assert "first-secret-key-aaaa" not in str(listed.json())
        assert "second-secret-key-bbbb" not in str(listed.json())
        assert len(providers_api._providers) == 1


@pytest.mark.asyncio
async def test_groq_openai_and_openrouter_names_resolve_on_save(client):
    user = str(uuid4())
    async with client:
        for name, provider_id in (("Groq", "groq"), ("OpenAI", "openai"), ("OpenRouter", "openrouter")):
            response = await client.put(
                "/api/v1/providers/credentials",
                headers={"x-user-id": user},
                json={"provider_name": name, "api_key": f"{provider_id}-secret-value-zzzz"},
            )
            assert response.status_code == 200
            assert response.json()["provider_id"] == provider_id
        listed = await client.get("/api/v1/providers/credentials", headers={"x-user-id": user})
        assert {row["provider_id"] for row in listed.json()} == {"groq", "openai", "openrouter"}


@pytest.mark.asyncio
async def test_unsupported_provider_name_is_rejected_without_persisting(client):
    user = str(uuid4())
    async with client:
        response = await client.put(
            "/api/v1/providers/credentials",
            headers={"x-user-id": user},
            json={"provider_name": "Anthropic", "api_key": "should-not-be-saved"},
        )
        assert response.status_code == 400
        listed = await client.get("/api/v1/providers/credentials", headers={"x-user-id": user})
        assert listed.json() == []
        assert "should-not-be-saved" not in str(response.json())


@pytest.mark.asyncio
async def test_credentials_are_user_isolated(client):
    alice, bob = str(uuid4()), str(uuid4())
    secret = "alice-only-secret-key-value"
    async with client:
        saved = await client.put(
            "/api/v1/providers/credentials",
            headers={"x-user-id": alice},
            json={"provider_name": "Groq", "api_key": secret},
        )
        assert saved.status_code == 200
        bob_list = await client.get("/api/v1/providers/credentials", headers={"x-user-id": bob})
        alice_list = await client.get("/api/v1/providers/credentials", headers={"x-user-id": alice})
        assert bob_list.json() == []
        assert len(alice_list.json()) == 1
        assert secret not in str(bob_list.json())
        assert secret not in str(alice_list.json())


def test_saved_secret_is_encrypted_in_process_store():
    _reset_provider_state()
    user = uuid4()
    secret = "in-memory-plain-key-must-not-remain"

    async def _save():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.put(
                "/api/v1/providers/credentials",
                headers={"x-user-id": str(user)},
                json={"provider_name": "OpenAI", "api_key": secret},
            )

    response = asyncio.run(_save())
    assert response.status_code == 200
    stored = providers_api._credentials[(user, "openai")]
    assert stored["encrypted_api_key"] != secret
    assert secret not in stored["encrypted_api_key"]
    blob = __import__("json").loads(stored["encrypted_api_key"])
    decrypted = CredentialService().decrypt(EncryptedSecret(**blob))
    assert decrypted == secret
    assert secret not in stored["key_fingerprint"][5:]
