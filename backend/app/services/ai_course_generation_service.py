from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from typing import Any
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.ai_generation import AdaptiveChapterVariant, AdaptiveChapterVariantContent, AdaptiveChapterVariantSet, AdaptiveLessonBlock, GeneratedChapterContent
from app.services.ai.ai_provider import AIProviderError, AIRequest
from app.services.ai.ai_usage_service import record_generation
from app.services.ai.groq_provider import get_ai_provider
from app.services.ai.prompt_templates import (
    PROMPT_VERSIONS,
    adaptive_course_variant_level_prompt,
    adaptive_course_variant_main_prompt,
    adaptive_course_variant_prompt,
    adaptive_course_variant_set_prompt,
    adaptive_course_variant_support_prompt,
    course_chapter_prompt,
)
from app.services.ai.quality_validation_service import score_course_chapter
from app.services.ai.source_grounding_service import source_hash, truncate_sources, validate_source_ids
from app.services.ai.structured_generation_service import generate_structured

LEVELS = ("debutant", "intermediaire", "avance")
ADAPTIVE_LENGTH_RULES = {
    "debutant": {
        "summary": (80, 120),
        "explanation": (140, 200),
        "key_points": (4, 6),
        "vocabulary": (4, 6),
        "guided_example": (100, 150),
        "learning_support": (80, 120),
    },
    "intermediaire": {
        "summary": (110, 160),
        "explanation": (200, 280),
        "key_points": (5, 7),
        "vocabulary": (5, 8),
        "guided_example": (140, 200),
        "learning_support": (100, 150),
    },
    "avance": {
        "summary": (140, 200),
        "explanation": (280, 400),
        "key_points": (6, 9),
        "vocabulary": (6, 10),
        "guided_example": (180, 260),
        "learning_support": (120, 180),
    },
}
ADAPTIVE_SIMILARITY_THRESHOLD = 0.72
GENERIC_ADAPTIVE_TEXTS = {
    "aide",
    "exemple",
    "resume adapte",
    "résumé adapté",
    "explication adaptee",
    "explication adaptée",
    "point cle",
    "point clé",
    "reponse attendue",
    "réponse attendue",
}
COMPACT_SOURCE_PRIORITIES = {
    "summary": 1,
    "resume": 1,
    "key_points": 2,
    "repere": 2,
    "analysis": 3,
    "analyse": 3,
    "paragraph": 3,
    "sequence": 4,
    "methodology": 5,
    "methode": 5,
    "exercise": 6,
    "correction": 6,
    "solution": 6,
}
_variant_rate_lock = threading.Lock()
_last_variant_request_at = 0.0


