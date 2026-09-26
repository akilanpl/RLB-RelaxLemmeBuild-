"""Abstract interfaces for AI Providers, Workers, and Loadout Routers."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional, List
from backend.app.providers.types import (
    CompletionRequest,
    CompletionResponse,
    CompletionChunk,
    EncryptedCredentials,
)


class BaseProviderAdapter(ABC):
    """
    Abstract adapter for vendor LLM APIs (Groq, Gemini, OpenRouter).
    Isolates all vendor-specific wire formats and auth mechanisms.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider key, e.g. 'groq'."""
        pass

    @abstractmethod
    async def generate_completion(
        self, 
        request: CompletionRequest, 
        credentials: EncryptedCredentials
    ) -> CompletionResponse:
        """Generate a complete unary LLM response."""
        pass

    @abstractmethod
    async def stream_completion(
        self, 
        request: CompletionRequest, 
        credentials: EncryptedCredentials
    ) -> AsyncIterator[CompletionChunk]:
        """Stream response tokens and tool call fragments."""
        pass

    @abstractmethod
    async def validate_credentials(self, credentials: EncryptedCredentials) -> bool:
        """Check if provider API key is functional without throwing unhandled errors."""
        pass


class BaseWorker(ABC):
    """
    A concrete worker representing a model + adapter + configured hyperparameters.
    Models are stateless compute units; they do not hold persistent conversation state.
    """

    @property
    @abstractmethod
    def worker_id(self) -> str:
        pass

    @property
    @abstractmethod
    def provider_adapter(self) -> BaseProviderAdapter:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    @abstractmethod
    def context_window_tokens(self) -> int:
        pass


class LoadoutRouterResult:
    """Result of dispatching an agent prompt through the loadout layer."""
    def __init__(
        self,
        response: CompletionResponse,
        executed_worker_id: str,
        provider_id: str,
        model_name: str,
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
        initial_worker_id: Optional[str] = None
    ):
        self.response = response
        self.executed_worker_id = executed_worker_id
        self.provider_id = provider_id
        self.model_name = model_name
        self.fallback_used = fallback_used
        self.fallback_reason = fallback_reason
        self.initial_worker_id = initial_worker_id
