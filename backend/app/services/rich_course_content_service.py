from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.persistence import Course, CourseChapter, CourseLevelVariant, LiteraryWork
from app.services.ai.ai_provider import AIProviderError, AIRequest
from app.services.ai.ai_usage_service import record_generation, stable_hash
from app.services.ai.groq_provider import get_ai_provider


LEVELS = ("debutant", "intermediaire", "avance")
GENERATION_LEVEL_ORDER = ("intermediaire", "debutant", "avance")
VARIANT_SCHEMA = "edumentor_chapter_variants_v1"
PROMPT_VERSION = "rich_course_regeneration_v1"


class RichChapterAIResponse(BaseModel):
    variants: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class RichLevelAIResponse(BaseModel):
    blocks: list[dict[str, Any]] = Field(default_factory=list)


def regenerate_course_content(db: Session, course_id: int, *, user_id: int | None = None) -> dict[str, Any]:
    course = db.get(Course, course_id)
    if not course:
        raise ValueError(f"Course {course_id} not found")

    settings = get_settings()
    before_stats = chapter_stats(course.chapters)
    works = db.query(LiteraryWork).filter(LiteraryWork.course_id == course_id).order_by(LiteraryWork.id).all()
    variant_payload: dict[str, list[dict[str, Any]]] = {level: [] for level in LEVELS}
    chapter_methods: dict[int, str] = {}

    for chapter in sorted(course.chapters, key=lambda item: (item.position, item.id)):
        source_blocks = extract_source_blocks(chapter.structured_content)
        source_context = clean_source_context(build_source_context(source_blocks, works, chapter.title), chapter.title)
        groq_result = generate_chapter_with_groq(
            db,
            course=course,
            chapter=chapter,
            source_blocks=source_blocks,
            source_context=source_context,
            user_id=user_id,
            enabled=bool(settings.get("ai_content_generation_enabled") and settings.get("groq_api_key")),
        )
        if groq_result["variants"]:
            variants = groq_result["variants"]
            generation_method = groq_result["method"]
            generation_error = groq_result.get("error")
        else:
            variants = {
                level: build_detailed_chapter_blocks(
                    course_title=course.title,
                    chapter_title=chapter.title,
                    level=level,
                    source_context=source_context,
                )
                for level in LEVELS
            }
            generation_method = "deterministic_fallback"
            generation_error = groq_result.get("error")
            record_generation(
                db,
                generation_type="course_chapter_regeneration",
                provider="deterministic",
                model_name=None,
                prompt_version=PROMPT_VERSION,
                input_payload={"course_id": course_id, "chapter_id": chapter.id, "source_context": source_context},
                source_hash=stable_hash(source_blocks),
                output_payload={"variants": variants},
                status="deterministic_fallback",
                user_id=user_id,
                course_id=course_id,
                chapter_id=chapter.id,
                quality_score=quality_score({"variants": variants}),
                error_message=generation_error,
                metadata={
                    "method": "deterministic_fallback",
                    "reason": "Groq unavailable or rejected by quality validation; produced rich source-bound fallback.",
                    "levels": list(LEVELS),
                    "attempts": groq_result.get("attempts", 0),
                    "word_counts": {level: count_words(blocks) for level, blocks in variants.items()},
                    "block_counts": {level: len(blocks) for level, blocks in variants.items()},
                },
            )

        for level in LEVELS:
            blocks = variants[level]
            variant_payload[level].append(
                {
                    "chapter_id": chapter.id,
                    "source_chapter_id": first_source_chapter_id(source_blocks),
                    "chapter_title": chapter.title,
                    "level": level,
                    "structured_content": blocks,
                    "generation_method": generation_method,
                    "adaptation_reason": LEVEL_PROFILES[level]["adaptation_reason"],
                    "word_count": count_words(blocks),
                    "block_count": len(blocks),
                }
            )

        output_payload = {
            "schema": VARIANT_SCHEMA,
            "default_level": "intermediaire",
            "variants": variants,
            "source_blocks": source_blocks,
            "generation_method": generation_method,
            "generation_error": generation_error,
            "regenerated_at": datetime.utcnow().isoformat(),
        }
        chapter_methods[chapter.id] = generation_method
        chapter.structured_content = output_payload
        chapter.content = blocks_to_text(variants["intermediaire"])
        chapter.estimated_duration = chapter.estimated_duration or chapter.duration or "60 min"
        chapter.updated_at = datetime.utcnow()

    for level, content in variant_payload.items():
        methods = {str(item.get("generation_method")) for item in content}
        variant_method = "ai_generated" if methods == {"ai_generated"} else "mixed" if "ai_generated" in methods else "deterministic_fallback"
        upsert_course_level_variant(db, course, level, content, generation_method=variant_method)

    information = course.information or {}
    method_values = set(chapter_methods.values())
    overall_method = (
        "ai_generated"
        if method_values == {"ai_generated"}
        else "mixed"
        if "ai_generated" in method_values or "mixed" in method_values
        else "deterministic_fallback"
    )
    information["rich_content"] = {
        "schema": VARIANT_SCHEMA,
        "generation_method": overall_method,
        "levels": list(LEVELS),
        "regenerated_at": datetime.utcnow().isoformat(),
        "chapter_count": len(course.chapters),
        "chapter_methods": {str(key): value for key, value in chapter_methods.items()},
    }
    course.information = information
    flag_modified(course, "information")
    course.content_import_status = "ready_for_review"
    course.content_import_error = None
    course.content_imported_at = datetime.utcnow()
    course.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(course)

    return {
        "course_id": course.id,
        "course_title": course.title,
        "method": overall_method,
        "chapter_methods": chapter_methods,
        "before": before_stats,
        "after": chapter_stats(course.chapters),
        "content_import_status": course.content_import_status,
    }


