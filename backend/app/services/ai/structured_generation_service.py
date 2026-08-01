from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.ai.ai_provider import AIProviderError, AIRequest
from app.services.ai.ai_usage_service import record_generation
from app.services.ai.groq_provider import get_ai_provider
from app.services.ai.source_grounding_service import source_hash

ModelT = TypeVar("ModelT", bound=BaseModel)


def generate_structured(
    *,
    schema: type[ModelT],
    system_prompt: str,
    user_payload: dict[str, Any],
    generation_type: str,
    prompt_version: str,
    db: Session | None = None,
    user_id: int | None = None,
    course_id: int | None = None,
    chapter_id: int | None = None,
    student_id: int | None = None,
    fallback: ModelT | None = None,
    enabled: bool = True,
) -> tuple[ModelT | None, dict[str, Any]]:
    settings = get_settings()
    source_digest = source_hash(user_payload.get("sources"))
    if not enabled:
        return fallback, {"status": "deterministic_fallback", "provider": "none", "model_name": None, "source_hash": source_digest}

    provider = get_ai_provider()
    is_variant_generation = generation_type == "adaptive_course_variant"
    retries = max(
        0,
        int((settings.get("ai_variant_max_retries") if is_variant_generation else settings.get("ai_max_retries")) or 0),
    )
    last_error = ""
    for attempt in range(retries + 1):
        try:
            response = provider.generate_structured(
                AIRequest(
                    system_prompt=system_prompt,
                    user_prompt=json.dumps(user_payload, ensure_ascii=False),
                    response_schema=schema.model_json_schema(),
                    max_tokens=int(settings.get("ai_max_tokens") or 1200),
                    timeout_seconds=float(
                        (settings.get("ai_variant_timeout_seconds") if is_variant_generation else settings.get("ai_timeout_seconds"))
                        or 20
                    ),
                    model_name=settings.get("ai_variant_model") if is_variant_generation else settings.get("ai_model"),
                    metadata={"attempt": attempt + 1, "prompt_version": prompt_version},
                )
            )
            parsed = json.loads(response.text)
            model = schema.model_validate(parsed)
            usage = provider.get_usage_metadata(response) | response.usage
            record_generation(
                db,
                generation_type=generation_type,
                provider=response.provider,
                model_name=response.model_name,
                prompt_version=prompt_version,
                input_payload=user_payload,
                source_hash=source_digest,
                output_payload=model.model_dump(),
                status="ai_generated" if attempt == 0 else "ai_generated_with_repairs",
                user_id=user_id,
                course_id=course_id,
                chapter_id=chapter_id,
                student_id=student_id,
                usage=usage,
                metadata={"attempt": attempt + 1},
            )
            return model, {
                "status": "ai_generated" if attempt == 0 else "ai_generated_with_repairs",
                "provider": response.provider,
                "model_name": response.model_name,
                "source_hash": source_digest,
                "usage": usage,
            }
        except (AIProviderError, ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = str(exc)

    record_generation(
        db,
        generation_type=generation_type,
        provider="deterministic",
        model_name=None,
        prompt_version=prompt_version,
        input_payload=user_payload,
        source_hash=source_digest,
        output_payload=fallback.model_dump() if fallback else {},
        status="deterministic_fallback" if fallback else "failed",
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        student_id=student_id,
        error_message=last_error,
    )
    return fallback, {
        "status": "deterministic_fallback" if fallback else "failed",
        "provider": "deterministic",
        "model_name": None,
        "source_hash": source_digest,
        "error": last_error,
    }
