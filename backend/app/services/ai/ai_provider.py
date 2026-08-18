from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AIRequest:
    system_prompt: str
    user_prompt: str
    response_schema: dict[str, Any] | None = None
    temperature: float = 0.2
    max_tokens: int = 1200
    timeout_seconds: float = 20
    model_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIResponse:
    text: str
    provider: str
    model_name: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class AIProviderError(RuntimeError):
    pass


class AIProvider(Protocol):
    def generate_structured(self, request: AIRequest) -> AIResponse:
        ...

    def generate_text(self, request: AIRequest) -> AIResponse:
        ...

    def health_check(self) -> dict[str, Any]:
        ...

    def get_model_name(self) -> str:
        ...

    def get_usage_metadata(self, response: AIResponse) -> dict[str, Any]:
        ...
