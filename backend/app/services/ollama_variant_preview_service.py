from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import Course, CourseChapter, CourseLevelVariant
from app.schemas.ai_generation import AdaptiveChapterVariantContent
from app.services.ai.ai_provider import AIProviderError, AIRequest
from app.services.ai.ollama_provider import OLLAMA_HOST, OLLAMA_MODEL, OllamaProvider
from app.services.ai.prompt_templates import PROMPT_VERSIONS, adaptive_course_variant_level_prompt
from app.services.ai.source_grounding_service import source_hash
from app.services.ai_course_generation_service import (
    adaptive_word_count,
    build_variant_from_content,
    prepare_compact_variant_sources,
    source_ids_from_sources,
    variant_word_targets,
    normalize_adaptive_content_payload,
    load_json_object_response,
)
from app.core.config import get_settings
from app.services.course_service import stable_chapter_source_id

ALLOWED_COURSE_ID = 23
ALLOWED_CHAPTER_ID = 197
ALLOWED_LEVEL = "debutant"
REFERENCE_VARIANT_ID = 74
OLLAMA_MAIN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "explanation": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "vocabulary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string"},
                },
                "required": ["term", "definition"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "explanation", "key_points", "vocabulary"],
}

OLLAMA_PEDAGOGY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "guided_example": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "content", "steps"],
            "additionalProperties": False,
        },
        "learning_support": {"type": "array", "items": {"type": "string"}},
        "practice_question": {"type": "string"},
        "expected_answer": {"type": "string"},
        "correction": {"type": "string"},
    },
    "required": [
        "guided_example",
        "learning_support",
        "practice_question",
        "expected_answer",
        "correction",
    ],
}


class OllamaVariantTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: int
    chapter_id: int
    level: str


