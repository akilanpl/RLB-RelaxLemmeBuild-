import asyncio
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from backend.app.ai.gateway import AIRequest, ProviderGateway, QuotaGuardedGateway, AIGatewayError, AIResponse
from backend.app.models.agent import AgentRole
from backend.app.models.provider import AgentWorkerMapping, Loadout, Worker
from backend.app.providers.adapters import ADAPTER_REGISTRY, GroqAdapter
from backend.app.providers.resolver import RuntimeResolver
from backend.app.services.composition import build_agent_services
from backend.app.providers.types import ChatMessage, CompletionRequest, CompletionResponse, EncryptedCredentials, ModelUsage
from backend.app.services.credential_service import CredentialService
from backend.app.repositories.provider import InMemoryProviderRepository


def setup_runtime():
    user, workspace, task = uuid4(), uuid4(), uuid4()
    service = CredentialService(b"a" * 32)
    resolver = RuntimeResolver(service)
    worker = Worker(id="worker-a", provider_id="groq", model_name="model-a",
                    context_window_tokens=1000, max_output_tokens=100,
                    created_at=datetime.now(timezone.utc))
    resolver.register_worker(worker)
    resolver.register_credential(user, "groq", service.encrypt("secret-provider-key"))
    loadout = Loadout(
        id=uuid4(), user_id=user, name="default",
        mappings={AgentRole.PLANNER: AgentWorkerMapping(primary_worker_id=worker.id)},
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    resolver.register_loadout(user, loadout)
    resolver.switch_loadout(user, workspace, loadout.id)
    return resolver, user, workspace, task, loadout


def test_adapter_registry_and_runtime_resolution():
    assert {"groq", "gemini", "openai", "openrouter"} <= set(ADAPTER_REGISTRY)
    resolver, user, workspace, task, _ = setup_runtime()
    runtime = resolver.resolve(user, workspace, task, AgentRole.PLANNER.value)
    assert (runtime.worker_id, runtime.provider_id, runtime.model_name) == ("worker-a", "groq", "model-a")
    assert "secret-provider-key" not in str(runtime.run_metadata())


def test_production_composition_shares_one_runtime_resolver():
    services = build_agent_services()
    assert services.resolver is not None
    assert services.planner.runtime_resolver is services.resolver
    assert services.coder.runtime_resolver is services.resolver
    assert services.reviewer.runtime_resolver is services.resolver


def test_credentials_are_encrypted_and_not_exposed():
    service = CredentialService(b"a" * 32)
    encrypted = service.encrypt("secret-provider-key")
    assert service.decrypt(encrypted) == "secret-provider-key"
    assert "secret-provider-key" not in encrypted.ciphertext
    assert "secret-provider-key" not in service.fingerprint("secret-provider-key")


def test_temporary_override_is_scoped_and_expires():
    resolver, user, workspace, task, loadout = setup_runtime()
    resolver.register_worker(Worker(id="worker-b", provider_id="groq", model_name="model-b",
                                    context_window_tokens=1000, max_output_tokens=100,
                                    created_at=datetime.now(timezone.utc)))
    resolver.set_override(user, task, AgentRole.PLANNER.value, "worker-b",
                         datetime.now(timezone.utc) + timedelta(minutes=1))
    assert resolver.resolve(user, workspace, task, AgentRole.PLANNER.value).worker_id == "worker-b"
    resolver.set_override(user, task, AgentRole.PLANNER.value, "worker-b",
                         datetime.now(timezone.utc) - timedelta(seconds=1))
    assert resolver.resolve(user, workspace, task, AgentRole.PLANNER.value).worker_id == "worker-a"
    assert loadout.mappings[AgentRole.PLANNER].primary_worker_id == "worker-a"


def test_persisted_configuration_survives_resolver_recreation_and_stale_state_is_replaced():
    user, workspace, task = uuid4(), uuid4(), uuid4()
    service = CredentialService(b"a" * 32)
    repository = InMemoryProviderRepository()
    worker = Worker(id="worker-a", provider_id="groq", model_name="model-a",
                    context_window_tokens=1000, max_output_tokens=100,
                    created_at=datetime.now(timezone.utc))
    loadout = Loadout(
        id=uuid4(), user_id=user, name="default",
        mappings={AgentRole.PLANNER: AgentWorkerMapping(primary_worker_id=worker.id)},
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    asyncio.run(repository.save_worker(worker.model_dump()))
    asyncio.run(repository.save_credential(user, {
        "provider_id": "groq",
        "encrypted_api_key": service.encrypt("secret-provider-key").__dict__,
    }))
    asyncio.run(repository.save_loadout({**loadout.model_dump(), "mappings": loadout.mappings}))
    asyncio.run(repository.switch_loadout(user, workspace, loadout.id))
    resolver = RuntimeResolver(service, repository=repository)
    asyncio.run(resolver.hydrate())
    assert resolver.resolve(user, workspace, task, "planner").worker_id == "worker-a"
    worker_b = worker.model_copy(update={"id": "worker-b", "model_name": "model-b"})
    loadout_b = loadout.model_copy(update={
        "id": uuid4(),
        "mappings": {AgentRole.PLANNER: AgentWorkerMapping(primary_worker_id="worker-b")},
    })
    asyncio.run(repository.save_worker(worker_b.model_dump()))
    asyncio.run(repository.save_loadout({**loadout_b.model_dump(), "mappings": loadout_b.mappings}))
    asyncio.run(repository.switch_loadout(user, workspace, loadout_b.id))
    asyncio.run(resolver.hydrate())
    assert resolver.resolve(user, workspace, task, "planner").worker_id == "worker-b"


def test_cross_user_loadout_and_credential_access_is_denied():
    resolver, user, workspace, task, loadout = setup_runtime()
    with pytest.raises(PermissionError):
        resolver.switch_loadout(uuid4(), workspace, loadout.id)


def test_provider_gateway_keeps_secret_out_of_response():
    service = CredentialService(b"a" * 32)

    class Adapter:
        provider_id = "fake"
        async def generate_completion(self, request, credentials):
            return CompletionResponse(id="r", model=request.model,
                message=ChatMessage(role="assistant", content="ok"),
                usage=ModelUsage(), finish_reason="stop")

    encrypted = service.encrypt("secret-provider-key")
    response = asyncio.run(ProviderGateway(
        Adapter(), EncryptedCredentials(provider_id="fake", **encrypted.__dict__), "model"
    ).generate(AIRequest(system_prompt="s", user_prompt="u")))
    assert "secret-provider-key" not in response.model_dump_json()


def test_openai_compatible_adapter_sends_bearer_secret(monkeypatch):
    service = CredentialService(b"a" * 32)
    encrypted = service.encrypt("secret-provider-key")
    captured = {}

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"id": "r", "model": "m", "choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, url, headers, json):
            captured.update(headers=headers)
            return Response()

    import backend.app.providers.adapters as module
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: Client())
    asyncio.run(GroqAdapter(service).generate_completion(
        CompletionRequest(model="m", messages=[ChatMessage(role="user", content="hi")]),
        EncryptedCredentials(provider_id="groq", **encrypted.__dict__),
    ))
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    assert captured["headers"]["Authorization"].endswith("key")


def test_quota_guard_blocks_duplicate_calls_without_provider_access():
    class FakeGateway:
        calls = 0
        def validate_configuration(self): pass
        async def generate(self, request):
            self.calls += 1
            return AIResponse(content="{}")

    fake = FakeGateway()
    guarded = QuotaGuardedGateway(fake, max_calls=1, max_output_tokens=10)
    asyncio.run(guarded.generate(AIRequest(system_prompt="s", user_prompt="u", max_tokens=1)))
    with pytest.raises(AIGatewayError, match="call limit"):
        asyncio.run(guarded.generate(AIRequest(system_prompt="s", user_prompt="u", max_tokens=1)))
    assert fake.calls == 1


def test_quota_guard_blocks_excess_output_tokens():
    class FakeGateway:
        def validate_configuration(self): pass
        async def generate(self, request):
            return AIResponse(content="{}")

    guarded = QuotaGuardedGateway(FakeGateway(), max_calls=2, max_output_tokens=2)
    with pytest.raises(AIGatewayError, match="token limit"):
        asyncio.run(guarded.generate(AIRequest(system_prompt="s", user_prompt="u", max_tokens=3)))
