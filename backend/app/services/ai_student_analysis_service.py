from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.ai_generation import PedagogicalAnalysis
from app.services.ai.prompt_templates import PROMPT_VERSIONS, analysis_prompt
from app.services.ai.structured_generation_service import generate_structured


def generate_teacher_analysis(db: Session | None, *, user_id: int | None, facts: dict[str, Any]) -> tuple[PedagogicalAnalysis, dict[str, Any]]:
    fallback = deterministic_analysis(facts, audience="teacher")
    model, metadata = generate_structured(
        schema=PedagogicalAnalysis,
        system_prompt=analysis_prompt("professeur"),
        user_payload={"facts": facts},
        generation_type="teacher_analysis",
        prompt_version=PROMPT_VERSIONS["teacher_analysis"],
        db=db,
        user_id=user_id,
        fallback=fallback,
        enabled=bool(get_settings().get("ai_teacher_analysis_enabled")),
    )
    return model or fallback, metadata


def generate_parent_summary(db: Session | None, *, user_id: int | None, student_id: int | None, facts: dict[str, Any]) -> tuple[PedagogicalAnalysis, dict[str, Any]]:
    fallback = deterministic_analysis(facts, audience="parent")
    model, metadata = generate_structured(
        schema=PedagogicalAnalysis,
        system_prompt=analysis_prompt("parent"),
        user_payload={"facts": facts},
        generation_type="parent_summary",
        prompt_version=PROMPT_VERSIONS["parent_summary"],
        db=db,
        user_id=user_id,
        student_id=student_id,
        fallback=fallback,
        enabled=bool(get_settings().get("ai_parent_summary_enabled")),
    )
    return model or fallback, metadata


def deterministic_analysis(facts: dict[str, Any], audience: str) -> PedagogicalAnalysis:
    measured = [f"{key}: {value}" for key, value in facts.items() if value not in (None, "", [])][:6]
    if not measured:
        measured = ["Aucune donnée suffisante pour produire une analyse complète."]
    label = "simple" if audience == "parent" else "pédagogique"
    return PedagogicalAnalysis(
        measured_facts=measured,
        interpretation=[f"Analyse {label} basée uniquement sur les données disponibles."],
        recommendations=["Continuer le suivi avec les activités déjà disponibles."],
        priority_actions=["Consulter les compétences faibles avant de planifier une nouvelle évaluation."],
    )