def test_ollama_variant_preview(db: Session, payload: OllamaVariantTestRequest) -> dict[str, Any]:
    level = payload.level.strip().lower()
    if payload.course_id != ALLOWED_COURSE_ID or payload.chapter_id != ALLOWED_CHAPTER_ID or level != ALLOWED_LEVEL:
        raise ValueError("Only course_id=23, chapter_id=197 and level='debutant' are accepted")

    course = db.scalar(select(Course).where(Course.id == payload.course_id))
    chapter = db.scalar(
        select(CourseChapter)
        .where(CourseChapter.id == payload.chapter_id, CourseChapter.course_id == payload.course_id)
    )
    reference = db.scalar(
        select(CourseLevelVariant)
        .where(
            CourseLevelVariant.id == REFERENCE_VARIANT_ID,
            CourseLevelVariant.course_id == payload.course_id,
            CourseLevelVariant.level == level,
        )
    )
    if course is None or chapter is None or reference is None:
        raise ValueError("Course, chapter or Groq reference variant not found")

    chapter_source_id = stable_chapter_source_id(chapter)
    sources = build_chapter_sources(chapter, chapter_source_id)
    reference_context = extract_reference_chapter_context(reference, chapter_source_id)
    sources = align_sources_with_reference_context(sources, reference_context)
    settings = {
        **get_settings(),
        "ai_variant_source_max_chars": 8000,
        "ai_variant_max_input_tokens": 2200,
        "ai_variant_max_sources": 5,
    }
    compact_sources = prepare_compact_variant_sources(sources, settings)
    source_digest = source_hash(compact_sources)
    user_payload = {
        "chapter_source_id": chapter_source_id,
        "chapter_title": chapter.title,
        "level": level,
        "sources": compact_sources,
        "reference_context": reference_context,
        "allowed_facts": {
            "msid": "Le Msid est une ecole coranique, pas une piece de la maison.",
            "impasse": "Une impasse est une rue ou un passage sans issue.",
            "chapter_scope": "Le chapitre 1 est l'incipit du roman; il ne represente pas la fin de l'histoire.",
            "chapter_end": "Le chapitre s'acheve sur la dispute entre Lalla Zoubida et Rahma, puis l'evanouissement de Sidi Mohammed.",
            "figures_de_style": "Ne cite une figure de style que si tu la nommes et expliques son effet.",
        },
        "forbidden_claims": [
            "Msid piece de la maison",
            "chapitre 1 fin de l'histoire",
            "ouverture de la tristesse",
            "figure de style sans nom ni effet",
            "contenu absent des sources",
        ],
        "strict_word_targets": variant_word_targets(level),
        "reference_variant_id": REFERENCE_VARIANT_ID,
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

    provider = OllamaProvider()
    main_response, pedagogy_response, parsed = generate_ollama_preview_sections(provider, user_payload, level)

    try:
        normalized = normalize_adaptive_content_payload(parsed)
        normalized = coerce_preview_content_payload(normalized)
        content_model = AdaptiveChapterVariantContent.model_validate(normalized)
        variant = build_variant_from_content(
            content=content_model,
            level=level,
            chapter_source_id=chapter_source_id,
            chapter_title=chapter.title,
            source_block_ids=source_ids_from_sources(compact_sources),
            source_digest=source_digest,
            model_name=main_response.model_name,
        )
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AIProviderError(f"Ollama JSON is invalid after normalization: {exc}") from exc

    content = variant.model_dump(mode="json")
    content["generation_method"] = "ai_preview"
    content["guided_example"] = parsed.get("guided_example") or content.get("guided_example")
    content["learning_support"] = parsed.get("learning_support") or content.get("learning_support")
    content["practice_question"] = parsed.get("practice_question") or content.get("practice_question", {}).get("question", "")
    content["expected_answer"] = parsed.get("expected_answer") or content.get("practice_question", {}).get("expected_answer", "")
    content["correction"] = parsed.get("correction") or content.get("practice_question", {}).get("explanation", "")
    content["blocks"] = [
        {**block, "generation_method": "ai_preview"}
        for block in content.get("blocks", [])
        if isinstance(block, dict)
    ]
    content = localize_preview_labels(content)
    validation_errors = validate_preview_content(content, compact_sources)

    metrics = merge_ollama_metrics(provider, main_response, pedagogy_response)
    metrics["ollama_host"] = OLLAMA_HOST
    metrics["source_hash"] = source_digest
    metrics["validation_errors"] = validation_errors
    metrics["json_valid"] = True
    metrics["schema_valid"] = True

    return {
        "provider": "ollama",
        "model": main_response.model_name,
        "execution": "local",
        "generation_method": "ai_preview",
        "validation_status": "valid" if not validation_errors else "rejected",
        "content": content,
        "validation_errors": validation_errors,
        "metrics": metrics,
        "reference": {
            "course_level_variant_id": reference.id,
            "generation_method": reference.generation_method,
            "source_hash": reference.source_hash,
            "read_only": True,
        },
    }


def generate_ollama_preview_sections(
    provider: OllamaProvider,
    user_payload: dict[str, Any],
    level: str,
):
    main_response = generate_ollama_section(
        provider=provider,
        schema=OLLAMA_MAIN_SCHEMA,
        section_name="contenu principal",
        system_prompt=build_ollama_section_prompt(
            level=level,
            schema=OLLAMA_MAIN_SCHEMA,
            task_lines=[
                "Genere uniquement summary, explanation, key_points et vocabulary.",
                "summary contient au moins 80 mots et raconte seulement les faits du chapitre.",
                "explanation contient au moins 140 mots et explique les notions sans repeter le resume.",
                "Aucune phrase de summary ne doit etre identique ou presque identique a une phrase de explanation.",
                "vocabulary contient obligatoirement exactement ces 5 termes: Msid, impasse, incipit, focalisation interne, imparfait iteratif.",
                "Definition obligatoire de Focalisation interne: narration ou le lecteur decouvre les evenements a travers les perceptions d'un personnage.",
                "Definition obligatoire de Imparfait iteratif: imparfait qui exprime une action repetee ou habituelle dans le passe.",
                "Definition obligatoire de Incipit: debut d'une oeuvre ou d'un recit.",
            ],
        ),
        user_payload=user_payload,
        max_tokens=1400,
    )
    main_payload = parse_ollama_section(main_response.text, OLLAMA_MAIN_SCHEMA)

    pedagogy_payload = {
        **user_payload,
        "main_content_already_generated": main_payload,
    }
    pedagogy_response = generate_ollama_section(
        provider=provider,
        schema=OLLAMA_PEDAGOGY_SCHEMA,
        section_name="pedagogie",
        system_prompt=build_ollama_section_prompt(
            level=level,
            schema=OLLAMA_PEDAGOGY_SCHEMA,
            task_lines=[
                "Genere uniquement guided_example, learning_support, practice_question, expected_answer et correction.",
                "guided_example explique une sequence du chapitre avec des etapes simples.",
                "learning_support est une liste d'etapes courtes et claires en francais.",
                "practice_question, expected_answer et correction ont trois formulations differentes.",
                "expected_answer est une reponse courte attendue.",
                "correction est une explication detaillee qui justifie la reponse et rappelle le passage utile; elle ne recopie pas expected_answer.",
            ],
        ),
        user_payload=pedagogy_payload,
        max_tokens=1100,
    )
    pedagogy = parse_ollama_section(pedagogy_response.text, OLLAMA_PEDAGOGY_SCHEMA)
    return main_response, pedagogy_response, main_payload | pedagogy


def build_ollama_section_prompt(*, level: str, schema: dict[str, Any], task_lines: list[str]) -> str:
    return "\n".join(
        [
            adaptive_course_variant_level_prompt("Francais", level),
            "Tu reponds avec un seul objet JSON valide conforme exactement au JSON Schema ci-dessous.",
            "N'ajoute aucun texte avant ou apres le JSON. N'utilise pas de bloc Markdown.",
            "Schema attendu:",
            json.dumps(schema, ensure_ascii=False),
            "Contraintes pedagogiques et factuelles:",
            "Utilise strictement les sources reelles fournies et le contexte source de reference.",
            "Interdiction d'utiliser une information absente des sources.",
            "Le Msid est une ecole coranique, pas une piece de la maison.",
            "Une impasse est une rue ou un passage sans issue.",
            "Le chapitre 1 est l'incipit du roman, pas la fin de l'histoire.",
            "N'invente jamais l'expression ouverture de la tristesse.",
            "Si tu mentionnes une figure de style, nomme-la et explique son effet.",
            "Aucun mot anglais dans les valeurs JSON.",
            "N'ecris jamais deux phrases identiques ou presque identiques entre summary et explanation.",
            *task_lines,
        ]
    )


def generate_ollama_section(
    *,
    provider: OllamaProvider,
    schema: dict[str, Any],
    section_name: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    max_tokens: int,
):
    request = AIRequest(
        system_prompt=system_prompt,
        user_prompt=json.dumps(user_payload, ensure_ascii=False),
        response_schema=schema,
        temperature=0,
        max_tokens=max_tokens,
        timeout_seconds=600,
        model_name=OLLAMA_MODEL,
        metadata={
            "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
            "preview_only": True,
            "section": section_name,
        },
    )
    try:
        return provider.generate_structured(request)
    except AIProviderError as exc:
        if "invalid JSON" not in str(exc):
            raise
        retry_request = AIRequest(
            system_prompt="\n".join(
                [
                    "Reponds avec un seul objet JSON valide, sans Markdown.",
                    "Respecte exactement ce JSON Schema:",
                    json.dumps(schema, ensure_ascii=False),
                    "Utilise uniquement les sources fournies. Francais simple. Aucun mot anglais.",
                ]
            ),
            user_prompt=json.dumps(
                {
                    "chapter_title": user_payload.get("chapter_title"),
                    "level": user_payload.get("level"),
                    "sources": user_payload.get("sources"),
                    "allowed_facts": user_payload.get("allowed_facts"),
                    "task": section_name,
                },
                ensure_ascii=False,
            ),
            response_schema=schema,
            temperature=0,
            max_tokens=max_tokens,
            timeout_seconds=600,
            model_name=OLLAMA_MODEL,
            metadata={
                "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
                "preview_only": True,
                "section": section_name,
                "retry": True,
            },
        )
        return provider.generate_structured(retry_request)


def parse_ollama_section(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    parsed = load_json_object_response(text)
    validate_schema_completeness(parsed, schema)
    return parsed


def validate_schema_completeness(payload: Any, schema: dict[str, Any], path: str = "content") -> None:
    if schema.get("type") == "object":
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must be an object")
        extra_keys = set(payload) - set(schema.get("properties") or {})
        if extra_keys:
            raise ValueError(f"{path} contains unexpected keys: {sorted(extra_keys)}")
        for key in schema.get("required") or []:
            if key not in payload:
                raise ValueError(f"{path}.{key} is missing")
            validate_schema_completeness(payload[key], schema["properties"][key], f"{path}.{key}")
        return
    if schema.get("type") == "array":
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"{path} must be a non-empty array")
        item_schema = schema.get("items") or {}
        for index, item in enumerate(payload):
            validate_schema_completeness(item, item_schema, f"{path}[{index}]")
        return
    if schema.get("type") == "string":
        if not isinstance(payload, str) or not payload.strip():
            raise ValueError(f"{path} must be a non-empty string")


def merge_ollama_metrics(provider: OllamaProvider, main_response, pedagogy_response) -> dict[str, Any]:
    main_metrics = provider.get_usage_metadata(main_response) | main_response.usage
    pedagogy_metrics = provider.get_usage_metadata(pedagogy_response) | pedagogy_response.usage
    total_fields = {
        "prompt_eval_count",
        "eval_count",
        "load_duration",
        "prompt_eval_duration",
        "eval_duration",
        "total_duration",
        "duration_ms",
    }
    merged = {
        key: sum(int(metrics.get(key) or 0) for metrics in (main_metrics, pedagogy_metrics))
        for key in total_fields
    }
    merged["main_call"] = main_metrics
    merged["pedagogy_call"] = pedagogy_metrics
    return merged


def build_chapter_sources(chapter: CourseChapter, chapter_source_id: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    structured = chapter.structured_content or []
    if isinstance(structured, dict):
        structured = structured.get("blocks") or structured.get("source_blocks") or []
    if isinstance(structured, list):
        for index, block in enumerate(structured, start=1):
            if not isinstance(block, dict):
                continue
            text = block.get("text") or block.get("content") or block.get("summary") or ""
            if not text:
                continue
            source_block_id = str(block.get("source_block_id") or block.get("id") or f"{chapter_source_id}_block_{index}")
            metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else {}
            sources.append(
                {
                    "id": source_block_id,
                    "source_block_id": source_block_id,
                    "source_chapter_id": chapter_source_id,
                    "type": block.get("type") or "paragraph",
                    "section": block.get("section") or metadata.get("section") or "",
                    "text": text,
                }
            )
    if chapter.content:
        sources.append(
            {
                "id": f"{chapter_source_id}_content",
                "source_block_id": f"{chapter_source_id}_content",
                "source_chapter_id": chapter_source_id,
                "type": "paragraph",
                "section": "chapter_content",
                "text": chapter.content,
            }
        )
    return sources


def extract_reference_chapter_context(reference: CourseLevelVariant, chapter_source_id: str) -> dict[str, Any]:
    content = reference.structured_content if isinstance(reference.structured_content, list) else []
    chapter_payload = next(
        (
            item for item in content
            if isinstance(item, dict)
            and (item.get("chapter_source_id") == chapter_source_id or item.get("source_chapter_id") == chapter_source_id)
        ),
        {},
    )
    source_block_ids = [
        str(item)
        for item in chapter_payload.get("source_block_ids") or []
        if str(item).strip()
    ]
    return {
        "course_level_variant_id": reference.id,
        "chapter_source_id": chapter_source_id,
        "source_block_ids": source_block_ids,
        "title": chapter_payload.get("title") or "",
        "summary": chapter_payload.get("summary") or "",
        "key_points": chapter_payload.get("key_points") or [],
    }


def align_sources_with_reference_context(sources: list[dict[str, Any]], reference_context: dict[str, Any]) -> list[dict[str, Any]]:
    reference_ids = [str(item) for item in reference_context.get("source_block_ids") or []]
    if not reference_ids:
        return sources

    by_id = {
        str(source.get("source_block_id") or source.get("id")): source
        for source in sources
    }
    selected = [by_id[source_id] for source_id in reference_ids if source_id in by_id]
    if not selected:
        return sources

    selected_ids = {str(source.get("source_block_id") or source.get("id")) for source in selected}
    remaining = [source for source in sources if str(source.get("source_block_id") or source.get("id")) not in selected_ids]
    return selected + remaining


def coerce_preview_content_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: payload.get(key) for key in AdaptiveChapterVariantContent.model_fields if key in payload}
    if "practice_question" not in normalized and payload.get("practice_question"):
        normalized["practice_question"] = payload.get("practice_question")
    if isinstance(normalized.get("practice_question"), str):
        normalized["practice_question"] = {
            "question": normalized.get("practice_question"),
            "instruction": "Reponds avec des mots simples en t'appuyant sur le chapitre.",
            "difficulty": "debutant",
            "expected_answer": payload.get("expected_answer") or "",
            "explanation": payload.get("correction") or payload.get("expected_answer") or "",
        }
    elif isinstance(normalized.get("practice_question"), dict):
        question = dict(normalized["practice_question"])
        question.setdefault("instruction", "Reponds avec des mots simples en t'appuyant sur le chapitre.")
        question.setdefault("difficulty", "debutant")
        question.setdefault("expected_answer", payload.get("expected_answer") or "")
        question.setdefault("explanation", payload.get("correction") or question.get("expected_answer") or "")
        normalized["practice_question"] = question

    support = normalized.get("learning_support")
    if isinstance(support, list):
        items = [str(item).strip() for item in support if str(item).strip()]
        normalized["learning_support"] = {
            "method": items[0] if items else "Relis le chapitre et repere les personnages, les lieux et les sentiments.",
            "steps": items[1:4],
            "pitfalls": items[4:6],
            "memory_tip": items[6] if len(items) > 6 else "Associe Dar Chouafa a la solitude et la Boite a Merveilles au refuge imaginaire.",
        }
    elif isinstance(support, str):
        normalized["learning_support"] = {
            "method": support,
            "steps": [],
            "pitfalls": [],
            "memory_tip": "Associe chaque idee importante a un exemple precis du chapitre.",
        }

    guided = normalized.get("guided_example")
    if isinstance(guided, str):
        normalized["guided_example"] = {
            "title": "Exemple guide",
            "instruction": "Observe comment la reponse reste liee au chapitre.",
            "content": guided,
            "steps": [],
            "answer": "",
        }
    elif isinstance(guided, dict):
        example = dict(guided)
        example.setdefault("title", "Exemple guide")
        example.setdefault("instruction", "Observe comment la reponse reste liee au chapitre.")
        if not example.get("content"):
            example["content"] = " ".join(str(item) for item in example.get("steps") or []) or example.get("answer") or ""
        example.setdefault("steps", [])
        example.setdefault("answer", "")
        normalized["guided_example"] = example

    normalized.setdefault("blocks", [])
    return normalized


def localize_preview_labels(content: dict[str, Any]) -> dict[str, Any]:
    replacements = {
        "Pitfall": "Attention",
        "pitfall": "attention",
        "Step": "Etape",
        "step": "etape",
        "Method": "Methode",
        "method": "methode",
        "Memory Tip": "Astuce de memorisation",
        "memory tip": "astuce de memorisation",
        "Key point": "Point important",
        "key point": "point important",
    }

    def replace_value(value: Any) -> Any:
        if isinstance(value, str):
            result = value
            for source, target in replacements.items():
                result = result.replace(source, target)
            return result.strip()
        if isinstance(value, list):
            return [replace_value(item) for item in value]
        if isinstance(value, dict):
            return {key: replace_value(item) for key, item in value.items()}
        return value

    return replace_value(content)


def validate_preview_content(content: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if adaptive_word_count(content.get("summary")) < 80:
        errors.append("summary must contain at least 80 words")
    if adaptive_word_count(content.get("explanation")) < 140:
        errors.append("explanation must contain at least 140 words")

    key_points = [item for item in content.get("key_points") or [] if str(item).strip()]
    if not 4 <= len(key_points) <= 6:
        errors.append("key_points count must be between 4 and 6")

    vocabulary = [
        item for item in content.get("vocabulary") or []
        if isinstance(item, dict)
        and str(item.get("term") or "").strip()
        and adaptive_word_count(item.get("definition")) >= 5
    ]
    if not 4 <= len(vocabulary) <= 6:
        errors.append("vocabulary count must be between 4 and 6")

    literary_text = " ".join(
        [
            str(content.get("explanation") or ""),
            " ".join(str(item.get("term") or "") for item in content.get("vocabulary") or [] if isinstance(item, dict)),
            " ".join(str(item.get("definition") or "") for item in content.get("vocabulary") or [] if isinstance(item, dict)),
        ]
    )
    literary_text = normalize_for_validation(literary_text)
    literary_terms = (
        "narrateur",
        "incipit",
        "point de vue",
        "focalisation interne",
        "imparfait iteratif",
        "merveilleux",
        "reel",
        "realite",
    )
    if sum(1 for term in literary_terms if term in literary_text) < 3:
        errors.append("literary terms are not explained")

    grounded_text = json.dumps(content, ensure_ascii=False).lower()
    grounded_terms = ("sidi mohammed", "dar chouafa", "lalla zoubida", "rahma", "boîte", "boite", "merveilles", "solitude")
    if sum(1 for term in grounded_terms if term in grounded_text) < 5:
        errors.append("content is not sufficiently grounded in chapter sources")
    source_text = normalize_for_validation(" ".join(str(source.get("text") or "") for source in sources))
    errors.extend(validate_no_empty_fields(content))
    errors.extend(validate_no_english_values(content))
    errors.extend(validate_repetition(content))
    errors.extend(validate_required_vocabulary(content))
    errors.extend(validate_factual_contradictions(content))
    errors.extend(validate_source_exclusivity(content, source_text))
    return errors


def validate_no_empty_fields(value: Any, path: str = "content") -> list[str]:
    errors: list[str] = []
    if isinstance(value, str):
        if not value.strip():
            errors.append(f"{path} is empty")
    elif isinstance(value, list):
        if not value:
            errors.append(f"{path} is empty")
        for index, item in enumerate(value):
            errors.extend(validate_no_empty_fields(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"blocks", "source_block_ids", "expected_elements", "answer"}:
                continue
            errors.extend(validate_no_empty_fields(item, f"{path}.{key}"))
    return errors


def validate_no_english_values(content: dict[str, Any]) -> list[str]:
    text = normalize_for_validation(" ".join(preview_text_values(content)))
    english_markers = (
        "pitfall", "pitfalls", "step 1", "step 2", "method :", "memory tip",
        "key point", "summary", "explanation", "expected answer",
    )
    return [f"english marker found: {marker}" for marker in english_markers if marker in text]


def validate_repetition(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    summary = normalize_for_validation(content.get("summary") or "")
    explanation = normalize_for_validation(content.get("explanation") or "")
    practice = content.get("practice_question")
    question = normalize_for_validation(practice.get("question") if isinstance(practice, dict) else practice)
    answer = normalize_for_validation(content.get("expected_answer") or "")
    correction = normalize_for_validation(content.get("correction") or "")
    if summary and explanation and SequenceMatcher(None, summary, explanation).ratio() > 0.72:
        errors.append("summary and explanation are too repetitive")
    if question and answer and SequenceMatcher(None, question, answer).ratio() > 0.62:
        errors.append("practice question and expected answer are too repetitive")
    if answer and correction and SequenceMatcher(None, answer, correction).ratio() > 0.82:
        errors.append("expected answer and correction are too repetitive")
    repeated_sentences = find_repeated_sentences(content)
    if repeated_sentences:
        errors.append("repeated sentence found: " + repeated_sentences[0][:80])
    return errors


def validate_required_vocabulary(content: dict[str, Any]) -> list[str]:
    vocab = {
        normalize_for_validation(item.get("term")): normalize_for_validation(item.get("definition"))
        for item in content.get("vocabulary") or []
        if isinstance(item, dict)
    }
    all_text = normalize_for_validation(" ".join(preview_text_values(content)))
    errors: list[str] = []
    required_terms = {
        "msid": "Msid vocabulary definition must say it is an ecole coranique",
        "impasse": "Impasse vocabulary definition must mention a rue or passage sans issue",
        "incipit": "Incipit vocabulary definition must explain it is the beginning of a work",
        "focalisation": "Focalisation interne vocabulary definition is missing",
        "imparfait": "Imparfait iteratif vocabulary definition is missing",
    }
    for term, message in required_terms.items():
        if not any(term in vocab_term for vocab_term in vocab):
            errors.append(message)
    if "msid" in all_text and not any("msid" in term and "ecole coranique" in definition for term, definition in vocab.items()):
        errors.append("Msid vocabulary definition must say it is an ecole coranique")
    if "impasse" in all_text and not any("impasse" in term and ("sans issue" in definition or "rue" in definition or "passage" in definition) for term, definition in vocab.items()):
        errors.append("Impasse vocabulary definition must mention a rue or passage sans issue")
    if "incipit" in all_text and not any("incipit" in term and ("debut" in definition or "commencement" in definition) for term, definition in vocab.items()):
        errors.append("Incipit vocabulary definition must explain it is the beginning of a work")
    if "focalisation interne" in all_text and not any("focalisation" in term and ("point de vue" in definition or "percoit" in definition or "perceptions" in definition or "personnage" in definition) for term, definition in vocab.items()):
        errors.append("Focalisation interne vocabulary definition is missing or incorrect")
    if "imparfait iteratif" in all_text and not any("imparfait" in term and ("repete" in definition or "repetee" in definition or "habituelle" in definition or "habitude" in definition) for term, definition in vocab.items()):
        errors.append("Imparfait iteratif vocabulary definition is missing or incorrect")
    if "incipient" in all_text:
        errors.append("Invalid vocabulary term: Incipient instead of incipit")
    return errors


def validate_factual_contradictions(content: dict[str, Any]) -> list[str]:
    text = normalize_for_validation(" ".join(preview_text_values(content)))
    errors: list[str] = []
    msid_patterns = (
        r"msid.{0,30}(est|represente|designe|constitue).{0,30}(piece|chambre|salle).{0,45}(maison|dar chouafa)",
        r"(piece|chambre|salle).{0,45}(maison|dar chouafa).{0,30}(appelee|nommee|est).{0,30}msid",
    )
    if has_msid_room_contradiction(text, msid_patterns):
        errors.append("fact contradiction: Msid is not a room of the house")
    if re.search(r"chapitre 1.{0,60}(fin de l histoire|fin du roman|fin de l oeuvre)", text):
        errors.append("fact contradiction: chapter 1 is not the end of the story")
    if "ouverture de la tristesse" in text:
        errors.append("invented expression: ouverture de la tristesse")
    if "figure de style" in text:
        known_figures = ("comparaison", "metaphore", "personnification", "hyperbole", "enumeration", "antithese")
        if not any(figure in text for figure in known_figures):
            errors.append("figure de style mentioned without naming a precise device")
        if "effet" not in text and "montre" not in text and "souligne" not in text:
            errors.append("figure de style mentioned without explaining its effect")
    return errors


def has_msid_room_contradiction(text: str, patterns: tuple[str, ...]) -> bool:
    negated_patterns = (
        r"msid.{0,20}(n est pas|nest pas|ne represente pas|ne designe pas).{0,30}(piece|chambre|salle)",
        r"msid.{0,40}pas.{0,20}(piece|chambre|salle).{0,45}(maison|dar chouafa)",
    )
    if any(re.search(pattern, text) for pattern in negated_patterns):
        return False
    return any(re.search(pattern, text) for pattern in patterns)


def validate_source_exclusivity(content: dict[str, Any], source_text: str) -> list[str]:
    raw_text = ". ".join(preview_text_values(content))
    proper_names = set(re.findall(r"\b[A-ZÉÈÀÂÎÔÛÄËÏÖÜÇ][\wÀ-ÿ'-]+(?:\s+[A-ZÉÈÀÂÎÔÛÄËÏÖÜÇ][\wÀ-ÿ'-]+)*", raw_text))
    invented = [
        name for name in proper_names
        if is_suspicious_entity_name(strip_entity_leading_words(name))
        and normalize_for_validation(strip_entity_leading_words(name)) not in source_text
    ]
    if invented:
        return ["possible invented proper name absent from sources: " + ", ".join(sorted(set(invented))[:5])]
    return []


def strip_entity_leading_words(name: str) -> str:
    return re.sub(r"^(Le|La|Les|Un|Une|Des|Ce|Cette|Ces|L')\s+", "", name).strip()


def is_suspicious_entity_name(name: str) -> bool:
    normalized = normalize_for_validation(name)
    common_capitalized_words = {
        "analysez",
        "cela",
        "comprendre",
        "identifiez",
        "interpretation",
        "le",
        "la",
        "les",
        "dans",
        "pour",
        "au",
        "cette",
        "ce",
        "il",
        "elle",
        "chapitre",
        "correction",
        "reponse",
        "question",
        "resume",
        "explication",
        "vocabulaire",
        "methode",
        "etape",
        "astuce",
        "attention",
        "associe",
        "debut",
        "point",
        "observe",
        "introduction",
        "quel",
        "baigne",
        "l'incipit",
    }
    if normalized in common_capitalized_words:
        return False

    words = [word for word in re.split(r"\s+", name.strip()) if word]
    if len(words) >= 2:
        return True

    return False


def preview_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(preview_text_values(item))
        return values
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            if key in {"blocks", "source_block_ids", "expected_elements", "answer"}:
                continue
            values.extend(preview_text_values(item))
        return values
    return []


def find_repeated_sentences(content: dict[str, Any]) -> list[str]:
    text = " ".join(preview_text_values(content))
    sentences = [
        normalize_for_validation(sentence)
        for sentence in re.split(r"[.!?]\s+", text)
        if adaptive_word_count(sentence) >= 8
    ]
    seen: set[str] = set()
    repeated: list[str] = []
    for sentence in sentences:
        if sentence in seen:
            repeated.append(sentence)
        seen.add(sentence)
    return repeated


def normalize_for_validation(value: Any) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
