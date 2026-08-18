from __future__ import annotations

from typing import Any

from app.services.ai.duplicate_detection_service import token_similarity
from app.services.ai.source_grounding_service import validate_source_ids


def score_course_chapter(payload: dict[str, Any], allowed_source_ids: set[str] | None = None) -> dict[str, Any]:
    allowed_source_ids = allowed_source_ids or set()
    checks = {
        "has_introduction": bool(payload.get("introduction")),
        "has_explanations": len(payload.get("detailed_explanations") or []) >= 3,
        "has_examples": len(payload.get("worked_examples") or []) >= 2,
        "has_exercises": len(payload.get("guided_exercises") or []) + len(payload.get("independent_exercises") or []) >= 3,
        "has_solutions": bool(payload.get("solutions")),
        "has_summary": bool(payload.get("revision_summary")),
        "has_knowledge_check": bool(payload.get("knowledge_check")),
        "valid_source_ids": not validate_source_ids(payload, allowed_source_ids) if allowed_source_ids else True,
    }
    score = round(sum(1 for value in checks.values() if value) / len(checks), 2)
    status = "validated" if score >= 0.75 else "source_insufficient" if score < 0.45 else "needs_review"
    return {"quality_score": score, "validation_status": status, "checks": checks}


def level_variant_difference(variants: dict[str, dict[str, Any]]) -> dict[str, Any]:
    texts = {level: _flatten_text(content) for level, content in variants.items()}
    similarities = {}
    levels = list(texts)
    for index, left in enumerate(levels):
        for right in levels[index + 1:]:
            similarities[f"{left}:{right}"] = round(token_similarity(texts[left], texts[right]), 4)
    max_similarity = max(similarities.values(), default=0.0)
    return {
        "similarities": similarities,
        "max_similarity": max_similarity,
        "sufficiently_different": max_similarity < 0.82,
    }


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(child) for child in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(child) for child in value)
    return str(value or "")

