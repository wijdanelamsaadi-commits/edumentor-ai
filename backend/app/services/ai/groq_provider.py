from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from app.core.config import get_settings
from app.services.ai.ai_provider import AIProviderError, AIRequest, AIResponse

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider:
    provider_name = "groq"

    def __init__(self) -> None:
        self.settings = get_settings()

    def generate_structured(self, request: AIRequest) -> AIResponse:
        return self._generate(request, structured=True)

    def generate_text(self, request: AIRequest) -> AIResponse:
        return self._generate(request, structured=False)

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model_name": self.get_model_name(),
            "configured": bool(self.settings.get("groq_api_key")),
        }

    def get_model_name(self) -> str:
        return str(self.settings.get("ai_model") or self.settings.get("groq_model") or "openai/gpt-oss-20b")

    def get_usage_metadata(self, response: AIResponse) -> dict[str, Any]:
        usage = response.usage or {}
        return {
            "tokens_input": usage.get("prompt_tokens") or usage.get("input_tokens"),
            "tokens_output": usage.get("completion_tokens") or usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }

    def _generate(self, request: AIRequest, *, structured: bool) -> AIResponse:
        api_key = self.settings.get("groq_api_key")
        if not api_key:
            raise AIProviderError("Groq API key is not configured")

        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ]
        payload: dict[str, Any] = {
            "model": request.model_name or self.get_model_name(),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if is_gpt_oss_model(str(payload["model"])):
            payload["include_reasoning"] = False
            payload["reasoning_effort"] = "low"
        if structured and supports_response_format_json_object(str(payload["model"])):
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        data = self._post(payload, timeout_seconds=request.timeout_seconds)
        duration_ms = round((time.perf_counter() - started) * 1000)
        try:
            content = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("Groq response format is invalid") from exc

        usage = dict(data.get("usage") or {})
        usage["duration_ms"] = duration_ms
        return AIResponse(
            text=content,
            provider=self.provider_name,
            model_name=request.model_name or self.get_model_name(),
            usage=usage,
            raw={"id": data.get("id"), "created": data.get("created")},
        )

    def _post(self, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        request = urllib.request.Request(
            GROQ_CHAT_COMPLETIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings['groq_api_key']}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "EduMentorAI/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:500]
            except Exception:
                detail = ""
            raise AIProviderError(f"Groq request failed: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AIProviderError("Groq request failed") from exc


def get_ai_provider() -> GroqProvider:
    settings = get_settings()
    provider_name = str(settings.get("ai_provider") or "groq").lower()
    if provider_name != "groq":
        raise AIProviderError(f"Unsupported AI provider: {provider_name}")
    return GroqProvider()


def supports_response_format_json_object(model_name: str) -> bool:
    return not is_gpt_oss_model(model_name)


def is_gpt_oss_model(model_name: str) -> bool:
    return model_name.startswith("openai/gpt-oss")
