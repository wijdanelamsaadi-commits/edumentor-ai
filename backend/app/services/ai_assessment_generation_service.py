from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.ai_generation import GeneratedQuestion
from app.services.ai.duplicate_detection_service import is_duplicate, max_similarity
from app.services.ai.prompt_templates import PROMPT_VERSIONS, assessment_prompt
from app.services.ai.structured_generation_service import generate_structured


def generate_question(
    db: Session | None,
    *,
    course_id: int,
    chapter_id: int | None,
    skill: str | None,
    level: str,
    difficulty: str,
    sources: list[dict[str, Any]],
    existing_questions: list[str],
    fallback: GeneratedQuestion,
    user_id: int | None = None,
) -> tuple[GeneratedQuestion, dict[str, Any]]:
    settings = get_settings()
    model, metadata = generate_structured(
        schema=GeneratedQuestion,
        system_prompt=assessment_prompt(),
        user_payload={
            "course_id": course_id,
            "chapter_id": chapter_id,
            "skill": skill,
            "level": level,
            "difficulty": difficulty,
            "sources": sources,
            "existing_questions": existing_questions[:20],
        },
        generation_type="assessment_question",
        prompt_version=PROMPT_VERSIONS["assessment_generation"],
        db=db,
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        fallback=fallback,
        enabled=bool(settings.get("ai_assessment_generation_enabled")),
    )
    model = model or fallback
    threshold = float(settings.get("ai_duplicate_threshold") or 0.82)
    similarity = max_similarity(model.question_text, existing_questions)
    if is_duplicate(model.question_text, existing_questions, threshold):
        model = fallback
        metadata["status"] = "deterministic_fallback"
        metadata["fallback_reason"] = "duplicate_question_rejected"
    metadata["similarity_score"] = similarity
    if model.correct_answer not in model.choices:
        model = fallback
        metadata["status"] = "deterministic_fallback"
        metadata["fallback_reason"] = "correct_answer_not_in_choices"
    return model, metadata

