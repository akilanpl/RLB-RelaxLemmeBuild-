"""Provider adapters. Vendor wire formats are isolated here."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from backend.app.providers.base import BaseProviderAdapter
from backend.app.providers.types import (
    ChatMessage, CompletionChunk, CompletionRequest, CompletionResponse,
    EncryptedCredentials, ModelUsage,
)
from backend.app.services.credential_service import CredentialService, EncryptedSecret


class OpenAICompatibleAdapter(BaseProviderAdapter):
    endpoint = ""
    default_model = ""

    def __init__(self, credential_service: CredentialService | None = None):
        self.credential_service = credential_service or CredentialService()

    def _key(self, credentials: EncryptedCredentials) -> str:
        return self.credential_service.decrypt(EncryptedSecret(
            ciphertext=credentials.ciphertext, iv=credentials.iv, tag=credentials.tag
        ))

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {"Authorization": "Bearer" + chr(32) + api_key}

    @staticmethod
    def _payload(request: CompletionRequest) -> dict:
        payload = request.model_dump(exclude_none=True)
        payload["messages"] = [message.model_dump(exclude_none=True) for message in request.messages]
        if request.tools:
            payload["tools"] = [
                {"type": "function", "function": tool.model_dump(exclude_none=True)}
                for tool in request.tools
            ]
        return payload

    async def generate_completion(self, request, credentials):
        api_key = self._key(credentials)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.endpoint, headers=self._headers(api_key), json=self._payload(request))
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return CompletionResponse(
            id=data.get("id", ""), model=data.get("model", request.model),
            message=ChatMessage(**choice["message"]),
            usage=ModelUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    async def stream_completion(self, request, credentials) -> AsyncIterator[CompletionChunk]:
        api_key = self._key(credentials)
        payload = self._payload(request)
        payload["stream"] = True
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", self.endpoint, headers=self._headers(api_key), json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line[6:] != "[DONE]":
                        item = json.loads(line[6:])
                        choice = item.get("choices", [{}])[0]
                        yield CompletionChunk(
                            delta_content=choice.get("delta", {}).get("content"),
                            finish_reason=choice.get("finish_reason"),
                        )

    async def validate_credentials(self, credentials) -> bool:
        try:
            await self.generate_completion(CompletionRequest(
                model=self.default_model,
                messages=[ChatMessage(role="user", content="ping")],
                max_tokens=1,
            ), credentials)
            return True
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return False


class GroqAdapter(OpenAICompatibleAdapter):
    provider_id = "groq"
    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    default_model = "llama-3.3-70b-versatile"


class GeminiAdapter(OpenAICompatibleAdapter):
    provider_id = "gemini"
    endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    default_model = "gemini-2.5-flash"


class OpenAIAdapter(OpenAICompatibleAdapter):
    provider_id = "openai"
    endpoint = "https://api.openai.com/v1/chat/completions"
    default_model = "gpt-4o-mini"


class OpenRouterAdapter(OpenAICompatibleAdapter):
    provider_id = "openrouter"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    default_model = "meta-llama/llama-3.3-70b-instruct"


class CustomOpenAICompatibleAdapter(OpenAICompatibleAdapter):
    provider_id = "custom_openai_compatible"

    def __init__(self, endpoint: str, default_model: str = "", credential_service=None):
        super().__init__(credential_service)
        self.endpoint = endpoint.rstrip("/") + "/chat/completions"
        self.default_model = default_model


ADAPTER_REGISTRY = {
    "groq": GroqAdapter,
    "gemini": GeminiAdapter,
    "openai": OpenAIAdapter,
    "openrouter": OpenRouterAdapter,
}


def register_adapter(provider_id: str, adapter_type: type[BaseProviderAdapter]) -> None:
    if not provider_id.strip():
        raise ValueError("Provider ID is required")
    ADAPTER_REGISTRY[provider_id] = adapter_type
