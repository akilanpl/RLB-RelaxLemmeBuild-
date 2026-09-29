"""Small provider-agnostic gateway contract."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel


class AIRequest(BaseModel):
    system_prompt: str
    user_prompt: str
    model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = None


class AIResponse(BaseModel):
    content: str
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    metadata: Dict[str, Any] = {}


class AIGatewayError(RuntimeError):
    """Safe application-level provider failure."""


class AIGateway(ABC):
    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResponse:
        pass

    @abstractmethod
    def validate_configuration(self) -> None:
        pass


class QuotaGuardedGateway(AIGateway):
    """Deterministic per-task call guard; never retries or falls back providers."""

    def __init__(self, gateway: AIGateway, max_calls: int, max_output_tokens: int):
        self.gateway = gateway
        self.max_calls = max_calls
        self.max_output_tokens = max_output_tokens
        self.calls = 0

    def validate_configuration(self) -> None:
        self.gateway.validate_configuration()

    async def generate(self, request: AIRequest) -> AIResponse:
        if self.calls >= self.max_calls:
            raise AIGatewayError("AI call limit reached.")
        if request.max_tokens is not None and request.max_tokens > self.max_output_tokens:
            raise AIGatewayError("AI output token limit exceeded.")
        self.calls += 1
        return await self.gateway.generate(request.model_copy(update={"max_tokens": request.max_tokens or self.max_output_tokens}))


class ProviderGateway(AIGateway):
    """Adapts a resolved worker/provider pair to the agent gateway contract."""

    def __init__(self, adapter, credentials, model: str, max_output_tokens: int | None = None):
        self.adapter = adapter
        self.credentials = credentials
        self.model = model
        self.max_output_tokens = max_output_tokens

    def validate_configuration(self) -> None:
        if not self.model:
            raise AIGatewayError("Resolved worker has no model.")
        if self.credentials is None:
            raise AIGatewayError("No credential is configured for the resolved provider.")

    async def generate(self, request: AIRequest) -> AIResponse:
        self.validate_configuration()
        from backend.app.providers.types import ChatMessage, CompletionRequest

        try:
            response = await self.adapter.generate_completion(
                CompletionRequest(
                    model=request.model or self.model,
                    messages=[
                        ChatMessage(role="system", content=request.system_prompt),
                        ChatMessage(role="user", content=request.user_prompt),
                    ],
                    temperature=request.temperature,
                    max_tokens=min(request.max_tokens or self.max_output_tokens, self.max_output_tokens) if self.max_output_tokens else request.max_tokens,
                ),
                self.credentials,
            )
            return AIResponse(
                content=response.message.content or "",
                model=response.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                metadata={"provider": self.adapter.provider_id},
            )
        except AIGatewayError:
            raise
        except Exception as exc:
            from backend.app.ai.failover import TransientProviderError
            import httpx
            if isinstance(exc, httpx.TimeoutException):
                raise TransientProviderError("Provider request timed out.") from exc
            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                if status == 401 or status == 403:
                    raise AIGatewayError("Provider authentication failed.") from exc
                if status == 404:
                    raise AIGatewayError("Provider model or endpoint is unavailable.") from exc
                if status == 429:
                    raise TransientProviderError("Provider rate limit exceeded.") from exc
                if status >= 500:
                    raise TransientProviderError("Provider is unavailable.") from exc
            if isinstance(exc, (KeyError, IndexError, TypeError, ValueError)):
                raise AIGatewayError("Provider returned a malformed response.") from exc
            if isinstance(exc, httpx.TransportError):
                raise TransientProviderError("Provider transport unavailable.") from exc
            if isinstance(exc, httpx.HTTPStatusError):
                raise AIGatewayError(f"Provider rejected the request (HTTP {exc.response.status_code}).") from exc
            if isinstance(exc, httpx.HTTPError):
                raise AIGatewayError("Provider request failed.") from exc
            raise AIGatewayError("Provider request failed.") from exc
