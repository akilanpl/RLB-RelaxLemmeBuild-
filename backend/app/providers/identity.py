"""Map user-entered provider names to existing adapter identities.

Display names are not execution identifiers. Resolution always lands on a
canonical adapter id from ADAPTER_REGISTRY, or on an already-persisted
provider that already has a usable OpenAI-compatible base URL.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.providers.adapters import (
    ADAPTER_REGISTRY,
    GeminiAdapter,
    GroqAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
)


class UnsupportedProviderError(ValueError):
    """Raised when a typed name cannot be bound to an existing adapter."""


@dataclass(frozen=True)
class ResolvedProvider:
    id: str
    name: str
    base_url: str
    adapter_id: str
    product_label: str


def _origin(endpoint: str) -> str:
    return endpoint.replace("/chat/completions", "").rstrip("/")


CANONICAL_PROVIDERS: dict[str, ResolvedProvider] = {
    "gemini": ResolvedProvider(
        id="gemini",
        name="Google Gemini",
        base_url=_origin(GeminiAdapter.endpoint),
        adapter_id="gemini",
        product_label="Google AI Studio",
    ),
    "groq": ResolvedProvider(
        id="groq",
        name="Groq",
        base_url=_origin(GroqAdapter.endpoint),
        adapter_id="groq",
        product_label="Groq Cloud",
    ),
    "openai": ResolvedProvider(
        id="openai",
        name="OpenAI",
        base_url=_origin(OpenAIAdapter.endpoint),
        adapter_id="openai",
        product_label="OpenAI API",
    ),
    "openrouter": ResolvedProvider(
        id="openrouter",
        name="OpenRouter",
        base_url=_origin(OpenRouterAdapter.endpoint),
        adapter_id="openrouter",
        product_label="OpenRouter",
    ),
}

_ALIASES: dict[str, str] = {
    "gemini": "gemini",
    "google gemini": "gemini",
    "google ai studio": "gemini",
    "google ai": "gemini",
    "google aistudio": "gemini",
    "aistudio": "gemini",
    "google": "gemini",
    "groq": "groq",
    "openai": "openai",
    "open ai": "openai",
    "openrouter": "openrouter",
    "open router": "openrouter",
}


def normalize_provider_label(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def resolve_provider_identity(
    raw_name: str,
    existing_providers: list[dict] | None = None,
) -> ResolvedProvider:
    label = normalize_provider_label(raw_name)
    if not label:
        raise UnsupportedProviderError("Provider name is required.")

    canonical_id = _ALIASES.get(label)
    if canonical_id is None and label in CANONICAL_PROVIDERS:
        canonical_id = label
    if canonical_id is not None:
        resolved = CANONICAL_PROVIDERS[canonical_id]
        if resolved.adapter_id not in ADAPTER_REGISTRY:
            raise UnsupportedProviderError("Provider adapter is not registered.")
        return resolved

    for row in existing_providers or []:
        row_id = str(row.get("id") or "")
        row_name = normalize_provider_label(str(row.get("name") or ""))
        base_url = str(row.get("base_url") or "").strip()
        if not row_id:
            continue
        if normalize_provider_label(row_id) != label and row_name != label:
            continue
        if row_id in ADAPTER_REGISTRY:
            canonical = CANONICAL_PROVIDERS.get(row_id)
            if canonical:
                return canonical
            return ResolvedProvider(
                id=row_id,
                name=str(row.get("name") or row_id),
                base_url=base_url,
                adapter_id=row_id,
                product_label=str(row.get("name") or row_id),
            )
        # Custom OpenAI-compatible is only valid when an endpoint is already stored.
        if row_id in {"custom", "custom_openai_compatible"} and base_url:
            return ResolvedProvider(
                id=row_id,
                name=str(row.get("name") or "Custom OpenAI-compatible"),
                base_url=base_url,
                adapter_id="custom_openai_compatible",
                product_label="Custom OpenAI-compatible",
            )

    raise UnsupportedProviderError(
        "Unsupported provider. Use Gemini, Groq, OpenAI, or OpenRouter."
    )


def worker_id_for(user_id, provider_id: str, model_name: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (model_name or "").strip()).strip("-")[:80] or "model"
    return f"u-{user_id}-p-{provider_id}-m-{slug}"


def worker_owned_by(worker_id: str, user_id) -> bool:
    return str(worker_id).startswith(f"u-{user_id}-")


def masked_fingerprint(fingerprint: str) -> str:
    digest = fingerprint.split("...")[-1] if fingerprint and "..." in fingerprint else (fingerprint or "")[-8:]
    return f"••••••••{digest}"
