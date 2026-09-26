"""Backward-compatible Groq gateway built on the provider contract."""

import httpx

from backend.app.ai.gateway import AIGateway, AIRequest, AIResponse, AIGatewayError
from backend.app.core.config import get_settings


class GroqGateway(AIGateway):
    endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL

    def validate_configuration(self) -> None:
        if not self.api_key:
            raise AIGatewayError("Groq is not configured.")
        if not self.model:
            raise AIGatewayError("Groq model is not configured.")

    async def generate(self, request: AIRequest) -> AIResponse:
        self.validate_configuration()
        payload = {
            "model": request.model or self.model,
            "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
            if response.status_code == 429:
                raise AIGatewayError("Groq rate limit exceeded.")
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return AIResponse(
                content=message,
                model=data.get("model"),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                metadata={"provider": "groq"},
            )
        except AIGatewayError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIGatewayError("Groq request failed.") from exc