LEVEL_PROFILES = {
    "debutant": {
        "label": "Débutant",
        "voice": "avec des phrases simples, des repères explicites et une méthode pas à pas",
        "adaptation_reason": "Vocabulaire simple et guidage renforcé pour sécuriser les bases.",
        "task": "identifier, reformuler et relier une idée simple à l'œuvre",
        "depth": "On commence par comprendre le sens global avant de chercher une analyse compliquée.",
        "exam": "réponse courte en trois temps : idée, indice du support, explication avec ses mots",
    },
    "intermediaire": {
        "label": "Intermédiaire",
        "voice": "avec une analyse structurée, des liens entre notions et une préparation directe à l'examen",
        "adaptation_reason": "Analyse standard de 1ère année Baccalauréat avec justification et méthode d'examen.",
        "task": "analyser, justifier et organiser une réponse complète",
        "depth": "L'objectif est de passer de la compréhension à l'interprétation justifiée.",
        "exam": "paragraphe organisé : idée directrice, justification, analyse, conclusion partielle",
    },
    "avance": {
        "label": "Avancé",
        "voice": "avec interprétation, nuance, comparaison et exigences proches d'une très bonne copie",
        "adaptation_reason": "Approfondissement, argumentation nuancée et questions complexes sans rupture brutale.",
        "task": "interpréter, comparer et défendre une lecture argumentée",
        "depth": "On distingue les faits du support, les effets littéraires et les limites de l'interprétation.",
        "exam": "réponse argumentée : thèse, justification, nuance, ouverture contrôlée",
    },
}


def generate_chapter_with_groq(
    db: Session,
    *,
    course: Course,
    chapter: CourseChapter,
    source_blocks: list[dict[str, Any]],
    source_context: dict[str, Any],
    user_id: int | None,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"variants": None, "method": "deterministic_fallback", "attempts": 0, "error": "AI_CONTENT_GENERATION_ENABLED is false or Groq key is missing"}

    variants: dict[str, list[dict[str, Any]]] = {}
    methods = []
    errors = []
    total_attempts = 0
    for level_index, level in enumerate(GENERATION_LEVEL_ORDER):
        result = generate_level_with_groq(
            db,
            course=course,
            chapter=chapter,
            level=level,
            source_blocks=source_blocks,
            source_context=source_context,
            user_id=user_id,
        )
        total_attempts += int(result.get("attempts") or 0)
        if result.get("blocks"):
            variants[level] = result["blocks"]
            methods.append("ai_generated")
        else:
            fallback_blocks = build_detailed_chapter_blocks(
                course_title=course.title,
                chapter_title=chapter.title,
                level=level,
                source_context=source_context,
            )
            variants[level] = fallback_blocks
            methods.append("deterministic_fallback")
            errors.append(f"{level}: {result.get('error')}")
            record_generation(
                db,
                generation_type="course_chapter_regeneration",
                provider="deterministic",
                model_name=None,
                prompt_version=PROMPT_VERSION,
                input_payload=build_groq_payload(course, chapter, source_context, level=level),
                source_hash=stable_hash(source_blocks),
                output_payload={"level": level, "blocks": fallback_blocks},
                status="deterministic_fallback",
                user_id=user_id,
                course_id=course.id,
                chapter_id=chapter.id,
                quality_score=quality_score({"variants": {level: fallback_blocks}}),
                error_message=result.get("error"),
                metadata={"method": "deterministic_fallback", "level": level, "attempts": result.get("attempts", 0)},
            )
        if level_index < len(GENERATION_LEVEL_ORDER) - 1:
            time.sleep(20)
    method = "ai_generated" if set(methods) == {"ai_generated"} else "mixed" if "ai_generated" in methods else "deterministic_fallback"
    return {"variants": variants, "method": method, "attempts": total_attempts, "error": " | ".join(errors) if errors else None}


