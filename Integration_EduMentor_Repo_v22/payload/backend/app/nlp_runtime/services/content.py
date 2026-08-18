from __future__ import annotations

from typing import Any

from .registry import ModelRegistry


def _route_text(
    instruction: str,
    ui_section: str,
    context: str,
    pair_role: str,
    competence: str,
    language_skill: str,
    bloom_verb: str,
) -> str:
    return "\n".join([
        f"UI_SECTION={ui_section}",
        f"PAIR_ROLE={pair_role}",
        f"COMPETENCE={competence}",
        f"LANGUAGE_SKILL={language_skill}",
        f"BLOOM_VERB={bloom_verb}",
        f"INSTRUCTION={instruction}",
        f"CONTEXT={context}",
    ])


def predict_content_type(
    registry: ModelRegistry,
    *,
    text: str = "",
    instruction: str = "",
    ui_section: str = "",
    context: str = "",
    pair_role: str = "none",
    competence: str = "",
    language_skill: str = "",
    bloom_verb: str = "",
) -> dict[str, Any]:
    if instruction.strip() and ui_section.strip():
        model_input = _route_text(
            instruction=instruction,
            ui_section=ui_section,
            context=context,
            pair_role=pair_role,
            competence=competence,
            language_skill=language_skill,
            bloom_verb=bloom_verb,
        )
        content_type = str(
            registry.content_metadata_router.predict([model_input])[0]
        )
        return {
            "mode": "metadata_instruction_router",
            "content_type": content_type,
            "model_version": "v16",
            "requires_human_validation": True,
        }

    family = str(registry.content_family_model.predict([text])[0])
    subtype = registry.content_subtypes[family]
    if isinstance(subtype, str):
        content_type = subtype
    else:
        content_type = str(subtype.predict([text])[0])

    return {
        "mode": "text_only_hierarchical_fallback",
        "family": family,
        "content_type": content_type,
        "model_version": "v15",
        "requires_human_validation": True,
        "warning": (
            "Le texte seul est plus ambigu que l'instruction "
            "avec les métadonnées de la plateforme."
        ),
    }