class VariantProviderExecutionError(AIProviderError):
    def __init__(self, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.metadata = metadata or {}


class AdaptiveVariantQualityError(ValueError):
    def __init__(self, message: str, invalid_levels: set[str] | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.invalid_levels = invalid_levels or set()
        self.payload = payload


def generate_adaptive_chapter_variant(
    db: Session | None,
    *,
    course_id: int | None,
    chapter_id: int | None,
    chapter_source_id: str,
    chapter_title: str,
    level: str,
    subject: str,
    sources: list[dict[str, Any]],
    user_id: int | None = None,
) -> tuple[AdaptiveChapterVariant, dict[str, Any]]:
    settings = get_settings()
    selected_sources = truncate_sources(sources, int(settings.get("ai_max_source_chars") or 6000))
    allowed_ids = {
        str(source.get("id") or source.get("source_block_id") or index)
        for index, source in enumerate(selected_sources, start=1)
    }
    fallback = deterministic_adaptive_chapter_variant(
        chapter_source_id=chapter_source_id,
        chapter_title=chapter_title,
        level=level,
        sources=selected_sources,
        model_name=None,
    )
    model, metadata = generate_structured(
        schema=AdaptiveChapterVariant,
        system_prompt=adaptive_course_variant_prompt(level, subject),
        user_payload={
            "chapter_source_id": chapter_source_id,
            "chapter_title": chapter_title,
            "level": level,
            "sources": selected_sources,
            "schema_hint": "AdaptiveChapterVariant",
        },
        generation_type="adaptive_course_variant",
        prompt_version=PROMPT_VERSIONS["adaptive_course_variant"],
        db=db,
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        fallback=fallback,
        enabled=bool(settings.get("ai_content_generation_enabled")),
    )
    model = model or fallback
    status = metadata.get("status")
    if status not in {"ai_generated", "ai_generated_with_repairs"}:
        model.generation_method = "deterministic_fallback"
        model.model = None
    else:
        model.generation_method = "ai_generated"
        model.model = metadata.get("model_name") or settings.get("ai_variant_model") or settings.get("ai_model")
    model.level = level
    model.chapter_source_id = chapter_source_id
    model.source_block_ids = [item for item in model.source_block_ids if item in allowed_ids] or list(allowed_ids)[:5]
    if not model.blocks:
        model.blocks = build_adaptive_lesson_blocks(model, selected_sources, metadata.get("source_hash"))
    else:
        model.blocks = enrich_adaptive_lesson_blocks(model.blocks, level, chapter_source_id, metadata.get("source_hash"), model.generation_method)
    unknown_sources = validate_source_ids({"source_ids": model.source_block_ids}, allowed_ids) if allowed_ids else []
    metadata.update({"unknown_source_ids": unknown_sources})
    if unknown_sources:
        model.generation_method = "deterministic_fallback"
    return model, metadata


def deterministic_adaptive_chapter_variant(
    *,
    chapter_source_id: str,
    chapter_title: str,
    level: str,
    sources: list[dict[str, Any]],
    model_name: str | None = None,
) -> AdaptiveChapterVariant:
    source_text = first_source_text(sources) or "Le professeur n'a pas fourni assez de contenu exploitable pour ce chapitre."
    source_id = str((sources[0].get("id") or sources[0].get("source_block_id")) if sources else f"{chapter_source_id}_source")
    generated_at = datetime.utcnow().isoformat()
    profile = {
        "debutant": {
            "summary": "Ce chapitre presente l'idee principale avec des mots simples.",
            "support": ["Relire les phrases sources une par une.", "Relever les mots importants.", "Reformuler avec ses propres mots."],
            "question": "Quelle idee principale faut-il retenir dans ce chapitre ?",
            "answer": "Il faut reprendre l'idee presente dans la source sans ajouter d'information.",
            "explanation": "On avance doucement. D'abord, on repere qui agit, ce qui se passe, puis pourquoi c'est important.",
            "method": "1. Lis la source. 2. Souligne les mots faciles a comprendre. 3. Classe les evenements dans l'ordre.",
            "correction": "Etape 1: reprendre une information visible. Etape 2: expliquer avec une phrase simple. Etape 3: verifier que rien n'est invente.",
        },
        "intermediaire": {
            "summary": "Ce chapitre organise les informations du professeur pour comprendre les liens importants.",
            "support": ["Identifier l'information principale.", "Justifier avec un indice du cours.", "Relier l'idee au theme du chapitre."],
            "question": "Comment justifier l'idee principale du chapitre avec les elements fournis ?",
            "answer": "La justification doit citer un element du cours puis expliquer son role.",
            "explanation": "On relie les informations: personnages, evenements, themes et consequences. La reponse doit etre organisee et justifiee.",
            "method": "Formule une idee, appuie-la sur un indice du cours, puis explique le lien avec le theme du chapitre.",
            "correction": "Une bonne reponse identifie l'idee, cite un indice et ajoute une justification courte mais claire.",
        },
        "avance": {
            "summary": "Ce chapitre sert de base a une analyse argumentee fondee uniquement sur les sources.",
            "support": ["Distinguer explicite et implicite.", "Construire une interpretation prudente.", "Limiter la reponse aux faits fournis."],
            "question": "Quelle analyse nuancee peut-on construire sans depasser les sources ?",
            "answer": "Une analyse valable relie plusieurs indices du cours et signale ses limites.",
            "explanation": "On construit une interpretation exigeante: procede, effet, enjeu litteraire et limite de l'analyse doivent rester lies aux sources.",
            "method": "Construis une reponse de type regional: these, justification, effet produit, nuance et retour a la source.",
            "correction": "La correction attend une argumentation synthetique, precise et limitee aux informations disponibles.",
        },
    }.get(level, {})
    variant = AdaptiveChapterVariant(
        level=level,
        chapter_source_id=chapter_source_id,
        title=chapter_title,
        summary=profile.get("summary", "Synthese adaptee du chapitre."),
        explanation=f"{profile.get('explanation', 'Ce chapitre reprend les elements fournis.')} Source principale: {source_text}",
        key_points=[source_text[:180], "Toute reponse doit rester verifiable dans le contenu du professeur."],
        vocabulary=[{"term": chapter_title, "definition": source_text[:240]}],
        guided_example={"title": f"Exemple guide - {chapter_title}", "content": f"{profile.get('method', 'On part de la source, puis on reformule.')} Exemple source: {source_text[:300]}"},
        learning_support=profile.get("support", []),
        practice_question={
            "question": profile.get("question", f"Que faut-il retenir de {chapter_title} ?"),
            "expected_answer": profile.get("answer", "Une reponse courte fondee sur la source."),
            "explanation": profile.get("correction", "La reponse est acceptee si elle utilise uniquement les informations du chapitre."),
        },
        source_block_ids=[source_id],
        generation_method="deterministic_fallback",
        model=model_name,
        generated_at=generated_at,
    )
    variant.blocks = build_adaptive_lesson_blocks(variant, sources, None)
    return variant


def build_adaptive_lesson_blocks(variant: AdaptiveChapterVariant, sources: list[dict[str, Any]], source_digest: str | None) -> list[AdaptiveLessonBlock]:
    primary_source = sources[0] if sources else {}
    source_id = str(primary_source.get("id") or primary_source.get("source_block_id") or variant.chapter_source_id)
    source_hash = source_digest or str(primary_source.get("source_hash") or "")
    original_type = str(primary_source.get("original_block_type") or primary_source.get("type") or "paragraph")
    base = {
        "source_block_id": source_id,
        "source_chapter_id": variant.chapter_source_id,
        "source_hash": source_hash,
        "original_block_type": original_type,
        "level": variant.level,
        "generation_method": variant.generation_method,
    }
    vocabulary = [f"{item.term}: {item.definition}" for item in variant.vocabulary]
    blocks: list[dict[str, Any]] = [
        block_payload(base, "heading", "Titre du chapitre", variant.title, "resume", "heading"),
        block_payload(base, "summary", "Résumé adapté", variant.summary, "resume", "summary"),
        block_payload(base, "paragraph", "Explication détaillée", variant.explanation, "resume", "explanation"),
        block_payload(base, "definition", "Vocabulaire et notions", "\n".join(vocabulary), "resume", "vocabulary"),
        block_payload(base, "example", variant.guided_example.title, variant.guided_example.content, "sequences", "guided-example"),
        block_payload(base, "methodology", "Aide à l'apprentissage", "\n".join(variant.learning_support), "sequences", "support"),
        block_payload(base, "visual", "Schéma pédagogique", pedagogical_schema_text(variant), "schemas", "schema"),
        block_payload(base, "exercise", "Question d'entraînement", variant.practice_question.question, "training_exams", "practice"),
        block_payload(
            base,
            "correction",
            "Correction pédagogique",
            f"{variant.practice_question.expected_answer}\n\n{variant.practice_question.explanation}",
            "corrections",
            "practice-correction",
        ),
        block_payload(base, "key_points", "Points clés", variant.key_points, "takeaways", "key-points"),
        block_payload(base, "mini_assessment", "Question pratique finale", {
            "question": variant.practice_question.question,
            "answer": variant.practice_question.expected_answer,
            "explanation": variant.practice_question.explanation,
        }, "training_exams", "mini-assessment"),
    ]
    blocks.extend(official_passthrough_blocks(variant, sources, source_digest))
    return [AdaptiveLessonBlock.model_validate(block) for block in blocks if block.get("content") or block.get("title")]


def block_payload(base: dict[str, Any], block_type: str, title: str, content: Any, section: str, suffix: str) -> dict[str, Any]:
    return {
        **base,
        "id": f"{base['source_chapter_id']}-{base['level']}-{suffix}",
        "type": block_type,
        "title": title,
        "content": content,
        "section": section,
    }


def pedagogical_schema_text(variant: AdaptiveChapterVariant) -> str:
    if variant.level == "debutant":
        return "Schema simple: Situation de depart -> evenement important -> idee a retenir -> reponse courte."
    if variant.level == "avance":
        return "Schema d'analyse: indice source -> procede ou relation -> effet produit -> interpretation argumentee -> limite."
    return "Schema structure: information principale -> indice du cours -> lien avec le theme -> justification."


def official_passthrough_blocks(variant: AdaptiveChapterVariant, sources: list[dict[str, Any]], source_digest: str | None) -> list[dict[str, Any]]:
    blocks = []
    for index, source in enumerate(sources, start=1):
        if not is_official_source(source):
            continue
        source_id = str(source.get("id") or source.get("source_block_id") or f"{variant.chapter_source_id}_official_{index}")
        blocks.append({
            "id": f"{variant.chapter_source_id}-{variant.level}-official-{index}",
            "type": source.get("type") or "paragraph",
            "title": source.get("title") or "Document officiel",
            "content": source.get("text") or source.get("content") or "",
            "section": source.get("section") or "regional_exams",
            "source_block_id": source_id,
            "source_chapter_id": variant.chapter_source_id,
            "source_hash": source_digest or source.get("source_hash") or "",
            "original_block_type": source.get("original_block_type") or source.get("type"),
            "level": variant.level,
            "generation_method": "official_source",
        })
    return blocks


def is_official_source(source: dict[str, Any]) -> bool:
    text = f"{source.get('section', '')} {source.get('type', '')} {source.get('title', '')} {source.get('metadata', '')}".lower()
    return any(marker in text for marker in ("regional", "official", "session", "academie", "examen"))


def enrich_adaptive_lesson_blocks(blocks: list[Any], level: str, chapter_source_id: str, source_hash: str | None, generation_method: str) -> list[Any]:
    enriched = []
    for index, block in enumerate(blocks, start=1):
        if hasattr(block, "model_dump"):
            block = block.model_dump()
        if not isinstance(block, dict):
            continue
        enriched.append(AdaptiveLessonBlock.model_validate({
            **block,
            "id": block.get("id") or f"{chapter_source_id}-{level}-ai-{index}",
            "source_chapter_id": block.get("source_chapter_id") or chapter_source_id,
            "source_hash": block.get("source_hash") or source_hash or "",
            "original_block_type": block.get("original_block_type") or block.get("type") or "paragraph",
            "level": level,
            "generation_method": block.get("generation_method") or generation_method,
        }))
    return enriched


def build_variant_from_content(
    *,
    content: AdaptiveChapterVariantContent,
    level: str,
    chapter_source_id: str,
    chapter_title: str,
    source_block_ids: list[str],
    source_digest: str,
    model_name: str | None,
) -> AdaptiveChapterVariant:
    key_points = [
        f"{item.title}: {item.content}".strip(": ")
        for item in content.key_points
    ]
    learning_support = content.learning_support.as_text_items()
    variant = AdaptiveChapterVariant(
        level=level,
        chapter_source_id=chapter_source_id,
        title=chapter_title,
        summary=content.summary,
        explanation=content.explanation,
        key_points=key_points,
        vocabulary=content.vocabulary,
        guided_example=content.guided_example,
        learning_support=learning_support,
        practice_question=content.practice_question,
        source_block_ids=source_block_ids,
        generation_method="ai_generated",
        model=model_name,
        generated_at=datetime.utcnow().isoformat(),
    )
    if content.blocks:
        variant.blocks = enrich_adaptive_lesson_blocks(content.blocks, level, chapter_source_id, source_digest, "ai_generated")
    else:
        variant.blocks = build_adaptive_lesson_blocks(variant, [], source_digest)
    return variant


def generate_single_level_adaptive_variant(
    db: Session | None,
    *,
    user_payload: dict[str, Any],
    subject: str,
    level: str,
    course_id: int | None,
    chapter_id: int | None,
    user_id: int | None,
    source_digest: str,
    source_block_ids: list[str],
    max_output_tokens: int,
    retry_reason: str | None = None,
    previous_error: str | None = None,
) -> tuple[AdaptiveChapterVariant, dict[str, Any]]:
    settings = get_settings()
    provider = get_ai_provider()
    level_payload = {
        **user_payload,
        "level": level,
        "strict_word_targets": variant_word_targets(level),
        "validation_feedback": previous_error,
        "server_injected_fields": [
            "chapter_source_id",
            "level",
            "title",
            "generation_method",
            "model",
            "generated_at",
            "source_block_ids",
        ],
    }
    parsed, response, call_metadata = request_split_level_adaptive_content(
        provider,
        level_payload=level_payload,
        subject=subject,
        level=level,
        settings=settings,
        max_output_tokens=max_output_tokens,
        retry_reason=retry_reason,
    )
    parsed = normalize_adaptive_content_payload(parsed)
    content = AdaptiveChapterVariantContent.model_validate(parsed)
    variant = build_variant_from_content(
        content=content,
        level=level,
        chapter_source_id=str(user_payload.get("chapter_source_id") or ""),
        chapter_title=str(user_payload.get("chapter_title") or ""),
        source_block_ids=source_block_ids,
        source_digest=source_digest,
        model_name=response.model_name,
    )
    level_errors = validate_adaptive_variant_quality(variant)
    if level_errors:
        raise AdaptiveVariantQualityError("; ".join(level_errors), {level}, payload=variant.model_dump(mode="json"))
    usage = provider.get_usage_metadata(response) | response.usage
    metadata = {
        "status": "ai_generated",
        "provider": response.provider,
        "model_name": response.model_name,
        "source_hash": source_digest,
        "usage": usage,
        "retry_reason": retry_reason,
        "validation_status": "validated_after_repair" if retry_reason or call_metadata.get("repair_attempted") else "validated",
        "repair_attempted": bool(retry_reason or call_metadata.get("repair_attempted")),
        "generation_method": "ai_generated",
        "rate_limit_retry_count": call_metadata["rate_limit_retry_count"],
        "retry_after_seconds": call_metadata["retry_after_seconds"],
        "attempts": call_metadata["attempts"],
        "final_http_status": call_metadata["final_http_status"],
        "part_http_statuses": call_metadata.get("part_http_statuses"),
        "finish_reason": usage.get("finish_reason") or usage.get("completion_reason"),
        "error": None,
        "generated_at": variant.generated_at,
    }
    record_generation(
        db,
        generation_type="adaptive_course_variant_level",
        provider=response.provider,
        model_name=response.model_name,
        prompt_version=PROMPT_VERSIONS["adaptive_course_variant"],
        input_payload={"chapter_source_id": user_payload.get("chapter_source_id"), "level": level, "source_count": len(user_payload.get("sources") or [])},
        source_hash=source_digest,
        output_payload={"chapter_source_id": variant.chapter_source_id, "level": level},
        status=metadata["validation_status"],
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        usage=usage,
        metadata=metadata,
    )
    return variant, metadata


def request_split_level_adaptive_content(
    provider,
    *,
    level_payload: dict[str, Any],
    subject: str,
    level: str,
    settings: dict,
    max_output_tokens: int,
    retry_reason: str | None,
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    model_name = settings.get("ai_variant_model") or settings.get("ai_model")
    timeout_seconds = float(settings.get("ai_variant_timeout_seconds") or 20)
    main_max_tokens = min(int(max_output_tokens), 1400)
    support_max_tokens = min(int(max_output_tokens), 1400)
    main_payload = {
        "phase": "main_content",
        "chapter_source_id": level_payload.get("chapter_source_id"),
        "chapter_title": level_payload.get("chapter_title"),
        "level": level,
        "sources": level_payload.get("sources") or [],
        "strict_word_targets": level_payload.get("strict_word_targets") or {},
        "validation_feedback": level_payload.get("validation_feedback"),
        "required_fields": ["summary", "explanation", "key_points", "vocabulary"],
    }
    main_response, main_metadata = execute_variant_provider_call(
        provider,
        AIRequest(
            system_prompt=adaptive_course_variant_main_prompt(subject, level),
            user_prompt=json.dumps(main_payload, ensure_ascii=False),
            response_schema=None,
            temperature=0.0,
            max_tokens=max(700, main_max_tokens),
            timeout_seconds=timeout_seconds,
            model_name=model_name,
            metadata={
                "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
                "retry_reason": retry_reason,
                "level": level,
                "phase": "main_content",
            },
        ),
        settings=settings,
    )
    try:
        main_content = load_json_object_response(main_response.text)
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(f"main_content JSON invalid: {exc.msg}", exc.doc, exc.pos) from exc
    main_errors = validate_main_content_payload(main_content, level)
    if main_errors:
        main_metadata["repair_attempted"] = True
        repair_payload = {
            **main_payload,
            "validation_feedback": "; ".join(main_errors),
            "previous_invalid_payload": {
                "summary": main_content.get("summary"),
                "explanation": main_content.get("explanation"),
                "key_points": main_content.get("key_points"),
                "vocabulary": main_content.get("vocabulary"),
            },
            "repair_instruction": "Return the complete main_content JSON again. Keep source facts, but expand fields named in validation_feedback until they pass backend word counts.",
        }
        repaired_response, repaired_metadata = execute_variant_provider_call(
            provider,
            AIRequest(
                system_prompt=adaptive_course_variant_main_prompt(subject, level),
                user_prompt=json.dumps(repair_payload, ensure_ascii=False),
                response_schema=None,
                temperature=0.0,
                max_tokens=max(700, main_max_tokens),
                timeout_seconds=timeout_seconds,
                model_name=model_name,
                metadata={
                    "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
                    "retry_reason": "main_content_validation_repair",
                    "level": level,
                    "phase": "main_content_repair",
                },
            ),
            settings=settings,
        )
        try:
            repaired_content = load_json_object_response(repaired_response.text)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(f"main_content_repair JSON invalid: {exc.msg}", exc.doc, exc.pos) from exc
        repaired_content = merge_main_repair_content(main_content, repaired_content, level)
        repaired_errors = validate_main_content_payload(repaired_content, level)
        if repaired_errors:
            raise ValueError("; ".join(repaired_errors))
        main_content = repaired_content
        main_response = repaired_response
        main_metadata = merge_provider_call_metadata(main_metadata, repaired_metadata)
    support_payload = {
        "phase": "pedagogical_support",
        "chapter_source_id": level_payload.get("chapter_source_id"),
        "chapter_title": level_payload.get("chapter_title"),
        "level": level,
        "sources": level_payload.get("sources") or [],
        "main_content": {
            "summary": clip_text_to_budget(str(main_content.get("summary") or ""), 700),
            "explanation": clip_text_to_budget(str(main_content.get("explanation") or ""), 900),
            "key_points": main_content.get("key_points"),
            "vocabulary": main_content.get("vocabulary"),
        },
        "strict_word_targets": level_payload.get("strict_word_targets") or {},
        "validation_feedback": level_payload.get("validation_feedback"),
        "required_fields": ["guided_example", "learning_support", "practice_question", "blocks"],
    }
    support_response, support_metadata = execute_variant_provider_call(
        provider,
        AIRequest(
            system_prompt=adaptive_course_variant_support_prompt(subject, level),
            user_prompt=json.dumps(support_payload, ensure_ascii=False),
            response_schema=None,
            temperature=0.0,
            max_tokens=max(700, support_max_tokens),
            timeout_seconds=timeout_seconds,
            model_name=model_name,
            metadata={
                "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
                "retry_reason": retry_reason,
                "level": level,
                "phase": "pedagogical_support",
            },
        ),
        settings=settings,
    )
    try:
        support_content = load_json_object_response(support_response.text)
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(f"pedagogical_support JSON invalid: {exc.msg}", exc.doc, exc.pos) from exc
    support_content = unwrap_support_content_payload(support_content)
    support_errors = validate_support_content_payload(support_content, level)
    if support_errors:
        support_metadata["repair_attempted"] = True
        support_repair_payload = {
            **support_payload,
            "validation_feedback": "; ".join(support_errors),
            "previous_invalid_payload": support_content,
            "repair_instruction": "Return the complete pedagogical_support JSON again. Keep valid fields, expand only fields named in validation_feedback, and preserve the exact schema.",
        }
        repaired_support_response, repaired_support_metadata = execute_variant_provider_call(
            provider,
            AIRequest(
                system_prompt=adaptive_course_variant_support_prompt(subject, level),
                user_prompt=json.dumps(support_repair_payload, ensure_ascii=False),
                response_schema=None,
                temperature=0.0,
                max_tokens=max(700, support_max_tokens),
                timeout_seconds=timeout_seconds,
                model_name=model_name,
                metadata={
                    "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
                    "retry_reason": "pedagogical_support_validation_repair",
                    "level": level,
                    "phase": "pedagogical_support_repair",
                },
            ),
            settings=settings,
        )
        try:
            repaired_support_content = load_json_object_response(repaired_support_response.text)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(f"pedagogical_support_repair JSON invalid: {exc.msg}", exc.doc, exc.pos) from exc
        support_content = merge_support_repair_content(
            support_content,
            unwrap_support_content_payload(repaired_support_content),
            level,
        )
        repaired_support_errors = validate_support_content_payload(support_content, level)
        if repaired_support_errors:
            raise ValueError("; ".join(repaired_support_errors))
        support_response = repaired_support_response
        support_metadata = merge_provider_call_metadata(support_metadata, repaired_support_metadata)
    merged = {
        "summary": main_content.get("summary"),
        "explanation": main_content.get("explanation"),
        "key_points": main_content.get("key_points") or [],
        "vocabulary": main_content.get("vocabulary") or [],
        "guided_example": support_content.get("guided_example"),
        "learning_support": support_content.get("learning_support"),
        "practice_question": support_content.get("practice_question"),
        "blocks": support_content.get("blocks") or [],
    }
    support_response.usage = merge_usage_metadata(main_response.usage, support_response.usage)
    metadata = merge_provider_call_metadata(main_metadata, support_metadata)
    metadata["repair_attempted"] = bool(main_metadata.get("repair_attempted") or support_metadata.get("repair_attempted"))
    metadata["part_http_statuses"] = {
        "main_content": main_metadata.get("final_http_status"),
        "pedagogical_support": support_metadata.get("final_http_status"),
    }
    return merged, support_response, metadata


def unwrap_support_content_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if any(key in payload for key in ("guided_example", "learning_support", "practice_question")):
        return payload
    for key in ("pedagogical_support", "support", "accompagnement", "accompagnement_pedagogique", "content"):
        value = payload.get(key)
        if isinstance(value, dict) and any(field in value for field in ("guided_example", "learning_support", "practice_question")):
            return value
    return payload


def merge_support_repair_content(previous: dict[str, Any], repaired: dict[str, Any], level: str) -> dict[str, Any]:
    merged = dict(previous)
    for key in ("guided_example", "learning_support", "practice_question", "blocks"):
        value = repaired.get(key)
        if value not in (None, "", []):
            merged[key] = value
    return merged


def validate_support_content_payload(payload: dict[str, Any], level: str) -> list[str]:
    normalized = normalize_adaptive_content_payload({
        "summary": "placeholder text " * 120,
        "explanation": "placeholder text " * 220,
        "key_points": [{"title": f"Point {index}", "content": "contenu explicatif suffisant"} for index in range(1, 7)],
        "vocabulary": [{"term": f"Terme {index}", "definition": "definition contextuelle suffisante"} for index in range(1, 7)],
        "guided_example": payload.get("guided_example"),
        "learning_support": payload.get("learning_support"),
        "practice_question": payload.get("practice_question"),
        "blocks": payload.get("blocks") or [],
    })
    try:
        content = AdaptiveChapterVariantContent.model_validate(normalized)
    except ValidationError as exc:
        return [compact_validation_error(exc)]
    temp_variant = build_variant_from_content(
        content=content,
        level=level,
        chapter_source_id="chapter_test",
        chapter_title="Chapitre test",
        source_block_ids=["source_test"],
        source_digest="",
        model_name=None,
    )
    return [
        error for error in validate_adaptive_variant_quality(temp_variant)
        if any(marker in error for marker in ("guided_example", "learning_support", "practice_question"))
    ]


def merge_main_repair_content(previous: dict[str, Any], repaired: dict[str, Any], level: str) -> dict[str, Any]:
    merged = dict(previous)
    for key in ("summary", "explanation"):
        value = repaired.get(key)
        if value not in (None, "", []):
            merged[key] = value
    for key, rule_name in (("key_points", "key_points"), ("vocabulary", "vocabulary")):
        value = repaired.get(key)
        if value in (None, "", []):
            continue
        min_items, max_items = ADAPTIVE_LENGTH_RULES.get(level, ADAPTIVE_LENGTH_RULES["intermediaire"])[rule_name]
        normalized = normalize_key_points_payload(value) if key == "key_points" else normalize_vocabulary_payload(value)
        if isinstance(normalized, list) and min_items <= len(normalized) <= max_items:
            merged[key] = value
    return merged


def validate_main_content_payload(payload: dict[str, Any], level: str) -> list[str]:
    rules = ADAPTIVE_LENGTH_RULES.get(level, ADAPTIVE_LENGTH_RULES["intermediaire"])
    errors: list[str] = []
    summary_words = adaptive_word_count(payload.get("summary"))
    explanation_words = adaptive_word_count(payload.get("explanation"))
    min_summary, _ = rules["summary"]
    min_explanation, _ = rules["explanation"]
    if summary_words < min_summary:
        errors.append(f"summary too short ({summary_words} words, minimum {min_summary})")
    if explanation_words < min_explanation:
        errors.append(f"explanation too short ({explanation_words} words, minimum {min_explanation})")
    key_points = normalize_key_points_payload(payload.get("key_points"))
    min_points, max_points = rules["key_points"]
    if not isinstance(key_points, list) or not min_points <= len(key_points) <= max_points:
        errors.append(f"key_points count must be between {min_points} and {max_points}")
    vocabulary = normalize_vocabulary_payload(payload.get("vocabulary"))
    min_vocab, max_vocab = rules["vocabulary"]
    if not isinstance(vocabulary, list) or not min_vocab <= len(vocabulary) <= max_vocab:
        errors.append(f"vocabulary count must be between {min_vocab} and {max_vocab}")
    elif any(
        isinstance(item, dict) and adaptive_word_count(item.get("definition")) < 5
        or hasattr(item, "definition") and adaptive_word_count(item.definition) < 5
        for item in vocabulary
    ):
        errors.append("vocabulary definitions are too short")
    return errors


def merge_usage_metadata(first: dict[str, Any] | None, second: dict[str, Any] | None) -> dict[str, Any]:
    first = first or {}
    second = second or {}
    merged = dict(second)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "tokens_input", "tokens_output"):
        values = [value for value in (first.get(key), second.get(key)) if isinstance(value, (int, float))]
        if values:
            merged[key] = sum(values)
    durations = [value for value in (first.get("duration_ms"), second.get("duration_ms")) if isinstance(value, (int, float))]
    if durations:
        merged["duration_ms"] = sum(durations)
    return merged


def normalize_adaptive_content_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("adaptive content payload must be a JSON object")
    normalized = dict(payload)
    for field_name in ("summary", "explanation"):
        normalized[field_name] = extract_text_field(normalized.get(field_name))
    normalized["key_points"] = normalize_key_points_payload(normalized.get("key_points"))
    normalized["vocabulary"] = normalize_vocabulary_payload(normalized.get("vocabulary"))
    normalized["learning_support"] = normalize_learning_support_payload(normalized.get("learning_support"))
    normalized["practice_question"] = normalize_practice_question_payload(normalized.get("practice_question"))
    normalized["guided_example"] = normalize_guided_example_payload(normalized.get("guided_example"))
    normalized["blocks"] = normalize_generated_blocks(normalized.get("blocks"))
    return normalized


def load_json_object_response(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = json.loads(extract_first_json_object(text))
    if not isinstance(parsed, dict):
        raise ValueError("AI response must be a JSON object")
    return parsed


def extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise json.JSONDecodeError("Unclosed JSON object", text, start)


def extract_text_field(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    return value


def normalize_key_points_payload(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    normalized = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            normalized.append({"title": f"Point clé {index}", "content": item})
        elif isinstance(item, dict):
            normalized.append(item)
        else:
            normalized.append(item)
    return normalized


def normalize_vocabulary_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return [
            {"term": str(term), "definition": str(definition)}
            for term, definition in value.items()
        ]
    if isinstance(value, list):
        normalized = []
        for item in value:
            if isinstance(item, dict):
                term = item.get("term") or item.get("word") or item.get("notion") or item.get("title") or item.get("concept")
                definition = item.get("definition") or item.get("meaning") or item.get("description") or item.get("content") or item.get("explanation")
                if term or definition:
                    normalized.append({"term": str(term or ""), "definition": str(definition or "")})
                else:
                    normalized.append(item)
            elif isinstance(item, str) and ":" in item:
                term, definition = item.split(":", 1)
                normalized.append({"term": term.strip(), "definition": definition.strip()})
            else:
                normalized.append(item)
        return normalized
    return value


def normalize_learning_support_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    payload = dict(value)
    if "method" in payload:
        payload["method"] = extract_text_field(payload.get("method"))
    pitfalls = payload.get("pitfalls")
    if isinstance(pitfalls, str):
        payload["pitfalls"] = [pitfalls]
    return payload


def normalize_practice_question_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    payload = dict(value)
    for field_name in ("question", "instruction", "difficulty", "expected_answer", "explanation"):
        if field_name in payload:
            payload[field_name] = extract_text_field(payload.get(field_name))
    expected_elements = payload.get("expected_elements")
    if isinstance(expected_elements, str):
        payload["expected_elements"] = [expected_elements]
    return payload


def normalize_guided_example_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    payload = dict(value)
    for field_name in ("title", "instruction", "content", "answer"):
        if field_name in payload:
            payload[field_name] = extract_text_field(payload.get(field_name))
    steps = payload.get("steps")
    if isinstance(steps, str):
        payload["steps"] = split_structured_text_items(steps)
    elif isinstance(steps, list):
        normalized_steps = []
        for item in steps:
            if isinstance(item, str):
                normalized_steps.append(item)
            elif isinstance(item, dict) and isinstance(item.get("step"), str):
                normalized_steps.append(item["step"])
            else:
                normalized_steps.append(item)
        payload["steps"] = normalized_steps
    return payload


def split_structured_text_items(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [
        item.strip(" .:-\t")
        for item in re.split(r"(?:\n+|(?:^|\s)\d+[\).\-\s]+)", text)
        if item.strip(" .:-\t")
    ]
    return parts or [text]


def normalize_generated_blocks(value: Any) -> Any:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return value
    blocks = []
    for item in value:
        if not isinstance(item, dict):
            continue
        block = dict(item)
        block_type = normalize_generated_block_type(block)
        if not block_type:
            blocks.append(block)
            continue
        block["type"] = block_type
        if "content" not in block and "text" in block:
            block["content"] = block.get("text")
        for key in (
            "source_block_id",
            "source_chapter_id",
            "source_hash",
            "level",
            "generation_method",
            "generated_at",
            "chapter_source_id",
            "model",
            "source_ids",
            "question",
            "answer",
            "correction",
            "method",
            "steps",
            "pitfalls",
            "items",
            "points",
            "term",
            "definition",
            "text",
        ):
            block.pop(key, None)
        blocks.append(block)
    return blocks


def normalize_generated_block_type(block: dict[str, Any]) -> str | None:
    raw_type = block.get("type")
    if raw_type:
        return normalize_generated_block_type_name(raw_type)
    title = normalize_for_similarity(block.get("title") or "")
    if "content" not in block and "text" in block:
        block["content"] = block.get("text")
    if "mini" in title and ("evaluation" in title or "assessment" in title):
        if "content" not in block and "question" in block:
            block["content"] = {
                "question": block.get("question", ""),
                "answer": block.get("answer", ""),
                "explanation": block.get("explanation", ""),
            }
        return "mini_assessment"
    if "correction" in title or "solution" in title:
        block.setdefault("content", block.get("answer") or block.get("correction") or block.get("text") or "")
        return "correction"
    if "exercice" in title or "exercise" in title or "entrainement" in title:
        block.setdefault("content", block.get("question") or block.get("instruction") or block.get("text") or "")
        return "exercise"
    if "exemple" in title or "example" in title:
        block.setdefault("content", block.get("text") or block.get("content") or "")
        return "example"
    if "methode" in title or "method" in title:
        block.setdefault("content", block.get("method") or block.get("steps") or block.get("text") or "")
        return "methodology"
    if "attention" in title or "erreur" in title or "warning" in title or "piege" in title:
        block.setdefault("content", block.get("pitfalls") or block.get("text") or block.get("content") or "")
        return "warning"
    if "point" in title or "retenir" in title:
        block.setdefault("content", block.get("items") or block.get("points") or block.get("text") or "")
        return "key_points"
    if "resume" in title or "summary" in title:
        block.setdefault("content", block.get("text") or block.get("content") or "")
        return "summary"
    if "sequence" in title and ("content" in block or "text" in block or "steps" in block):
        block.setdefault("content", block.get("content") or block.get("text") or block.get("steps") or "")
        return "paragraph"
    if "question" in block and ("answer" in block or "explanation" in block):
        block.setdefault(
            "content",
            {
                "question": block.get("question", ""),
                "answer": block.get("answer", ""),
                "explanation": block.get("explanation", ""),
            },
        )
        block.setdefault("title", "Mini-évaluation")
        return "mini_assessment"
    if "question" in block:
        block.setdefault("content", block.get("question"))
        block.setdefault("title", "Exercice")
        return "exercise"
    if "answer" in block or "correction" in block:
        block.setdefault("content", block.get("answer") or block.get("correction"))
        block.setdefault("title", "Correction")
        return "correction"
    if "term" in block and "definition" in block:
        block.setdefault("title", block.get("term"))
        block.setdefault("content", block.get("definition"))
        return "definition"
    if "method" in block or "steps" in block or "pitfalls" in block:
        block.setdefault("content", block.get("method") or block.get("steps") or block.get("pitfalls"))
        block.setdefault("title", "Méthode")
        return "methodology"
    if "items" in block or "points" in block:
        block.setdefault("content", block.get("items") or block.get("points"))
        block.setdefault("title", "Points clés")
        return "key_points"
    return None


def normalize_generated_block_type_name(value: Any) -> str:
    clean = normalize_for_similarity(value).replace(" ", "_").replace("-", "_")
    aliases = {
        "resume": "summary",
        "summary": "summary",
        "explication": "paragraph",
        "explanation": "paragraph",
        "paragraph": "paragraph",
        "definition": "definition",
        "vocabulaire": "definition",
        "example": "example",
        "exemple": "example",
        "method": "methodology",
        "methode": "methodology",
        "methodology": "methodology",
        "warning": "warning",
        "attention": "warning",
        "key_points": "key_points",
        "points_cles": "key_points",
        "exercise": "exercise",
        "exercice": "exercise",
        "correction": "correction",
        "solution": "correction",
        "mini_assessment": "mini_assessment",
        "quiz": "mini_assessment",
        "schema": "visual",
        "visual": "visual",
    }
    return aliases.get(clean, clean)


def generate_three_level_adaptive_variants(
    db: Session | None,
    *,
    course_id: int | None,
    chapter_id: int | None,
    chapter_source_id: str,
    chapter_title: str,
    subject: str,
    sources: list[dict[str, Any]],
    user_id: int | None = None,
    levels: tuple[str, ...] = LEVELS,
) -> tuple[dict[str, AdaptiveChapterVariant], dict[str, Any]]:
    settings = get_settings()
    selected_levels = tuple(level for level in LEVELS if level in set(levels or LEVELS))
    if not settings.get("ai_content_generation_enabled"):
        return deterministic_three_level_adaptive_variants(chapter_source_id, chapter_title, sources, "AI_CONTENT_GENERATION_ENABLED=false")

    compact_sources = prepare_compact_variant_sources(sources, settings)
    fallback_variants, fallback_metadata = deterministic_three_level_adaptive_variants(
        chapter_source_id,
        chapter_title,
        sources,
        "deterministic_fallback",
    )
    if not compact_sources:
        return fallback_variants, fallback_metadata

    source_digest = source_hash(compact_sources)
    source_block_ids = source_ids_from_sources(compact_sources)
    user_payload = build_variant_set_payload(chapter_source_id, chapter_title, compact_sources, settings)
    estimated_input_tokens = estimate_payload_tokens(user_payload)
    max_output_tokens = int(settings.get("ai_variant_level_max_output_tokens") or settings.get("ai_variant_max_output_tokens") or 1800)

    variants: dict[str, AdaptiveChapterVariant] = {}
    metadata_by_level: dict[str, dict[str, Any]] = {}

    for level in selected_levels:
        variants[level], metadata_by_level[level] = generate_level_with_single_repair(
            db,
            user_payload=user_payload,
            subject=subject,
            level=level,
            course_id=course_id,
            chapter_id=chapter_id,
            user_id=user_id,
            source_digest=source_digest,
            source_block_ids=source_block_ids,
            max_output_tokens=max_output_tokens,
            estimated_input_tokens=estimated_input_tokens,
            fallback_variant=fallback_variants[level],
            fallback_metadata=fallback_metadata[level],
        )

    invalid_similarity_levels = invalid_levels_for_similarity(variants)
    for level in sorted(invalid_similarity_levels):
        if variants[level].generation_method != "ai_generated":
            continue
        repaired_variant, repaired_metadata = generate_level_with_single_repair(
            db,
            user_payload=user_payload,
            subject=subject,
            level=level,
            course_id=course_id,
            chapter_id=chapter_id,
            user_id=user_id,
            source_digest=source_digest,
            source_block_ids=source_block_ids,
            max_output_tokens=max_output_tokens,
            estimated_input_tokens=estimated_input_tokens,
            fallback_variant=fallback_variants[level],
            fallback_metadata=fallback_metadata[level],
            retry_reason="similarity_repair",
            previous_error="This level is too similar to another validated level. Rewrite only this level with a clearly different pedagogical angle.",
        )
        variants[level] = repaired_variant
        metadata_by_level[level] = merge_level_metadata(metadata_by_level[level], repaired_metadata)

    if set(variants) == set(LEVELS):
        try:
            variant_set = AdaptiveChapterVariantSet(chapter_source_id=chapter_source_id, variants=variants)
            validate_adaptive_variant_set_quality(variant_set)
        except AdaptiveVariantQualityError as exc:
            for level in exc.invalid_levels:
                if level in variants and variants[level].generation_method == "ai_generated":
                    variants[level] = fallback_variants[level]
                    metadata_by_level[level] = fallback_metadata_for_level(
                        fallback_metadata[level],
                        str(exc),
                        estimated_input_tokens,
                        max_output_tokens,
                        previous_metadata=metadata_by_level.get(level),
                    )

    return variants, metadata_by_level


def generate_level_with_single_repair(
    db: Session | None,
    *,
    user_payload: dict[str, Any],
    subject: str,
    level: str,
    course_id: int | None,
    chapter_id: int | None,
    user_id: int | None,
    source_digest: str,
    source_block_ids: list[str],
    max_output_tokens: int,
    estimated_input_tokens: int,
    fallback_variant: AdaptiveChapterVariant,
    fallback_metadata: dict[str, Any],
    retry_reason: str | None = None,
    previous_error: str | None = None,
) -> tuple[AdaptiveChapterVariant, dict[str, Any]]:
    try:
        return generate_single_level_adaptive_variant(
            db,
            user_payload=user_payload,
            subject=subject,
            level=level,
            course_id=course_id,
            chapter_id=chapter_id,
            user_id=user_id,
            source_digest=source_digest,
            source_block_ids=source_block_ids,
            max_output_tokens=max_output_tokens,
            retry_reason=retry_reason,
            previous_error=previous_error,
        )
    except (AIProviderError, ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        first_error = str(exc)[:1000]
        provider_metadata = provider_error_metadata(exc)
        if isinstance(exc, VariantProviderExecutionError) and provider_metadata.get("final_http_status") != 413:
            return fallback_variant, fallback_metadata_for_level(
                fallback_metadata,
                first_error,
                estimated_input_tokens,
                max_output_tokens,
                previous_metadata=provider_metadata,
            )
        if retry_reason is None:
            repair_payload = reduced_level_payload(user_payload) if "HTTP 413" in first_error else user_payload
            if isinstance(exc, AdaptiveVariantQualityError) and exc.payload:
                repair_payload = {
                    **repair_payload,
                    "previous_invalid_payload": slim_adaptive_variant_payload(exc.payload),
                    "repair_instruction": (
                        "Return the complete JSON object again. Keep the same facts from previous_invalid_payload, "
                        "but expand every field named in validation_feedback until it passes the real backend word counts. "
                        "If vocabulary count fails, add missing terms that are explicitly present in the provided sources. "
                        "If learning_support is too short, expand method, steps, pitfalls, and memory_tip with source-based guidance."
                    ),
                }
            repair_reason = "http_413_payload_reduced" if "HTTP 413" in first_error else "validation_repair"
            try:
                repaired, metadata = generate_single_level_adaptive_variant(
                    db,
                    user_payload=repair_payload,
                    subject=subject,
                    level=level,
                    course_id=course_id,
                    chapter_id=chapter_id,
                    user_id=user_id,
                    source_digest=source_digest,
                    source_block_ids=source_block_ids,
                    max_output_tokens=max_output_tokens,
                    retry_reason=repair_reason,
                    previous_error=first_error,
                )
                metadata["previous_error"] = first_error
                return repaired, metadata
            except (AIProviderError, ValidationError, json.JSONDecodeError, TypeError, ValueError) as repair_exc:
                return fallback_variant, fallback_metadata_for_level(
                    fallback_metadata,
                    str(repair_exc),
                    estimated_input_tokens,
                    max_output_tokens,
                    previous_error=first_error,
                    previous_metadata={
                        **provider_error_metadata(repair_exc),
                        "retry_reason": repair_reason,
                    },
                )
        return fallback_variant, fallback_metadata_for_level(
            fallback_metadata,
            first_error,
            estimated_input_tokens,
            max_output_tokens,
            previous_metadata=provider_metadata,
        )


def slim_adaptive_variant_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "summary",
        "explanation",
        "key_points",
        "vocabulary",
        "guided_example",
        "learning_support",
        "practice_question",
    )
    return {key: payload.get(key) for key in allowed if key in payload}


def variant_word_targets(level: str) -> dict[str, Any]:
    if level == "debutant":
        return {
            "summary_words": "140-170",
            "explanation_words": "260-320",
            "key_points_count": "5",
            "vocabulary_count": "5",
            "guided_example_content_words": "140-170",
            "learning_support_total_words": "110-140",
            "learning_support_structure": "method 55+ words, 3 steps of 12+ words, 2 pitfalls of 12+ words, memory_tip 18+ words",
            "practice_question_words": "question 18+, expected_answer 45+, explanation 45+",
        }
    if level == "avance":
        return {
            "summary_words": "220-260",
            "explanation_words": "230-300",
            "key_points_count": "8",
            "vocabulary_count": "8",
            "guided_example_content_words": "150-190",
            "learning_support_total_words": "110-150",
            "learning_support_structure": "method 55+ words, 4 steps of 12+ words, 3 pitfalls of 12+ words, memory_tip 18+ words",
            "practice_question_words": "question 28+, expected_answer 70+, explanation 70+",
        }
    return {
        "summary_words": "180-220",
        "explanation_words": "210-280",
        "key_points_count": "6",
        "vocabulary_count": "6",
        "guided_example_content_words": "130-170",
        "learning_support_total_words": "95-130",
        "learning_support_structure": "method 45+ words, 4 steps of 10+ words, 2 pitfalls of 10+ words, memory_tip 16+ words",
        "practice_question_words": "question 24+, expected_answer 60+, explanation 60+",
    }


def reduced_level_payload(user_payload: dict[str, Any]) -> dict[str, Any]:
    reduced = dict(user_payload)
    sources = user_payload.get("sources") if isinstance(user_payload.get("sources"), list) else []
    reduced_sources = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        payload = dict(source)
        text = str(payload.get("text") or "")
        payload["text"] = clip_text_to_budget(text, max(800, len(text) // 2))
        reduced_sources.append(payload)
    reduced["sources"] = reduced_sources
    reduced["retry_reason"] = "http_413_payload_reduced"
    return reduced


def source_ids_from_sources(sources: list[dict[str, Any]]) -> list[str]:
    return [str(source.get("id") or source.get("source_block_id")) for source in sources if source.get("id") or source.get("source_block_id")]


def invalid_levels_for_similarity(variants: dict[str, AdaptiveChapterVariant]) -> set[str]:
    if set(variants) != set(LEVELS):
        return set()
    try:
        variant_set = AdaptiveChapterVariantSet(chapter_source_id=next(iter(variants.values())).chapter_source_id, variants=variants)
    except ValidationError:
        return set()
    invalid: set[str] = set()
    for level_pair, _message in validate_adaptive_level_differences(variant_set):
        invalid.update(level_pair)
    return invalid


def merge_level_metadata(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    return {
        **previous,
        **current,
        "attempts": int(previous.get("attempts") or 0) + int(current.get("attempts") or 0),
        "rate_limit_retry_count": int(previous.get("rate_limit_retry_count") or 0) + int(current.get("rate_limit_retry_count") or 0),
        "repair_attempted": bool(previous.get("repair_attempted") or current.get("repair_attempted")),
        "previous_validation_status": previous.get("validation_status"),
    }

def deterministic_three_level_adaptive_variants(
    chapter_source_id: str,
    chapter_title: str,
    sources: list[dict[str, Any]],
    reason: str,
) -> tuple[dict[str, AdaptiveChapterVariant], dict[str, Any]]:
    variants = {
        level: deterministic_adaptive_chapter_variant(
            chapter_source_id=chapter_source_id,
            chapter_title=chapter_title,
            level=level,
            sources=sources,
        )
        for level in LEVELS
    }
    metadata = {
        level: {
            "status": "deterministic_fallback",
            "provider": "deterministic",
            "model_name": None,
            "error": reason[:500],
            "estimated_input_tokens": estimate_payload_tokens({"sources": sources}),
            "max_output_tokens": 0,
            "final_payload_chars": len(json.dumps(sources, ensure_ascii=False, default=str)),
            "raw_structure_normalized": False,
            "original_variants_format": "none",
            "validation_status": "not_attempted",
            "repair_attempted": False,
            "rate_limit_retry_count": 0,
            "retry_after_seconds": 0,
            "attempts": 0,
            "final_http_status": None,
            "generation_method": "deterministic_fallback",
        }
        for level in LEVELS
    }
    return variants, metadata


def fallback_metadata_for_error(
    metadata: dict[str, Any],
    error: str,
    estimated_input_tokens: int,
    max_output_tokens: int,
    retry_reason: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra_metadata = extra_metadata or {}
    return {
        level: data | {
            "error": error[:500],
            "estimated_input_tokens": estimated_input_tokens,
            "max_output_tokens": max_output_tokens,
            "retry_reason": retry_reason,
            "raw_structure_normalized": extra_metadata.get("raw_structure_normalized", data.get("raw_structure_normalized", False)),
            "original_variants_format": extra_metadata.get("original_variants_format", data.get("original_variants_format", "unknown")),
            "validation_status": extra_metadata.get("validation_status", data.get("validation_status", "failed")),
            "repair_attempted": extra_metadata.get("repair_attempted", data.get("repair_attempted", False)),
            "rate_limit_retry_count": extra_metadata.get("rate_limit_retry_count", data.get("rate_limit_retry_count", 0)),
            "retry_after_seconds": extra_metadata.get("retry_after_seconds", data.get("retry_after_seconds", 0)),
            "attempts": extra_metadata.get("attempts", data.get("attempts", 0)),
            "final_http_status": extra_metadata.get("final_http_status", data.get("final_http_status")),
            "provider": extra_metadata.get("provider", data.get("provider", "groq")),
            "model_name": extra_metadata.get("model_name", data.get("model_name")),
            "generation_method": "deterministic_fallback",
        }
        for level, data in metadata.items()
    }


def fallback_metadata_for_level(
    metadata: dict[str, Any],
    error: str,
    estimated_input_tokens: int,
    max_output_tokens: int,
    previous_error: str | None = None,
    previous_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_metadata = previous_metadata or {}
    attempts = max(1, int(previous_metadata.get("attempts") or metadata.get("attempts") or 0))
    return metadata | {
        "error": error[:500],
        "previous_error": previous_error[:500] if previous_error else None,
        "estimated_input_tokens": estimated_input_tokens,
        "max_output_tokens": max_output_tokens,
        "retry_reason": previous_metadata.get("retry_reason", metadata.get("retry_reason")),
        "validation_status": "failed",
        "repair_attempted": bool(previous_error) or bool(previous_metadata.get("repair_attempted")),
        "rate_limit_retry_count": previous_metadata.get("rate_limit_retry_count", metadata.get("rate_limit_retry_count", 0)),
        "retry_after_seconds": previous_metadata.get("retry_after_seconds", metadata.get("retry_after_seconds", 0)),
        "attempts": attempts,
        "final_http_status": previous_metadata.get("final_http_status", metadata.get("final_http_status")),
        "provider": previous_metadata.get("provider", metadata.get("provider", "groq")),
        "model_name": previous_metadata.get("model_name", metadata.get("model_name")),
        "generation_method": "deterministic_fallback",
        "generated_at": datetime.utcnow().isoformat(),
    }


def provider_error_metadata(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, VariantProviderExecutionError):
        return exc.metadata
    return {}


def prepare_compact_variant_sources(sources: list[dict[str, Any]], settings: dict, shrink_factor: float = 1.0) -> list[dict[str, Any]]:
    max_chars = int((settings.get("ai_variant_source_max_chars") or 8000) * shrink_factor)
    max_tokens = int((settings.get("ai_variant_max_input_tokens") or 2200) * shrink_factor)
    max_sources = max(1, int(settings.get("ai_variant_max_sources") or 5))
    compact_candidates = []
    seen_texts = set()
    for source in sources:
        if source_is_excluded_from_prompt(source):
            continue
        text = clean_source_text(source.get("text") or source.get("content") or "")
        if not text:
            continue
        signature = " ".join(text.lower().split())[:220]
        if signature in seen_texts:
            continue
        seen_texts.add(signature)
        compact_candidates.append({
            "id": str(source.get("id") or source.get("source_block_id") or len(compact_candidates) + 1),
            "source_block_id": str(source.get("source_block_id") or source.get("id") or len(compact_candidates) + 1),
            "source_chapter_id": source.get("source_chapter_id"),
            "type": source.get("type") or "paragraph",
            "section": source.get("section") or "",
            "priority": source_priority(source),
            "text": text,
        })
    compact_candidates.sort(key=lambda item: (item["priority"], item["id"]))
    selected = []
    used_chars = 0
    used_tokens = 0
    for source in compact_candidates:
        remaining_chars = max_chars - used_chars
        remaining_tokens = max_tokens - used_tokens
        if remaining_chars <= 0 or remaining_tokens <= 0:
            break
        text = clip_text_to_budget(source["text"], min(remaining_chars, remaining_tokens * 4))
        if not text:
            continue
        used_chars += len(text)
        used_tokens += estimate_text_tokens(text)
        selected.append({key: value for key, value in {**source, "text": text}.items() if key != "priority"})
        if len(selected) >= max_sources:
            break
    return selected


def source_is_excluded_from_prompt(source: dict[str, Any]) -> bool:
    descriptor = " ".join(str(source.get(key) or "") for key in ("type", "section", "title", "source_block_id")).lower()
    metadata = str(source.get("metadata") or "").lower()
    text = f"{descriptor} {metadata}"
    excluded_markers = (
        "regional_exam",
        "regional-exam",
        "regional_exams",
        "examens_regionaux",
        "official",
        "official_source",
        "pdf",
        "latex",
        "mermaid",
        "qcm",
        "multiple_choice",
        "correct_answer",
        "session",
        "academie",
        "region",
    )
    if any(marker in text for marker in excluded_markers):
        return True
    if source.get("type") in {"visual", "diagram", "table", "image", "code"}:
        return True
    return False


def source_priority(source: dict[str, Any]) -> int:
    descriptor = " ".join(str(source.get(key) or "") for key in ("type", "section", "title", "source_block_id")).lower()
    for marker, priority in COMPACT_SOURCE_PRIORITIES.items():
        if marker in descriptor:
            return priority
    return 4


def clean_source_text(value: str) -> str:
    text = str(value or "").replace("\x00", " ")
    text = " ".join(text.split())
    return text


def clip_text_to_budget(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    clipped = value[:max(0, max_chars)].rsplit(" ", 1)[0].strip()
    return clipped or value[:max(0, max_chars)].strip()


def estimate_text_tokens(value: str) -> int:
    return max(1, (len(str(value or "")) + 3) // 4)


def estimate_payload_tokens(payload: Any) -> int:
    return estimate_text_tokens(json.dumps(payload, ensure_ascii=False, default=str))


def build_variant_set_payload(
    chapter_source_id: str,
    chapter_title: str,
    compact_sources: list[dict[str, Any]],
    settings: dict,
    shrink_factor: float = 1.0,
) -> dict[str, Any]:
    return {
        "chapter_source_id": chapter_source_id,
        "chapter_title": chapter_title,
        "levels": list(LEVELS),
        "sources": compact_sources,
        "budget": {
            "max_input_tokens": int((settings.get("ai_variant_max_input_tokens") or 2200) * shrink_factor),
            "max_output_tokens": int((settings.get("ai_variant_max_output_tokens") or 1800) * shrink_factor),
            "total_budget_tokens": int(settings.get("ai_groq_tpm_budget") or 5500),
        },
        "schema_hint": "AdaptiveChapterVariantSet",
    }


def request_variant_set(
    db: Session | None,
    *,
    user_payload: dict[str, Any],
    subject: str,
    course_id: int | None,
    chapter_id: int | None,
    user_id: int | None,
    source_digest: str,
    max_output_tokens: int,
    estimated_input_tokens: int,
    retry_reason: str | None,
) -> tuple[AdaptiveChapterVariantSet, dict[str, Any]]:
    settings = get_settings()
    provider = get_ai_provider()
    response, call_metadata = execute_variant_provider_call(
        provider,
        AIRequest(
            system_prompt=adaptive_course_variant_set_prompt(subject),
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            response_schema=AdaptiveChapterVariantSet.model_json_schema(),
            max_tokens=max(400, int(max_output_tokens)),
            timeout_seconds=float(settings.get("ai_variant_timeout_seconds") or 20),
            model_name=settings.get("ai_variant_model") or settings.get("ai_model"),
            metadata={"prompt_version": PROMPT_VERSIONS["adaptive_course_variant"], "retry_reason": retry_reason},
        ),
        settings=settings,
    )
    parsed = json.loads(response.text)
    repair_attempted = False
    normalization_metadata = {
        "raw_structure_normalized": False,
        "original_variants_format": "unknown",
    }
    try:
        normalized, normalization_metadata = normalize_adaptive_variant_payload(
            parsed,
            expected_chapter_source_id=str(user_payload.get("chapter_source_id") or ""),
        )
        model = AdaptiveChapterVariantSet.model_validate(normalized)
        validate_adaptive_variant_set_quality(model)
        validation_status = "validated"
    except (AdaptiveVariantQualityError, ValueError, ValidationError) as exc:
        repair_attempted = True
        repair_payload = build_variant_set_repair_payload(
            expected_chapter_source_id=str(user_payload.get("chapter_source_id") or ""),
            validation_error=compact_structure_error(exc),
            invalid_levels=sorted(exc.invalid_levels) if isinstance(exc, AdaptiveVariantQualityError) else None,
            previous_payload=normalized if "normalized" in locals() else None,
        )
        repair_response, repair_call_metadata = execute_variant_provider_call(
            provider,
            AIRequest(
                system_prompt=adaptive_course_variant_set_prompt(subject),
                user_prompt=json.dumps(repair_payload, ensure_ascii=False),
                response_schema=AdaptiveChapterVariantSet.model_json_schema(),
                max_tokens=max(1200, min(int(max_output_tokens), 1800)),
                timeout_seconds=float(settings.get("ai_variant_timeout_seconds") or 20),
                model_name=settings.get("ai_variant_model") or settings.get("ai_model"),
                metadata={
                    "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
                    "retry_reason": "schema_validation_repair",
                },
            ),
            settings=settings,
        )
        parsed = json.loads(repair_response.text)
        normalized, repair_normalization_metadata = normalize_adaptive_variant_payload(
            parsed,
            expected_chapter_source_id=str(user_payload.get("chapter_source_id") or ""),
        )
        normalization_metadata = {
            **normalization_metadata,
            "repair": repair_normalization_metadata,
        }
        model = AdaptiveChapterVariantSet.model_validate(normalized)
        validate_adaptive_variant_set_quality(model)
        response = repair_response
        call_metadata = merge_provider_call_metadata(call_metadata, repair_call_metadata)
        retry_reason = retry_reason or "schema_validation_repair"
        validation_status = "validated_after_repair"
    usage = provider.get_usage_metadata(response) | response.usage
    usage.setdefault("tokens_input", estimated_input_tokens)
    usage.setdefault("tokens_output", max_output_tokens)
    metadata = {
        "status": "ai_generated",
        "provider": response.provider,
        "model_name": response.model_name,
        "source_hash": source_digest,
        "usage": usage,
        "estimated_input_tokens": estimated_input_tokens,
        "max_output_tokens": max_output_tokens,
        "retry_reason": retry_reason,
        "raw_structure_normalized": normalization_metadata["raw_structure_normalized"],
        "original_variants_format": normalization_metadata["original_variants_format"],
        "validation_status": validation_status,
        "repair_attempted": repair_attempted,
        "generation_method": "ai_generated",
        "rate_limit_retry_count": call_metadata["rate_limit_retry_count"],
        "retry_after_seconds": call_metadata["retry_after_seconds"],
        "attempts": call_metadata["attempts"],
        "final_http_status": call_metadata["final_http_status"],
    }
    record_generation(
        db,
        generation_type="adaptive_course_variant_set",
        provider=response.provider,
        model_name=response.model_name,
        prompt_version=PROMPT_VERSIONS["adaptive_course_variant"],
        input_payload={"chapter_source_id": user_payload.get("chapter_source_id"), "source_count": len(user_payload.get("sources") or [])},
        source_hash=source_digest,
        output_payload={"chapter_source_id": model.chapter_source_id, "levels": list(model.variants.keys())},
        status="ai_generated",
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        usage=usage,
        metadata={
            "estimated_input_tokens": estimated_input_tokens,
            "max_output_tokens": max_output_tokens,
            "retry_reason": retry_reason,
            "final_payload_chars": len(json.dumps(user_payload, ensure_ascii=False)),
            "raw_structure_normalized": normalization_metadata["raw_structure_normalized"],
            "original_variants_format": normalization_metadata["original_variants_format"],
            "validation_status": validation_status,
            "repair_attempted": repair_attempted,
            "generation_method": "ai_generated",
            "provider": response.provider,
            "model_name": response.model_name,
            "rate_limit_retry_count": call_metadata["rate_limit_retry_count"],
            "retry_after_seconds": call_metadata["retry_after_seconds"],
            "attempts": call_metadata["attempts"],
            "final_http_status": call_metadata["final_http_status"],
        },
    )
    return model, metadata


def normalize_adaptive_variant_payload(payload: Any, expected_chapter_source_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("adaptive variant payload must be a JSON object")

    normalized = dict(payload)
    raw_structure_normalized = False
    if normalized.pop("chapter_id", None) is not None:
        raw_structure_normalized = True

    if normalized.get("chapter_source_id") != expected_chapter_source_id:
        normalized["chapter_source_id"] = expected_chapter_source_id
        raw_structure_normalized = True

    variants = normalized.get("variants")
    original_variants_format = "list" if isinstance(variants, list) else "dict" if isinstance(variants, dict) else type(variants).__name__
    if isinstance(variants, list):
        converted: dict[str, Any] = {}
        for item in variants:
            if not isinstance(item, dict):
                raise ValueError("each adaptive variant must be an object")
            level = normalize_variant_level(item.get("level"))
            if not level:
                raise ValueError("adaptive variant level is missing or unknown")
            if level in converted:
                raise ValueError(f"duplicate adaptive variant level: {level}")
            converted[level] = dict(item)
        variants = converted
        raw_structure_normalized = True
    elif isinstance(variants, dict):
        converted = {}
        for key, value in variants.items():
            if not isinstance(value, dict):
                raise ValueError("each adaptive variant must be an object")
            level = normalize_variant_level(value.get("level") or key)
            if not level:
                raise ValueError(f"unknown adaptive variant level: {key}")
            if level in converted:
                raise ValueError(f"duplicate adaptive variant level: {level}")
            converted[level] = dict(value)
        variants = converted
    else:
        raise ValueError("adaptive variants must be an object or a list")

    expected_levels = set(LEVELS)
    received_levels = set(variants)
    if received_levels != expected_levels:
        missing = sorted(expected_levels - received_levels)
        extra = sorted(received_levels - expected_levels)
        details = []
        if missing:
            details.append(f"missing levels: {', '.join(missing)}")
        if extra:
            details.append(f"unknown levels: {', '.join(extra)}")
        raise ValueError("; ".join(details) or "invalid adaptive variant levels")

    normalized_variants = {}
    for level in LEVELS:
        variant = dict(variants[level])
        if variant.pop("chapter_id", None) is not None:
            raw_structure_normalized = True
        if variant.get("level") != level:
            variant["level"] = level
            raw_structure_normalized = True
        if variant.get("chapter_source_id") != expected_chapter_source_id:
            variant["chapter_source_id"] = expected_chapter_source_id
            raw_structure_normalized = True
        normalized_variants[level] = variant

    normalized["variants"] = normalized_variants
    return normalized, {
        "raw_structure_normalized": raw_structure_normalized,
        "original_variants_format": original_variants_format,
    }


def normalize_variant_level(value: Any) -> str | None:
    raw = (
        str(value or "")
        .strip()
        .lower()
        .replace("Ã©", "é")
        .replace("ã©", "é")
        .replace("Ã¨", "è")
        .replace("ã¨", "è")
    )
    cleaned = unicodedata.normalize("NFD", raw)
    cleaned = "".join(char for char in cleaned if unicodedata.category(char) != "Mn")
    aliases = {
        "debutant": "debutant",
        "debutante": "debutant",
        "beginner": "debutant",
        "intermediaire": "intermediaire",
        "intermediate": "intermediaire",
        "avance": "avance",
        "advanced": "avance",
    }
    return aliases.get(cleaned)


def validate_adaptive_variant_set_quality(model: AdaptiveChapterVariantSet) -> None:
    invalid_levels: set[str] = set()
    errors: list[str] = []
    for level, variant in model.variants.items():
        level_errors = validate_adaptive_variant_quality(variant)
        if level_errors:
            invalid_levels.add(level)
            errors.extend(f"{level}: {message}" for message in level_errors)
    similarity_errors = validate_adaptive_level_differences(model)
    for level_pair, message in similarity_errors:
        invalid_levels.update(level_pair)
        errors.append(message)
    if errors:
        raise AdaptiveVariantQualityError("; ".join(errors)[:1200], invalid_levels)


def validate_adaptive_variant_quality(variant: AdaptiveChapterVariant) -> list[str]:
    rules = ADAPTIVE_LENGTH_RULES[variant.level]
    errors: list[str] = []
    for field_name in ("summary", "explanation"):
        word_count = adaptive_word_count(getattr(variant, field_name))
        min_words, _max_words = rules[field_name]
        if word_count < min_words:
            errors.append(f"{field_name} too short ({word_count} words, minimum {min_words})")
        if pedagogically_empty(getattr(variant, field_name)):
            errors.append(f"{field_name} is pedagogically empty")
    key_points = [item for item in variant.key_points if not pedagogically_empty(item)]
    min_points, max_points = rules["key_points"]
    if not min_points <= len(key_points) <= max_points:
        errors.append(f"key_points count must be between {min_points} and {max_points}")
    if any(adaptive_word_count(item) < 6 for item in key_points):
        errors.append("key_points must be explained, not one-word labels")
    vocabulary = [item for item in variant.vocabulary if not pedagogically_empty(item.term) and not pedagogically_empty(item.definition)]
    min_vocab, max_vocab = rules["vocabulary"]
    if not min_vocab <= len(vocabulary) <= max_vocab:
        errors.append(f"vocabulary count must be between {min_vocab} and {max_vocab}")
    if any(adaptive_word_count(item.definition) < 5 for item in vocabulary):
        errors.append("vocabulary definitions are too short")
    guided_words = adaptive_word_count(
        " ".join([
            variant.guided_example.content,
            " ".join(variant.guided_example.steps),
            variant.guided_example.answer,
        ])
    )
    min_guided, _max_guided = rules["guided_example"]
    if guided_words < min_guided or pedagogically_empty(variant.guided_example.content):
        errors.append(f"guided_example incomplete ({guided_words} words, minimum {min_guided})")
    support_text = " ".join(variant.learning_support)
    support_words = adaptive_word_count(support_text)
    min_support, _max_support = rules["learning_support"]
    if support_words < min_support or pedagogically_empty(support_text):
        errors.append(f"learning_support too short ({support_words} words, minimum {min_support})")
    practice_text = " ".join(
        [
            variant.practice_question.question,
            variant.practice_question.expected_answer,
            variant.practice_question.explanation,
        ]
    )
    if adaptive_word_count(variant.practice_question.question) < 12:
        errors.append("practice_question question must include a clear instruction")
    if adaptive_word_count(variant.practice_question.expected_answer) < 18:
        errors.append("practice_question expected_answer is too short")
    if adaptive_word_count(variant.practice_question.explanation) < 20:
        errors.append("practice_question explanation is too short")
    if pedagogically_empty(practice_text):
        errors.append("practice_question is pedagogically empty")
    return errors


def validate_adaptive_level_differences(model: AdaptiveChapterVariantSet) -> list[tuple[tuple[str, str], str]]:
    errors: list[tuple[tuple[str, str], str]] = []
    pairs = (("debutant", "intermediaire"), ("intermediaire", "avance"))
    for left, right in pairs:
        for field_name in ("summary", "explanation", "guided_example", "learning_support", "practice_question"):
            left_text = comparable_variant_field_text(model.variants[left], field_name)
            right_text = comparable_variant_field_text(model.variants[right], field_name)
            similarity = token_jaccard_similarity(left_text, right_text)
            if similarity >= ADAPTIVE_SIMILARITY_THRESHOLD:
                errors.append(((left, right), f"{left} and {right} are too similar for {field_name} ({similarity:.2f})"))
                break
    return errors


def comparable_variant_field_text(variant: AdaptiveChapterVariant, field_name: str) -> str:
    if field_name == "guided_example":
        return f"{variant.guided_example.title} {variant.guided_example.content}"
    if field_name == "learning_support":
        return " ".join(variant.learning_support)
    if field_name == "practice_question":
        return " ".join(
            [
                variant.practice_question.question,
                variant.practice_question.expected_answer,
                variant.practice_question.explanation,
            ]
        )
    return str(getattr(variant, field_name, ""))


def adaptive_word_count(value: Any) -> int:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    return len(re.findall(r"\b[\wÀ-ÿ']+\b", str(value or ""), flags=re.UNICODE))


def pedagogically_empty(value: Any) -> bool:
    normalized = normalize_for_similarity(value)
    if not normalized:
        return True
    if normalized in GENERIC_ADAPTIVE_TEXTS:
        return True
    return adaptive_word_count(value) <= 1


def token_jaccard_similarity(left: Any, right: Any) -> float:
    left_tokens = set(tokenize_for_similarity(left))
    right_tokens = set(tokenize_for_similarity(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def tokenize_for_similarity(value: Any) -> list[str]:
    normalized = normalize_for_similarity(value)
    stop_words = {
        "avec", "dans", "pour", "une", "des", "les", "aux", "sur", "que", "qui",
        "est", "sont", "plus", "moins", "cette", "chapitre", "eleve", "etudiant",
    }
    return [token for token in re.findall(r"\b[a-z0-9]{3,}\b", normalized) if token not in stop_words]


def normalize_for_similarity(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def compact_validation_error(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors()[:5]:
        loc = ".".join(str(item) for item in error.get("loc", []))
        messages.append(f"{loc}: {error.get('msg', 'validation error')}")
    return " | ".join(messages)[:800]


def compact_structure_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return compact_validation_error(exc)
    return str(exc)[:800]


def build_variant_set_repair_payload(
    expected_chapter_source_id: str,
    validation_error: str,
    invalid_levels: list[str] | None = None,
    previous_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "task": "Repair the AdaptiveChapterVariantSet JSON and regenerate only invalid pedagogical levels when listed.",
        "validation_error": validation_error,
        "invalid_levels": invalid_levels or list(LEVELS),
        "previous_payload": previous_payload,
        "expected_schema": {
            "chapter_source_id": expected_chapter_source_id,
            "variants": {
                "debutant": {"level": "debutant"},
                "intermediaire": {"level": "intermediaire"},
                "avance": {"level": "avance"},
            },
        },
        "rules": [
            "Do not return chapter_id.",
            "Use exactly chapter_source_id from expected_schema.",
            "variants must be a JSON object, never a list.",
            "Use exactly the keys debutant, intermediaire and avance.",
            "Keep valid levels if they are present in previous_payload, but rewrite invalid_levels completely.",
            "summary, explanation, guided_example, learning_support and practice_question must be genuinely different between levels.",
            "Do not use generic one-word content such as Aide, Exemple, Resume adapte or Reponse attendue.",
            "Respect the minimum word counts: debutant summary 80 words and explanation 140 words; intermediaire summary 110 words and explanation 200 words; avance summary 140 words and explanation 280 words.",
            "learning_support must contain method steps, guided questions, traps to avoid and memorization advice.",
            "guided_example must include a task, a process and an explained answer.",
            "practice_question must include question, instruction, adapted difficulty and expected answer elements.",
            "Return JSON only.",
        ],
    }


def execute_variant_provider_call(provider, request: AIRequest, *, settings: dict) -> tuple[Any, dict[str, Any]]:
    min_interval = float(settings.get("ai_variant_min_interval_seconds") or 0)
    max_429_retries = int(settings.get("ai_variant_max_rate_limit_retries") or 3)
    metadata = {
        "rate_limit_retry_count": 0,
        "retry_after_seconds": 0.0,
        "attempts": 0,
        "final_http_status": None,
    }

    while True:
        metadata["attempts"] += 1
        wait_for_variant_rate_limit(min_interval)
        try:
            response = provider.generate_structured(request)
            metadata["final_http_status"] = 200
            return response, metadata
        except AIProviderError as exc:
            status_code = extract_http_status(str(exc))
            metadata["final_http_status"] = status_code
            if status_code == 429 and metadata["rate_limit_retry_count"] < max_429_retries:
                retry_after = extract_retry_after_seconds(str(exc)) or min_interval
                wait_seconds = float(retry_after) + 3.0
                metadata["rate_limit_retry_count"] += 1
                metadata["retry_after_seconds"] = wait_seconds
                time.sleep(wait_seconds)
                continue
            raise VariantProviderExecutionError(str(exc), metadata) from exc


def merge_provider_call_metadata(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    return {
        "rate_limit_retry_count": int(first.get("rate_limit_retry_count") or 0) + int(second.get("rate_limit_retry_count") or 0),
        "retry_after_seconds": max(float(first.get("retry_after_seconds") or 0), float(second.get("retry_after_seconds") or 0)),
        "attempts": int(first.get("attempts") or 0) + int(second.get("attempts") or 0),
        "final_http_status": second.get("final_http_status") or first.get("final_http_status"),
        "repair_attempted": bool(first.get("repair_attempted") or second.get("repair_attempted")),
    }


def extract_http_status(message: str) -> int | None:
    match = re.search(r"HTTP\s+(\d{3})", str(message or ""), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_retry_after_seconds(message: str) -> float | None:
    retry_after_match = re.search(r"retry-after['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)", str(message or ""), flags=re.IGNORECASE)
    if retry_after_match:
        return float(retry_after_match.group(1))
    try_again_match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*s", str(message or ""), flags=re.IGNORECASE)
    if try_again_match:
        return float(try_again_match.group(1))
    minute_match = re.search(
        r"try again in\s+(\d+(?:\.\d+)?)\s*m\s*(\d+(?:\.\d+)?)?\s*s?",
        str(message or ""),
        flags=re.IGNORECASE,
    )
    if minute_match:
        minutes = float(minute_match.group(1))
        seconds = float(minute_match.group(2) or 0)
        return minutes * 60 + seconds
    return None


def wait_for_variant_rate_limit(min_interval: float) -> None:
    global _last_variant_request_at
    if min_interval <= 0:
        return
    with _variant_rate_lock:
        now = time.monotonic()
        elapsed = now - _last_variant_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_variant_request_at = time.monotonic()


def generate_chapter_variant(
    db: Session | None,
    *,
    course_id: int | None,
    chapter_id: int | None,
    chapter_title: str,
    level: str,
    subject: str,
    sources: list[dict[str, Any]],
    user_id: int | None = None,
) -> tuple[GeneratedChapterContent, dict[str, Any]]:
    settings = get_settings()
    selected_sources = truncate_sources(sources, int(settings.get("ai_max_source_chars") or 6000))
    allowed_ids = {str(source.get("id") or source.get("source_block_id") or index) for index, source in enumerate(selected_sources, start=1)}
    fallback = deterministic_chapter_variant(chapter_title, level, selected_sources)
    model, metadata = generate_structured(
        schema=GeneratedChapterContent,
        system_prompt=course_chapter_prompt(level, subject),
        user_payload={
            "chapter_title": chapter_title,
            "level": level,
            "sources": selected_sources,
            "schema_hint": "GeneratedChapterContent",
        },
        generation_type="course_chapter",
        prompt_version=PROMPT_VERSIONS["course_generation"],
        db=db,
        user_id=user_id,
        course_id=course_id,
        chapter_id=chapter_id,
        fallback=fallback,
        enabled=bool(settings.get("ai_content_generation_enabled")),
    )
    model = model or fallback
    unknown_sources = validate_source_ids(model.model_dump(), allowed_ids) if allowed_ids else []
    quality = score_course_chapter(model.model_dump(), allowed_ids)
    if unknown_sources:
        model.validation_status = "needs_review"
        quality["checks"]["valid_source_ids"] = False
    else:
        model.validation_status = quality["validation_status"]
    metadata.update({"quality": quality, "unknown_source_ids": unknown_sources})
    return model, metadata


def deterministic_chapter_variant(chapter_title: str, level: str, sources: list[dict[str, Any]]) -> GeneratedChapterContent:
    source_text = first_source_text(sources)
    if not source_text:
        source_text = "Source insuffisante pour produire un contenu complet sans invention."
    source_id = str((sources[0].get("id") or sources[0].get("source_block_id")) if sources else "source_insufficient")
    profile = {
        "debutant": {
            "guidance": "Explication progressive avec vocabulaire simple, rappels et indices visibles.",
            "method": "Lire la phrase source, repérer un mot clé, puis reformuler avec ses propres mots.",
            "exercise": "Complétez une phrase simple avec l'indice donné par le document.",
            "mistake": "Chercher une analyse complexe avant d'avoir compris le sens explicite.",
        },
        "intermediaire": {
            "guidance": "Explication structurée avec justification, liens entre idées et exercice semi-guidé.",
            "method": "Comparer deux indices, formuler une justification et relier la réponse au thème du chapitre.",
            "exercise": "Justifiez une réponse en citant deux indices différents de la source.",
            "mistake": "Donner la bonne idée sans expliquer le lien logique avec le passage.",
        },
        "avance": {
            "guidance": "Analyse approfondie avec nuances, comparaison, limites et critères proches de l'examen.",
            "method": "Construire une argumentation nuancée, distinguer l'explicite de l'implicite et vérifier les limites.",
            "exercise": "Rédigez une réponse argumentée avec thèse, justification, nuance et retour à la source.",
            "mistake": "Surinterpréter le texte ou affirmer une idée non vérifiable dans les sources.",
        },
    }.get(level, {})
    guidance = profile.get("guidance", "Explication adaptée.")
    return GeneratedChapterContent(
        chapter_title=chapter_title,
        level=level,
        learning_objectives=[f"Comprendre {chapter_title}", "Relier la notion aux sources du cours"],
        prerequisites=["Lire le passage source"],
        introduction=f"{guidance} Ce chapitre reprend uniquement les éléments disponibles dans les sources.",
        detailed_explanations=[
            {"title": "Idée principale", "content": source_text, "source_ids": [source_id]},
            {"title": "Méthode", "content": profile.get("method", "Identifier les informations puis les justifier avec le document."), "source_ids": [source_id]},
            {"title": "Vérification", "content": f"À ce niveau, la réponse est validée si elle respecte cette exigence : {guidance}", "source_ids": [source_id]},
        ],
        key_concepts=[{"term": chapter_title, "definition": source_text[:300], "example": profile.get("method", "Exemple fondé sur le passage source."), "source_ids": [source_id]}],
        worked_examples=[{"title": f"Exemple {level}", "content": f"À partir du passage source, appliquez cette démarche : {profile.get('method')}", "source_ids": [source_id]}],
        guided_exercises=[{"prompt": profile.get("exercise", f"Soulignez l'information la plus importante sur {chapter_title}."), "expected_answer": source_text[:180], "source_ids": [source_id]}],
        independent_exercises=[{"prompt": f"Produisez une réponse de niveau {level} sur {chapter_title}.", "expected_answer": "Réponse justifiée par la source et adaptée au niveau.", "source_ids": [source_id]}],
        solutions=[f"La réponse doit rester reliée aux passages sources et suivre l'exigence {level}."],
        common_mistakes=["Répondre sans citer d'indice.", profile.get("mistake", "Inventer une information absente des sources.")],
        revision_summary=source_text[:500],
        flashcards=[{"front": chapter_title, "back": source_text[:200], "source_ids": [source_id]}],
        knowledge_check=[
            {
                "question": f"Quelle démarche est correcte pour étudier {chapter_title} ?",
                "options": ["S'appuyer sur les sources", "Inventer un détail", "Ignorer le document", "Changer de chapitre"],
                "answer": "S'appuyer sur les sources",
                "explanation": "Le contenu doit rester vérifiable dans les sources.",
                "source_ids": [source_id],
            }
        ],
        validation_status="deterministic_fallback" if sources else "source_insufficient",
    )


def generate_three_level_variants(
    db: Session | None,
    *,
    course_id: int | None,
    chapter_id: int | None,
    chapter_title: str,
    subject: str,
    sources: list[dict[str, Any]],
    user_id: int | None = None,
) -> tuple[dict[str, GeneratedChapterContent], dict[str, Any]]:
    variants = {}
    metadata = {}
    for level in LEVELS:
        variants[level], metadata[level] = generate_chapter_variant(
            db,
            course_id=course_id,
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            level=level,
            subject=subject,
            sources=sources,
            user_id=user_id,
        )
    return variants, metadata


def first_source_text(sources: list[dict[str, Any]]) -> str:
    for source in sources:
        text = str(source.get("text") or source.get("content") or source.get("excerpt") or "").strip()
        if text:
            return text[:900]
    return ""