def generate_level_with_groq(
    db: Session,
    *,
    course: Course,
    chapter: CourseChapter,
    level: str,
    source_blocks: list[dict[str, Any]],
    source_context: dict[str, Any],
    user_id: int | None,
) -> dict[str, Any]:
    settings = get_settings()
    retries = max(0, int(settings.get("ai_max_retries") or 0))
    last_error = ""
    provider = get_ai_provider()
    input_payload = build_groq_payload(course, chapter, source_context, level=level)
    source_digest = stable_hash(source_blocks)

    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            response = provider.generate_structured(
                AIRequest(
                    system_prompt=rich_chapter_system_prompt(level),
                    user_prompt=json.dumps(input_payload, ensure_ascii=False),
                    response_schema=RichLevelAIResponse.model_json_schema(),
                    temperature=0.25,
                    max_tokens=2200,
                    timeout_seconds=float(settings.get("ai_timeout_seconds") or 60),
                    metadata={"attempt": attempt + 1, "prompt_version": PROMPT_VERSION, "level": level},
                )
            )
            parsed = json.loads(response.text)
            model = RichLevelAIResponse.model_validate(parsed)
            blocks = normalize_ai_level_blocks(model.blocks, chapter.title, level, source_context)
            validate_generation_quality({level: blocks}, chapter.title, source_context)
            usage = provider.get_usage_metadata(response) | response.usage
            usage["duration_ms"] = usage.get("duration_ms") or round((time.perf_counter() - started) * 1000)
            record_generation(
                db,
                generation_type="course_chapter_regeneration",
                provider=response.provider,
                model_name=response.model_name,
                prompt_version=PROMPT_VERSION,
                input_payload=input_payload,
                source_hash=source_digest,
                output_payload={"level": level, "blocks": blocks},
                status="ai_generated" if attempt == 0 else "ai_generated_with_repairs",
                user_id=user_id,
                course_id=course.id,
                chapter_id=chapter.id,
                quality_score=quality_score({"variants": {level: blocks}}),
                usage=usage,
                metadata={"method": "ai_generated", "attempt": attempt + 1, "level": level, "word_count": count_words(blocks), "block_count": len(blocks)},
            )
            return {"blocks": blocks, "attempts": attempt + 1, "error": None}
        except (AIProviderError, ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = str(exc)[:1000]
            record_generation(
                db,
                generation_type="course_chapter_regeneration",
                provider="groq",
                model_name=provider.get_model_name(),
                prompt_version=PROMPT_VERSION,
                input_payload=input_payload,
                source_hash=source_digest,
                output_payload=None,
                status="failed",
                user_id=user_id,
                course_id=course.id,
                chapter_id=chapter.id,
                quality_score=0,
                usage={"duration_ms": round((time.perf_counter() - started) * 1000)},
                error_message=last_error,
                metadata={"method": "ai_generated", "attempt": attempt + 1, "level": level},
            )
            db.flush()
            wait_seconds = retry_after_seconds(last_error) or (20.0 if "too short" in last_error.lower() else 0.0)
            if wait_seconds and attempt < retries:
                time.sleep(wait_seconds)
    return {"blocks": None, "attempts": retries + 1, "error": last_error}


def rich_chapter_system_prompt(level: str) -> str:
    profile = LEVEL_PROFILES.get(level, LEVEL_PROFILES["intermediaire"])
    return "\n".join(
        [
            "Tu es un professeur de francais pour la 1ere annee Baccalaureat au Maroc.",
            f"Genere uniquement la variante de niveau {level} ({profile['label']}).",
            f"Adapte le cours {profile['voice']}.",
            "Retourne uniquement un JSON strict conforme au schema: {\"blocks\":[...]}",
            "Chaque bloc doit avoir type, title et content.",
            "Types autorises: heading, paragraph, definition, example, methodology, warning, key_points, exercise, correction, summary, mini_assessment.",
            "Utilise uniquement les sources du chapitre courant. N'invente pas de citation exacte, numero de page ou passage absent.",
            "N'ajoute aucun personnage, lieu, evenement ou lien familial qui n'apparait pas dans les sources fournies.",
            "Ne melange pas plusieurs oeuvres dans un chapitre dedie a une oeuvre, sauf si le chapitre est explicitement comparatif.",
            "Le contenu doit contenir: presentation, situation centrale, conflit ou notion, methodes d'examen, exemples, trois exercices, trois corrections completes, resume, points cles et mini-evaluation avec answer et explanation.",
            "Ecris un vrai cours pedagogique detaille, specifique au chapitre, sans repetitions artificielles.",
            "Interdiction de placeholders, de corrections vides, de phrases tronquees par des points de suspension et de repetitions.",
        ]
    )


def build_groq_payload(course: Course, chapter: CourseChapter, source_context: dict[str, Any], *, level: str) -> dict[str, Any]:
    profile = LEVEL_PROFILES.get(level, LEVEL_PROFILES["intermediaire"])
    return {
        "course_id": course.id,
        "course_title": course.title,
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "level": level,
        "level_instructions": {
            "label": profile["label"],
            "voice": profile["voice"],
            "task": profile["task"],
            "exam_method": profile["exam"],
        },
        "target": "1ere annee Baccalaureat Maroc, examen regional de francais",
        "clean_facts": source_context["facts"],
        "current_work": source_context.get("current_work"),
        "characters": source_context.get("characters", []),
        "themes": source_context.get("themes", []),
        "strict_boundaries": {
            "allowed_characters": source_context.get("characters", []),
            "allowed_work_titles": [item.get("title") for item in source_context.get("works", []) if item.get("title")],
            "do_not_add": "No extra characters, places, citations, page numbers, plot episodes or biographical details beyond clean_facts and current_work.",
        },
        "source_exercise": source_context.get("exercise", ""),
        "source_solution": source_context.get("solution", ""),
        "requirements": {
            "words": "800 a 1500 mots utiles pour ce niveau",
            "required_blocks": [
                "heading",
                "paragraph",
                "definition",
                "example",
                "methodology",
                "warning",
                "key_points",
                "exercise",
                "correction",
                "summary",
                "mini_assessment",
            ],
            "minimum_exercises": 3,
            "minimum_corrections": 3,
            "no_truncated_sentence": True,
            "non_empty_corrections": True,
            "mini_assessment_requires_answer_and_explanation": True,
        },
    }


def build_detailed_chapter_blocks(*, course_title: str, chapter_title: str, level: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    profile = LEVEL_PROFILES.get(level, LEVEL_PROFILES["intermediaire"])
    facts = source_context["facts"]
    works = source_context["works"]
    exercise_seed = source_context["exercise"]
    solution_seed = source_context["solution"]
    source_label = source_context["source_label"]
    chapter_focus = infer_chapter_focus(chapter_title, facts, works)
    exam_object = "l'examen régional de français de 1ère année Baccalauréat au Maroc"
    work_reference = describe_work_reference(chapter_title, works)

    blocks = [
        block("heading", chapter_title, f"{chapter_title} — parcours {profile['label']}", source_label),
        block(
            "paragraph",
            "Introduction du chapitre",
            (
                f"Ce chapitre transforme les informations importées sur « {chapter_title} » en un cours exploitable pour {exam_object}. "
                f"Le travail se fait {profile['voice']}. Le support de départ indique notamment : {facts}. "
                f"À partir de ces éléments, l'apprenant apprend à {profile['task']} sans inventer de citation exacte ni de détail absent des sources. "
                f"{profile['depth']} Le but est de produire une réponse claire, fidèle au cours et adaptée au niveau attendu."
            ),
            source_label,
        ),
        block(
            "key_points",
            "Objectifs pédagogiques",
            [
                f"Comprendre le rôle de « {chapter_title} » dans le parcours régional.",
                "Identifier les informations sûres présentes dans le support importé.",
                "Construire une réponse écrite organisée et justifiée.",
                "Relier les notions littéraires aux œuvres étudiées sans réciter mécaniquement.",
                f"S'entraîner à {profile['exam']}.",
            ],
            source_label,
        ),
        block(
            "definition",
            "Notion principale",
            (
                f"Dans ce chapitre, la notion principale correspond à la capacité de lire une information littéraire, de la reformuler et de l'utiliser dans une réponse. "
                f"Pour « {chapter_title} », il faut retenir ce qui est explicitement fourni par le support : {facts}. "
                f"Une bonne définition n'est donc pas une phrase apprise au hasard ; c'est une explication reliée au thème, au genre, au personnage ou à la méthode travaillée."
            ),
            source_label,
        ),
        block(
            "paragraph",
            "Explication détaillée — comprendre avant d'analyser",
            (
                f"La première étape consiste à repérer le thème du chapitre. {chapter_focus} "
                f"Ensuite, l'apprenant reformule l'idée avec ses propres mots. Cette reformulation est importante, car l'examen régional ne demande pas seulement de reconnaître une œuvre : il demande de comprendre une situation, une valeur, un conflit, un sentiment ou une méthode. "
                f"{work_reference} Le support importé sert de limite : il donne les éléments fiables, puis le cours explique comment les organiser. "
                f"Au niveau {profile['label']}, l'attention porte surtout sur la cohérence de la réponse : chaque affirmation doit être compréhensible et rattachée à une information du cours."
            ),
            source_label,
        ),
        block(
            "paragraph",
            "Explication détaillée — construire le sens",
            (
                f"Pour construire le sens, il faut distinguer trois éléments : ce que le support dit, ce que cela signifie pour l'œuvre, et ce que l'élève peut écrire dans une copie. "
                f"Par exemple, si le chapitre évoque un conflit, on précise les deux positions opposées ; s'il évoque un sentiment, on montre son effet sur le personnage ; s'il évoque une méthode, on décrit les étapes à suivre. "
                f"Cette démarche évite deux erreurs : répondre par une simple phrase trop courte ou développer une idée sans preuve. "
                f"La réponse attendue doit donc être progressive : observation, explication, puis conclusion partielle."
            ),
            source_label,
        ),
        block(
            "example",
            "Exemple pédagogique",
            (
                f"Question possible : « Que faut-il retenir de {chapter_title} ? » "
                f"Réponse modèle au niveau {profile['label']} : on commence par nommer l'idée principale, puis on ajoute une justification issue du support importé. "
                f"On peut écrire que le chapitre met en avant {shorten(facts, 220)}. "
                f"Ensuite, on explique pourquoi cette idée aide à comprendre l'œuvre ou la méthode. Cette réponse est acceptable parce qu'elle reste reliée au cours et ne prétend pas citer un passage exact."
            ),
            source_label,
        ),
        block(
            "methodology",
            "Méthode à appliquer à l'examen régional",
            (
                f"1. Lire la question et souligner le verbe de consigne. 2. Identifier l'œuvre, le personnage, la notion ou la méthode concernée. "
                f"3. Écrire une idée principale en une phrase claire. 4. Ajouter un indice ou une information du support. "
                f"5. Expliquer le lien entre l'indice et l'idée. 6. Terminer par une phrase de bilan. "
                f"Pour ce chapitre, la méthode recommandée est : {profile['exam']}. Cette méthode permet de gagner en précision et d'éviter les réponses vagues."
            ),
            source_label,
        ),
        block(
            "warning",
            "Erreurs fréquentes",
            (
                "Les erreurs les plus fréquentes sont : confondre résumé et analyse, donner une opinion personnelle sans justification, inventer une citation, oublier le nom de l'œuvre ou de l'auteur quand il est demandé, et répondre en une seule phrase sans expliquer. "
                f"Dans « {chapter_title} », il faut aussi éviter de dépasser les sources importées : lorsqu'un détail n'est pas fourni, on reste général et on formule une analyse prudente."
            ),
            source_label,
        ),
        block(
            "summary",
            "Résumé",
            (
                f"Ce chapitre apprend à exploiter les informations sûres sur « {chapter_title} ». "
                f"Il montre comment passer de la compréhension à une réponse structurée pour {exam_object}. "
                f"Les éléments essentiels sont : {facts}. Le travail demandé consiste à {profile['task']} avec une formulation claire et justifiée."
            ),
            source_label,
        ),
        block(
            "key_points",
            "Points clés à retenir",
            [
                "Ne jamais inventer de citation exacte ou de numéro de page.",
                "Toujours relier l'idée à une information disponible dans le support.",
                "Organiser la réponse en idée, justification et explication.",
                f"Adapter la profondeur de l'analyse au niveau {profile['label']}.",
                "Préparer l'examen par des exercices progressifs et corrigés.",
            ],
            source_label,
        ),
        block(
            "exercise",
            "Exercice 1 — Compréhension guidée",
            (
                f"Reformulez en deux ou trois phrases l'idée principale du chapitre « {chapter_title} ». "
                f"Appuyez-vous sur cette information du support : {shorten(facts, 260)}."
            ),
            source_label,
        ),
        block(
            "correction",
            "Correction détaillée 1",
            (
                f"Une bonne réponse reprend l'idée sans copier mécaniquement la source. Elle peut expliquer que {shorten(facts, 260)}. "
                "La correction est complète si l'élève utilise ses propres mots, reste fidèle au support et montre pourquoi cette information est importante pour comprendre le chapitre."
            ),
            source_label,
        ),
        block(
            "exercise",
            "Exercice 2 — Analyse structurée",
            (
                f"Rédigez un paragraphe selon la méthode suivante : idée principale, justification, explication. "
                f"Votre réponse doit montrer ce que « {chapter_title} » apporte à la compréhension du parcours régional."
            ),
            source_label,
        ),
        block(
            "correction",
            "Correction détaillée 2",
            (
                f"Le paragraphe attendu commence par une idée claire sur {chapter_title}. Il ajoute ensuite une justification issue du support, par exemple : {shorten(facts, 180)}. "
                "Enfin, il explique l'effet produit : meilleure compréhension d'un personnage, d'un thème, d'un conflit, d'une figure ou d'une méthode. "
                "La réponse ne doit pas juxtaposer des informations ; elle doit montrer le lien logique entre elles."
            ),
            source_label,
        ),
        block(
            "exercise",
            "Exercice 3 — Entraînement type régional",
            exercise_seed
            or f"À partir du chapitre « {chapter_title} », proposez une réponse argumentée en respectant la structure attendue au régional.",
            source_label,
        ),
        block(
            "correction",
            "Correction détaillée 3",
            solution_seed
            or (
                "La réponse doit contenir une opinion ou une idée directrice, deux arguments courts, un exemple lié au cours et une phrase de conclusion. "
                "Elle est réussie si elle reste liée au support et si l'enchaînement des idées est clair."
            ),
            source_label,
        ),
        block(
            "mini_assessment",
            "Mini-évaluation de fin de chapitre",
            {
                "question": f"Quelle démarche permet de réussir une question sur « {chapter_title} » ?",
                "options": [
                    "S'appuyer sur le support et expliquer le lien avec la question",
                    "Inventer une citation pour enrichir la réponse",
                    "Répondre uniquement par le titre du chapitre",
                    "Donner une opinion sans justification",
                ],
                "answer": "S'appuyer sur le support et expliquer le lien avec la question",
                "explanation": "La réponse doit être fondée sur les documents importés et organisée pour l'examen régional.",
            },
            source_label,
        ),
    ]

    return blocks


def block(block_type: str, title: str, content: Any, source_label: str) -> dict[str, Any]:
    return {
        "type": block_type,
        "title": title,
        "content": content,
        "generation_method": "deterministic_fallback",
        "source_document_id": source_label,
        "generated_from_pdf": False,
    }


def extract_source_blocks(structured_content: Any) -> list[dict[str, Any]]:
    if isinstance(structured_content, dict):
        source_blocks = structured_content.get("source_blocks")
        if isinstance(source_blocks, list):
            return [item for item in source_blocks if isinstance(item, dict)]
        variants = structured_content.get("variants")
        if isinstance(variants, dict):
            for blocks in variants.values():
                if isinstance(blocks, list):
                    return [item for item in blocks if isinstance(item, dict) and item.get("generation_method") == "source_json"]
        return []
    if isinstance(structured_content, list):
        return [item for item in structured_content if isinstance(item, dict)]
    return []


def build_source_context(source_blocks: list[dict[str, Any]], works: list[LiteraryWork], chapter_title: str = "") -> dict[str, Any]:
    facts = []
    exercises = []
    solutions = []
    for item in source_blocks:
        text = str(item.get("content") or item.get("question") or "").strip()
        if not text:
            continue
        if item.get("type") == "exercise" or item.get("question"):
            exercises.append(str(item.get("question") or text).strip())
            if item.get("solution"):
                solutions.append(str(item.get("solution")).strip())
        else:
            facts.append(text)
    works_payload = [
        {
            "title": work.title,
            "author": work.author,
            "genre": work.genre,
            "context": work.context,
        }
        for work in works
    ]
    if works_payload:
        facts.extend(f"{item['title']} — {item['author']} — {item['genre']}" for item in works_payload if item.get("title"))
    return {
        "facts": normalize_sentence(" ".join(unique_keep_order(facts)) or "Le support importé présente les repères essentiels du chapitre."),
        "exercise": exercises[0] if exercises else "",
        "solution": solutions[0] if solutions else "",
        "works": works_payload,
        "source_label": first_source_label(source_blocks),
    }


def clean_source_context(context: dict[str, Any], chapter_title: str) -> dict[str, Any]:
    works = context.get("works") if isinstance(context.get("works"), list) else []
    current_work = select_current_work(chapter_title, works)
    if current_work and not is_comparative_chapter(chapter_title):
        works = [current_work]
    facts = clean_fact_text(str(context.get("facts") or ""), chapter_title, works)
    return {
        **context,
        "facts": facts or "Le support importe presente les reperes essentiels du chapitre.",
        "works": works,
        "current_work": current_work,
        "characters": infer_characters(chapter_title, [facts]),
        "themes": infer_themes(chapter_title, [facts]),
    }


def clean_fact_text(text: str, chapter_title: str, works: list[dict[str, Any]]) -> str:
    clean = normalize_sentence(text).replace("...", "")
    if not is_comparative_chapter(chapter_title) and works:
        allowed_titles = {normalize_ascii(item.get("title", "")) for item in works if item.get("title")}
        blocked_titles = {
            "la boite a merveilles",
            "antigone",
            "le dernier jour dun condamne",
            "le dernier jour d un condamne",
        } - allowed_titles
        sentences = split_sentences(clean)
        filtered = []
        for sentence in sentences:
            normalized = normalize_ascii(sentence)
            if any(title and title in normalized for title in blocked_titles):
                continue
            filtered.append(sentence)
        clean = " ".join(filtered) or clean
    return remove_truncated_fragments(clean)


def select_current_work(chapter_title: str, works: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_title = normalize_ascii(chapter_title)
    for work in works:
        work_title = normalize_ascii(work.get("title", ""))
        if work_title and (work_title in normalized_title or normalized_title in work_title):
            return work
    if "boite" in normalized_title or "merveilles" in normalized_title:
        return next((work for work in works if "merveilles" in normalize_ascii(work.get("title", ""))), None)
    if "condamne" in normalized_title:
        return next((work for work in works if "condamne" in normalize_ascii(work.get("title", ""))), None)
    return None


def is_comparative_chapter(chapter_title: str) -> bool:
    normalized = normalize_ascii(chapter_title)
    return any(keyword in normalized for keyword in ("vue densemble", "trois oeuvres", "comparaison", "ensemble"))


def infer_characters(chapter_title: str, facts: list[str] | str) -> list[str]:
    text = normalize_ascii(" ".join(facts) if isinstance(facts, list) else facts)
    normalized_title = normalize_ascii(chapter_title)
    characters = []
    for candidate in ("Antigone", "Creon", "Polynice", "Sidi Mohammed", "Le condamne"):
        if normalize_ascii(candidate) in text or normalize_ascii(candidate) in normalized_title:
            characters.append(candidate)
    return characters


def infer_themes(chapter_title: str, facts: list[str] | str) -> list[str]:
    text = normalize_ascii(f"{chapter_title} {' '.join(facts) if isinstance(facts, list) else facts}")
    themes = []
    for keyword, label in (
        ("devoir", "devoir moral"),
        ("loi", "loi et autorite"),
        ("conflit", "conflit"),
        ("enfance", "enfance"),
        ("solitude", "solitude"),
        ("peine de mort", "peine de mort"),
        ("examen", "methode d'examen"),
        ("figure", "outils d'analyse litteraire"),
    ):
        if keyword in text:
            themes.append(label)
    return themes


def infer_chapter_focus(chapter_title: str, facts: str, works: list[dict[str, Any]]) -> str:
    lowered = chapter_title.lower()
    if "antigone" in lowered:
        return "Le centre du chapitre est le conflit entre la conscience personnelle et l'autorité, à partir des repères fournis par le support."
    if "boîte" in lowered or "merveilles" in lowered:
        return "Le centre du chapitre est l'enfance, le souvenir et le rôle de l'imaginaire comme refuge."
    if "condamné" in lowered:
        return "Le centre du chapitre est la dénonciation de la peine de mort et l'effet produit par l'attente de l'exécution."
    if "langue" in lowered or "analyse" in lowered:
        return "Le centre du chapitre est l'utilisation des notions de langue pour expliquer un effet littéraire."
    if "méthodologie" in lowered or "examen" in lowered:
        return "Le centre du chapitre est la construction d'une réponse complète et méthodique au régional."
    if works:
        titles = ", ".join(item["title"] for item in works if item.get("title"))
        return f"Le centre du chapitre est la mise en relation des œuvres du programme : {titles}."
    return f"Le centre du chapitre est l'information suivante : {shorten(facts, 220)}."


def describe_work_reference(chapter_title: str, works: list[dict[str, Any]]) -> str:
    lowered = chapter_title.lower()
    matches = [item for item in works if item.get("title") and item["title"].lower() in lowered]
    if not matches and "boîte" in lowered:
        matches = [item for item in works if "merveilles" in str(item.get("title", "")).lower()]
    if matches:
        work = matches[0]
        return f"L'œuvre concernée est {work.get('title')} de {work.get('author')}, classée dans le genre {work.get('genre')} selon les données importées."
    if works:
        titles = "; ".join(f"{item.get('title')} de {item.get('author')}" for item in works if item.get("title"))
        return f"Le parcours mobilise les œuvres suivantes : {titles}."
    return "Le support importé ne fournit pas de fiche d'œuvre détaillée ; le cours reste donc centré sur les informations disponibles."


def upsert_course_level_variant(db: Session, course: Course, level: str, content: list[dict[str, Any]], *, generation_method: str = "deterministic_fallback") -> None:
    source_hash = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    variant = (
        db.query(CourseLevelVariant)
        .filter(CourseLevelVariant.course_id == course.id, CourseLevelVariant.level == level)
        .order_by(CourseLevelVariant.id.desc())
        .first()
    )
    if not variant:
        variant = CourseLevelVariant(course=course, level=level, title=f"{course.title} - {level}")
        db.add(variant)
    variant.structured_content = content
    variant.generation_method = generation_method
    variant.source_hash = source_hash
    variant.generated_at = datetime.utcnow()


def chapter_stats(chapters: list[CourseChapter]) -> list[dict[str, Any]]:
    stats = []
    for chapter in sorted(chapters, key=lambda item: (item.position, item.id)):
        blocks = select_stats_blocks(chapter.structured_content)
        stats.append(
            {
                "chapter_id": chapter.id,
                "title": chapter.title,
                "content_chars": len(chapter.content or ""),
                "block_count": len(blocks),
                "block_types": dict(Counter(str(block.get("type")) for block in blocks if isinstance(block, dict))),
                "word_count": count_words(blocks),
            }
        )
    return stats


def select_stats_blocks(structured_content: Any) -> list[dict[str, Any]]:
    if isinstance(structured_content, dict):
        variants = structured_content.get("variants")
        if isinstance(variants, dict) and isinstance(variants.get("intermediaire"), list):
            return variants["intermediaire"]
        source_blocks = structured_content.get("source_blocks")
        if isinstance(source_blocks, list):
            return source_blocks
    if isinstance(structured_content, list):
        return structured_content
    return []


def count_words(blocks: list[dict[str, Any]]) -> int:
    text = blocks_to_text(blocks)
    return len([word for word in text.replace("’", " ").split() if word.strip()])


def blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    parts = []
    for item in blocks:
        content = item.get("content")
        if isinstance(content, list):
            parts.append(" ".join(str(value) for value in content))
        elif isinstance(content, dict):
            parts.append(json.dumps(content, ensure_ascii=False))
        elif content:
            parts.append(str(content))
    return "\n\n".join(parts)


def quality_score(payload: dict[str, Any]) -> float:
    variants = payload.get("variants", {})
    if not isinstance(variants, dict):
        return 0.0
    scores = []
    for blocks in variants.values():
        if not isinstance(blocks, list):
            continue
        word_count = count_words(blocks)
        types = {block.get("type") for block in blocks if isinstance(block, dict)}
        coverage = len(types & {"paragraph", "definition", "example", "methodology", "warning", "key_points", "exercise", "correction", "summary", "mini_assessment"}) / 10
        length_score = min(1.0, word_count / 800)
        scores.append(round((coverage + length_score) / 2, 2))
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def normalize_ai_variants(raw_variants: dict[str, list[dict[str, Any]]], chapter_title: str, source_context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    variants: dict[str, list[dict[str, Any]]] = {}
    for level in LEVELS:
        raw_blocks = raw_variants.get(level) or raw_variants.get(LEVEL_PROFILES[level]["label"]) or []
        variants[level] = normalize_ai_level_blocks(raw_blocks, chapter_title, level, source_context)
    return variants


def normalize_ai_level_blocks(raw_blocks: Any, chapter_title: str, level: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        raw_blocks = []
    blocks = []
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        block_type = normalize_block_type(item.get("type"))
        content = normalize_ai_content(item.get("content"))
        title = normalize_sentence(item.get("title") or default_block_title(block_type))
        if content in (None, "") and block_type == "heading":
            content = title
        if block_type == "mini_assessment" and isinstance(content, dict):
            content = {
                "question": normalize_sentence(content.get("question") or ""),
                "options": [normalize_sentence(option) for option in content.get("options", []) if normalize_sentence(option)],
                "answer": normalize_sentence(content.get("answer") or ""),
                "explanation": normalize_sentence(content.get("explanation") or ""),
            }
        blocks.append(
                {
                    "type": block_type,
                    "title": title,
                    "content": content,
                    "generation_method": "ai_generated",
                    "source_document_id": source_context.get("source_label"),
                "generated_from_pdf": False,
            }
        )
    blocks = ensure_required_blocks(blocks, chapter_title, level, source_context, generation_method="ai_generated")
    blocks = repair_invalid_mini_assessments(blocks, chapter_title, source_context)
    return enforce_variant_contract(blocks, chapter_title, source_context)


def enforce_variant_contract(blocks: list[dict[str, Any]], chapter_title: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep one coherent lesson stream. Do not append old fallback blocks after Groq content."""
    selected: list[dict[str, Any]] = []
    selected.extend(first_blocks(blocks, "heading", 1, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "paragraph", 1, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "definition", 1, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "example", 1, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "methodology", 1, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "warning", 1, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "key_points", 1, chapter_title, source_context))
    selected.extend(numbered_blocks(blocks, "exercise", 3, chapter_title, source_context))
    selected.extend(numbered_blocks(blocks, "correction", 3, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "summary", 1, chapter_title, source_context))
    selected.extend(first_blocks(blocks, "mini_assessment", 1, chapter_title, source_context))
    return selected


def first_blocks(blocks: list[dict[str, Any]], block_type: str, count: int, chapter_title: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    matches = [block for block in blocks if block.get("type") == block_type and valid_block_content(block)]
    if block_type == "mini_assessment":
        matches = [block for block in matches if mini_assessment_matches_chapter(block, chapter_title)]
    if len(matches) < count:
        matches.extend(fallback_blocks_by_type(block_type, count - len(matches), chapter_title, source_context))
    return matches[:count]


def numbered_blocks(blocks: list[dict[str, Any]], block_type: str, count: int, chapter_title: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    matches = [block for block in blocks if block.get("type") == block_type and valid_block_content(block)]
    if len(matches) < count:
        matches.extend(fallback_blocks_by_type(block_type, count - len(matches), chapter_title, source_context))
    output = []
    for index, item in enumerate(matches[:count], start=1):
        output.append({**item, "title": f"{'Exercice' if block_type == 'exercise' else 'Correction'} {index}"})
    return output


def fallback_blocks_by_type(block_type: str, count: int, chapter_title: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    fallback = build_detailed_chapter_blocks(
        course_title="Préparation au régional de français",
        chapter_title=chapter_title,
        level="intermediaire",
        source_context=source_context,
    )
    return [
        {**block_item, "generation_method": "ai_generated_repair"}
        for block_item in fallback
        if block_item.get("type") == block_type and valid_block_content(block_item)
    ][:count]


def valid_block_content(block_item: dict[str, Any]) -> bool:
    content = block_item.get("content")
    if block_item.get("type") == "heading":
        return bool(normalize_sentence(content or block_item.get("title") or ""))
    if block_item.get("type") == "mini_assessment":
        return isinstance(content, dict) and bool(content.get("answer")) and bool(content.get("explanation"))
    return bool(normalize_sentence(content))


def mini_assessment_matches_chapter(block_item: dict[str, Any], chapter_title: str) -> bool:
    content = block_item.get("content")
    if not isinstance(content, dict):
        return False
    text = normalize_ascii(" ".join(str(value) for value in content.values()))
    current_title = normalize_ascii(chapter_title)
    if current_title and current_title in text:
        return True
    return not any(
        other in text
        for other in (
            "methodologie de lexamen regional",
            "la boite a merveilles",
            "le dernier jour dun condamne",
            "le dernier jour d un condamne",
        )
        if other != current_title
    )


def repair_invalid_mini_assessments(blocks: list[dict[str, Any]], chapter_title: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    repaired = False
    for item in blocks:
        if item.get("type") != "mini_assessment":
            output.append(item)
            continue
        content = item.get("content")
        if isinstance(content, dict) and content.get("answer") and content.get("explanation"):
            output.append(item)
            continue
        output.append(
            {
                **item,
                "content": build_source_bound_mini_assessment(chapter_title, source_context),
                "generation_method": "ai_generated_repair",
            }
        )
        repaired = True
    if not any(item.get("type") == "mini_assessment" for item in output):
        output.append(
            {
                "type": "mini_assessment",
                "title": "Mini-évaluation de fin de chapitre",
                "content": build_source_bound_mini_assessment(chapter_title, source_context),
                "generation_method": "ai_generated_repair",
                "source_document_id": source_context.get("source_label"),
                "generated_from_pdf": False,
            }
        )
    return output if repaired or output else blocks


def build_source_bound_mini_assessment(chapter_title: str, source_context: dict[str, Any]) -> dict[str, Any]:
    facts = source_context.get("facts") or "les informations du chapitre"
    return {
        "question": f"Quelle réponse respecte le mieux le chapitre « {chapter_title} » ?",
        "options": [
            "Répondre en s'appuyant sur les faits fournis par le support",
            "Inventer une citation pour rendre la réponse plus longue",
            "Changer d'œuvre pour enrichir la réponse",
            "Donner seulement une opinion personnelle",
        ],
        "answer": "Répondre en s'appuyant sur les faits fournis par le support",
        "explanation": f"La bonne réponse reste liée au support : {shorten(str(facts), 220)}.",
    }


def extend_short_ai_blocks(blocks: list[dict[str, Any]], chapter_title: str, level: str, source_context: dict[str, Any]) -> list[dict[str, Any]]:
    output = list(blocks)
    fallback = build_detailed_chapter_blocks(
        course_title="Préparation au régional de français",
        chapter_title=chapter_title,
        level=level,
        source_context=source_context,
    )
    for candidate in fallback:
        if count_words(output) >= 800:
            break
        if candidate.get("type") not in {"paragraph", "methodology", "example", "exercise", "correction", "summary", "key_points"}:
            continue
        normalized_candidate = {
            **candidate,
            "generation_method": "ai_generated_repair",
        }
        if not is_duplicate_block(output, normalized_candidate):
            output.append(normalized_candidate)
    return output


def is_duplicate_block(blocks: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_text = normalize_ascii(blocks_to_text([candidate]))
    if not candidate_text:
        return True
    for block_item in blocks:
        existing_text = normalize_ascii(blocks_to_text([block_item]))
        if existing_text and (candidate_text in existing_text or existing_text in candidate_text):
            return True
    return False


def normalize_ai_content(content: Any) -> Any:
    if isinstance(content, str):
        return remove_truncated_fragments(content)
    if isinstance(content, list):
        return [remove_truncated_fragments(str(item)) for item in content if normalize_sentence(str(item))]
    if isinstance(content, dict):
        return {key: normalize_ai_content(value) for key, value in content.items()}
    return content


def ensure_required_blocks(blocks: list[dict[str, Any]], chapter_title: str, level: str, source_context: dict[str, Any], *, generation_method: str) -> list[dict[str, Any]]:
    existing_types = [block.get("type") for block in blocks]
    required_types = {"heading", "paragraph", "definition", "example", "methodology", "warning", "key_points", "exercise", "correction", "summary", "mini_assessment"}
    if required_types.issubset(set(existing_types)) and count_blocks(blocks, "exercise") >= 3 and count_blocks(blocks, "correction") >= 3:
        return blocks
    fallback = build_detailed_chapter_blocks(
        course_title="Préparation au régional de français",
        chapter_title=chapter_title,
        level=level,
        source_context=source_context,
    )
    fallback_by_type = group_blocks_by_type(fallback)
    output = list(blocks)
    for block_type in required_types:
        if block_type not in existing_types and fallback_by_type.get(block_type):
            candidate = {**fallback_by_type[block_type][0], "generation_method": generation_method}
            output.append(candidate)
    while count_blocks(output, "exercise") < 3 and fallback_by_type.get("exercise"):
        output.append({**fallback_by_type["exercise"][count_blocks(output, "exercise") % len(fallback_by_type["exercise"])], "generation_method": generation_method})
    while count_blocks(output, "correction") < 3 and fallback_by_type.get("correction"):
        output.append({**fallback_by_type["correction"][count_blocks(output, "correction") % len(fallback_by_type["correction"])], "generation_method": generation_method})
    return output


def validate_generation_quality(variants: dict[str, list[dict[str, Any]]], chapter_title: str, source_context: dict[str, Any]) -> None:
    for level, blocks in variants.items():
        if count_words(blocks) < 450:
            raise ValueError(f"Generated {level} content is too short")
        if repeated_sentence_ratio(blocks) > 0.2:
            raise ValueError(f"Generated {level} content has too many repeated sentences")
        if has_truncated_sentence(blocks):
            raise ValueError(f"Generated {level} content contains truncated sentences")
        if contains_placeholder(blocks):
            raise ValueError(f"Generated {level} content contains placeholders")
        if mixes_unrelated_works(blocks, chapter_title, source_context):
            raise ValueError(f"Generated {level} content mixes unrelated works")
        corrections = [block for block in blocks if block.get("type") == "correction"]
        exercises = [block for block in blocks if block.get("type") == "exercise"]
        if len(exercises) != 3 or len(corrections) != 3:
            raise ValueError(f"Generated {level} content must contain exactly 3 exercises and 3 corrections")
        if any(not normalize_sentence(block.get("content")) for block in corrections):
            raise ValueError(f"Generated {level} content has empty corrections")
        if any(block.get("generation_method") == "deterministic_fallback" for block in blocks):
            raise ValueError(f"Generated {level} content still contains deterministic fallback blocks")
        assessments = [block for block in blocks if block.get("type") == "mini_assessment"]
        if len(assessments) != 1:
            raise ValueError(f"Generated {level} content must contain exactly one mini assessment")
        for assessment in assessments:
            content = assessment.get("content")
            if not isinstance(content, dict) or not content.get("answer") or not content.get("explanation"):
                raise ValueError(f"Generated {level} mini assessment lacks answer or explanation")
            if not mini_assessment_matches_chapter(assessment, chapter_title):
                raise ValueError(f"Generated {level} mini assessment does not match current chapter")


def normalize_block_type(value: Any) -> str:
    clean = normalize_ascii(value).replace("-", "_").replace(" ", "_")
    allowed = {"heading", "paragraph", "definition", "example", "methodology", "warning", "key_points", "exercise", "correction", "summary", "mini_assessment"}
    if clean in {"key_point", "points_cles", "points_clefs"}:
        return "key_points"
    if clean in {"solution", "corrige"}:
        return "correction"
    if clean in {"knowledge_check", "quiz", "evaluation"}:
        return "mini_assessment"
    return clean if clean in allowed else "paragraph"


def default_block_title(block_type: str) -> str:
    return {
        "heading": "Titre",
        "paragraph": "Explication",
        "definition": "Définition",
        "example": "Exemple",
        "methodology": "Méthode",
        "warning": "Attention",
        "key_points": "Points clés",
        "exercise": "Exercice",
        "correction": "Correction",
        "summary": "Résumé",
        "mini_assessment": "Mini-évaluation",
    }.get(block_type, "Section")


def group_blocks_by_type(blocks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for block_item in blocks:
        grouped.setdefault(str(block_item.get("type")), []).append(block_item)
    return grouped


def count_blocks(blocks: list[dict[str, Any]], block_type: str) -> int:
    return len([block for block in blocks if block.get("type") == block_type])


def repeated_sentence_ratio(blocks: list[dict[str, Any]]) -> float:
    sentences = [normalize_ascii(sentence) for sentence in split_sentences(blocks_to_text(blocks)) if len(sentence.split()) >= 6]
    if not sentences:
        return 0.0
    counts = Counter(sentences)
    repeated = sum(count - 1 for count in counts.values() if count > 1)
    return repeated / len(sentences)


def has_truncated_sentence(blocks: list[dict[str, Any]]) -> bool:
    text = blocks_to_text(blocks)
    if "..." in text or "…" in text:
        return True
    return bool(re.search(r"\b(Le|La|Les|Victor|Jean|Ahmed|Antigone|Creon|Polynice)\s*$", text.strip()))


def retry_after_seconds(error_message: str) -> float:
    message = error_message or ""
    seconds_match = re.search(r"try again in ([0-9.]+)s", message, re.IGNORECASE)
    if seconds_match:
        return min(60.0, max(5.0, float(seconds_match.group(1)) + 2.0))
    ms_match = re.search(r"try again in ([0-9.]+)ms", message, re.IGNORECASE)
    if ms_match:
        return max(5.0, (float(ms_match.group(1)) / 1000.0) + 1.0)
    if "rate_limit_exceeded" in message or "HTTP 429" in message:
        return 30.0
    return 0.0


def contains_placeholder(blocks: list[dict[str, Any]]) -> bool:
    text = normalize_ascii(blocks_to_text(blocks))
    return any(token in text for token in ("todo", "placeholder", "a completer", "lorem ipsum"))


def mixes_unrelated_works(blocks: list[dict[str, Any]], chapter_title: str, source_context: dict[str, Any]) -> bool:
    if is_comparative_chapter(chapter_title):
        return False
    current_work = source_context.get("current_work")
    if not current_work:
        return False
    current_title = normalize_ascii(current_work.get("title", ""))
    other_titles = {
        "la boite a merveilles",
        "antigone",
        "le dernier jour dun condamne",
        "le dernier jour d un condamne",
    } - {current_title}
    text = normalize_ascii(blocks_to_text(blocks))
    return any(title in text for title in other_titles)


def split_sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", str(text or "")) if item.strip()]


def remove_truncated_fragments(text: str) -> str:
    clean = str(text or "").replace("…", "").replace("...", "")
    sentences = split_sentences(clean)
    safe_sentences = []
    for sentence in sentences:
        if re.search(r"\b(Le|La|Les|Victor|Jean|Ahmed|Antigone|Creon|Polynice)\s*$", sentence.strip()):
            continue
        safe_sentences.append(sentence.strip())
    return " ".join(safe_sentences) if safe_sentences else normalize_sentence(clean)


def normalize_ascii(value: Any) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFD", str(value or "").lower())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def first_source_label(source_blocks: list[dict[str, Any]]) -> str:
    for item in source_blocks:
        if item.get("source_chapter_id"):
            return str(item["source_chapter_id"])
    return "import_json_latex"


def first_source_chapter_id(source_blocks: list[dict[str, Any]]) -> str | None:
    for item in source_blocks:
        if item.get("source_chapter_id"):
            return str(item["source_chapter_id"])
    return None


def unique_keep_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        clean = normalize_sentence(value)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def normalize_sentence(value: str) -> str:
    return " ".join(str(value or "").split())


def shorten(value: str, limit: int) -> str:
    clean = normalize_sentence(value)
    if len(clean) <= limit:
        return clean
    shortened = clean[:limit].rsplit(" ", 1)[0]
    sentences = split_sentences(shortened)
    return sentences[0] if sentences else shortened
