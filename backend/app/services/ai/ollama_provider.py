from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from app.services.ai.ai_provider import AIProviderError, AIRequest, AIResponse

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:1.7b"
LOGGER = logging.getLogger(__name__)


class OllamaProvider:
    provider_name = "ollama"

    def __init__(self, *, host: str = OLLAMA_HOST, model_name: str = OLLAMA_MODEL) -> None:
        self.host = host.rstrip("/")
        self.model_name = model_name

    def generate_structured(self, request: AIRequest) -> AIResponse:
        return self._generate(request, structured=True)

    def generate_text(self, request: AIRequest) -> AIResponse:
        return self._generate(request, structured=False)

    def health_check(self) -> dict[str, Any]:
        try:
            data = self._get("/api/version", timeout_seconds=5)
        except AIProviderError as exc:
            return {
                "provider": self.provider_name,
                "configured": False,
                "host": self.host,
                "model_name": self.get_model_name(),
                "error": str(exc),
            }
        return {
            "provider": self.provider_name,
            "configured": True,
            "host": self.host,
            "model_name": self.get_model_name(),
            "version": data.get("version"),
        }

    def get_model_name(self) -> str:
        return self.model_name

    def get_usage_metadata(self, response: AIResponse) -> dict[str, Any]:
        usage = response.usage or {}
        return {
            "tokens_input": usage.get("prompt_eval_count"),
            "tokens_output": usage.get("eval_count"),
            "prompt_eval_count": usage.get("prompt_eval_count"),
            "eval_count": usage.get("eval_count"),
            "load_duration": usage.get("load_duration"),
            "prompt_eval_duration": usage.get("prompt_eval_duration"),
            "eval_duration": usage.get("eval_duration"),
            "total_duration": usage.get("total_duration"),
            "duration_ms": usage.get("duration_ms"),
        }

    def _generate(self, request: AIRequest, *, structured: bool) -> AIResponse:
        payload: dict[str, Any] = {
            "model": request.model_name or self.get_model_name(),
            "prompt": "\n\n".join([request.system_prompt, request.user_prompt]).strip(),
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": request.max_tokens,
            },
        }
        if structured:
            payload["format"] = request.response_schema or "json"

        started = time.perf_counter()
        data = self._post("/api/generate", payload, timeout_seconds=request.timeout_seconds)
        duration_ms = round((time.perf_counter() - started) * 1000)
        text = self._extract_response_text("/api/generate", data)
        if structured:
            text = self._validate_structured_text(text, data)

        usage = {
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
            "load_duration": data.get("load_duration"),
            "prompt_eval_duration": data.get("prompt_eval_duration"),
            "eval_duration": data.get("eval_duration"),
            "total_duration": data.get("total_duration"),
            "duration_ms": duration_ms,
        }
        return AIResponse(
            text=text,
            provider=self.provider_name,
            model_name=str(data.get("model") or payload["model"]),
            usage=usage,
            raw={
                "done": data.get("done"),
                "done_reason": data.get("done_reason"),
                "raw_response_length": len(text),
                "host": self.host,
            },
        )

    def _extract_response_text(self, path: str, data: dict[str, Any]) -> str:
        if path == "/api/chat":
            message = data.get("message") if isinstance(data.get("message"), dict) else {}
            return str(message.get("content") or "").strip()
        return str(data.get("response") or "").strip()

    def _validate_structured_text(self, text: str, data: dict[str, Any]) -> str:
        try:
            json.loads(text)
            self._log_structured_response(data, text)
            return text
        except json.JSONDecodeError as first_error:
            cleaned = self._strip_json_fences(text)
            if cleaned != text:
                try:
                    json.loads(cleaned)
                    self._log_structured_response(data, cleaned, json_error=first_error)
                    return cleaned
                except json.JSONDecodeError as second_error:
                    self._log_structured_response(data, text, json_error=second_error)
                    raise AIProviderError(f"Ollama returned invalid JSON: {second_error}") from second_error
            self._log_structured_response(data, text, json_error=first_error)
            raise AIProviderError(f"Ollama returned invalid JSON: {first_error}") from first_error

    def _strip_json_fences(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.removeprefix("```json").strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned.removesuffix("```").strip()
        return cleaned

    def _log_structured_response(
        self,
        data: dict[str, Any],
        text: str,
        *,
        json_error: json.JSONDecodeError | None = None,
    ) -> None:
        LOGGER.info(
            "ollama_structured_response",
            extra={
                "raw_response_length": len(text),
                "done_reason": data.get("done_reason"),
                "eval_count": data.get("eval_count"),
                "json_error": str(json_error) if json_error else "",
                "raw_response_start": text[:300],
                "raw_response_end": text[-300:],
            },
        )

    def _get(self, path: str, *, timeout_seconds: float) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{self.host}{path}", timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (ConnectionRefusedError, urllib.error.URLError) as exc:
            raise AIProviderError("Ollama is unavailable on localhost:11434") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AIProviderError("Ollama request timed out") from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError("Ollama health response is invalid JSON") from exc

    def _post(self, path: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "EduMentorAI-OllamaPreview/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:600]
            except Exception:
                detail = ""
            lowered = detail.lower()
            if exc.code == 404 or "not found" in lowered or "pull model" in lowered:
                raise AIProviderError(f"Ollama model is unavailable: {payload.get('model')}") from exc
            if "memory" in lowered or "out of memory" in lowered or "insufficient" in lowered:
                raise AIProviderError("Ollama failed because memory is insufficient") from exc
            raise AIProviderError(f"Ollama request failed: HTTP {exc.code} {detail}") from exc
        except (ConnectionRefusedError, urllib.error.URLError) as exc:
            raise AIProviderError("Ollama is unavailable on localhost:11434") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AIProviderError("Ollama request timed out") from exc
        except json.JSONDecodeError as exc:
            raise AIProviderError("Ollama response envelope is invalid JSON") from exc
