from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.persistence import AIGenerationRecord


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def record_generation(
    db: Session | None,
    *,
    generation_type: str,
    provider: str,
    model_name: str | None,
    prompt_version: str | None,
    input_payload: Any,
    source_hash: str | None,
    output_payload: Any,
    status: str,
    user_id: int | None = None,
    course_id: int | None = None,
    chapter_id: int | None = None,
    student_id: int | None = None,
    quality_score: float | None = None,
    error_message: str | None = None,
    usage: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AIGenerationRecord | None:
    if db is None:
        return None
    usage = usage or {}
    record = AIGenerationRecord(
        generation_type=generation_type,
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        student_id=student_id,
        provider=provider,
        model_name=model_name,
        prompt_version=prompt_version,
        input_hash=stable_hash(input_payload),
        source_hash=source_hash,
        output_hash=stable_hash(output_payload),
        status=status,
        quality_score=quality_score,
        error_message=(error_message or "")[:1000] or None,
        tokens_input=usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("tokens_input"),
        tokens_output=usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("tokens_output"),
        duration_ms=usage.get("duration_ms"),
        metadata_json=metadata or {},
    )
    db.add(record)
    db.flush()
    return record

