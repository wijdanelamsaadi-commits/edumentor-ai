from __future__ import annotations

from typing import Any

from .content import predict_content_type
from .figures_exam import analyze_figure, classify_exam_competence
from .level import predict_level
from .registry import ModelRegistry


def analyze_all(
    registry: ModelRegistry,
    *,
    text: str,
    instruction: str = "",
    ui_section: str = "",
    context: str = "",
    pair_role: str = "none",
    competence: str = "",
    language_skill: str = "",
    bloom_verb: str = "",
    treat_as_exam_question: bool = False,
) -> dict[str, Any]:
    content = predict_content_type(
        registry,
        text=text,
        instruction=instruction,
        ui_section=ui_section,
        context=context,
        pair_role=pair_role,
        competence=competence,
        language_skill=language_skill,
        bloom_verb=bloom_verb,
    )

    result: dict[str, Any] = {
        "level": predict_level(registry, text),
        "content_type": content,
        "figure": analyze_figure(registry, text),
    }

    if treat_as_exam_question:
        result["exam_competence"] = classify_exam_competence(
            registry,
            instruction or text,
        )
    else:
        result["exam_competence"] = None

    return result
