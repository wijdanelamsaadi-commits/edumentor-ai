from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.ai_generation import ExerciseItem, RemediationGeneration
from app.services.ai.prompt_templates import PROMPT_VERSIONS, remediation_prompt
from app.services.ai.structured_generation_service import generate_structured


def generate_remediation(
    db: Session | None,
    *,
    course_id: int,
    chapter_id: int | None,
    student_id: int,
    level: str,
    error_context: dict[str, Any],
    sources: list[dict[str, Any]],
) -> tuple[RemediationGeneration, dict[str, Any]]:
    fallback = deterministic_remediation(level, error_context, sources)
    model, metadata = generate_structured(
        schema=RemediationGeneration,
        system_prompt=remediation_prompt(),
        user_payload={"level": level, "error": error_context, "sources": sources},
        generation_type="remediation",
        prompt_version=PROMPT_VERSIONS["remediation_generation"],
        db=db,
        course_id=course_id,
        chapter_id=chapter_id,
        student_id=student_id,
        fallback=fallback,
        enabled=bool(get_settings().get("ai_remediation_enabled")),
    )
    return model or fallback, metadata


def deterministic_remediation(level: str, error_context: dict[str, Any], sources: list[dict[str, Any]]) -> RemediationGeneration:
    skill = str(error_context.get("skill") or error_context.get("chapter") or "la notion ciblée")
    selected = str(error_context.get("selected_answer") or "réponse incorrecte")
    correct = str(error_context.get("correct_answer") or "réponse attendue")
    return RemediationGeneration(
        identified_misconception=f"Confusion détectée autour de {skill}.",
        simple_explanation=f"La réponse '{selected}' ne correspond pas à l'objectif. Il faut revenir à l'indice qui justifie '{correct}'.",
        step_by_step_explanation=[
            "Relire la question.",
            "Repérer la compétence évaluée.",
            "Comparer chaque choix avec la source.",
            "Justifier la réponse retenue.",
        ],
        new_example=f"Nouvel exemple : expliquez {skill} avec un autre passage ou un autre contexte.",
        guided_exercise=ExerciseItem(prompt=f"Choisissez l'indice qui prouve {skill}.", expected_answer=correct),
        independent_exercise=ExerciseItem(prompt=f"Rédigez une justification courte sur {skill}.", expected_answer="Réponse argumentée et liée à la source."),
        solutions=[f"La réponse doit être reliée à la source et justifier pourquoi '{correct}' est attendu."],
        micro_summary=f"Pour progresser, il faut relier {skill} à un indice explicite.",
        follow_up_questions=[f"Quel indice permet de justifier {skill} ?", "Pourquoi l'autre réponse était-elle insuffisante ?"],
    )

