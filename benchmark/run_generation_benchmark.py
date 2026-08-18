from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.persistence import Course, CourseChapter
from app.schemas.ai_generation import AdaptiveChapterVariantContent
from app.services import ai_course_generation_service
from app.services.adaptive_generation_benchmark_service import (
    build_metrics,
    ensure_results_dir,
    metric_to_row,
    recommended_solution,
    sanitize_error,
    timestamp,
    write_csv,
    write_json,
    write_xlsx,
)
from app.services.ai.ai_provider import AIProviderError, AIRequest
from app.services.ai.groq_provider import GroqProvider
from app.services.ai.ollama_provider import OllamaProvider
from app.services.ai.prompt_templates import (
    PROMPT_VERSIONS,
    adaptive_course_variant_main_prompt,
    adaptive_course_variant_support_prompt,
)
from app.services.ai.source_grounding_service import source_hash
from app.services.ai_course_generation_service import (
    build_variant_from_content,
    extract_http_status,
    extract_retry_after_seconds,
    load_json_object_response,
    normalize_adaptive_content_payload,
    prepare_compact_variant_sources,
    source_ids_from_sources,
    validate_adaptive_variant_quality,
    validate_main_content_payload,
    validate_support_content_payload,
    variant_word_targets,
)
from app.services.course_service import stable_chapter_source_id

COURSE_ID = 23
CHAPTER_POSITION = 1
LEVELS = ("debutant", "intermediaire")
GROQ_MODEL = "openai/gpt-oss-20b"
OLLAMA_MODEL = "qwen3:1.7b"
RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"
DOCUMENTATION_PATH = PROJECT_ROOT / "benchmark" / "BENCHMARK_ET_JUSTIFICATION_GENERATION.md"


def main() -> int:
    ensure_results_dir(RESULTS_DIR)
    environment = collect_environment()
    source_context = load_source_context()
    results: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []

    for level in LEVELS:
        groq_result = run_provider_benchmark(
            provider_name="groq",
            provider=GroqProvider(),
            model=GROQ_MODEL,
            level=level,
            source_context=source_context,
            environment=environment,
        )
        write_json(RESULTS_DIR / f"groq_{level}.json", groq_result)
        results.append(groq_result)
        metrics.append(groq_result["metrics"])

        local_result = run_ollama_benchmark(level, source_context, environment)
        write_json(RESULTS_DIR / f"local_{level}.json", local_result)
        results.append(local_result)
        metrics.append(local_result["metrics"])

    recommendation, justification = recommended_solution(metrics)
    rows = [metric_to_row(metric, recommendation, justification) for metric in metrics]
    payload = {
        "generated_at": timestamp(),
        "course_id": COURSE_ID,
        "chapter_position": CHAPTER_POSITION,
        "levels": list(LEVELS),
        "environment": environment,
        "recommendation": recommendation,
        "justification": justification,
        "metrics": metrics,
    }
    write_json(RESULTS_DIR / "benchmark_metrics.json", payload)
    write_csv(RESULTS_DIR / "benchmark_generation.csv", rows)
    write_xlsx(PROJECT_ROOT / "benchmark_generation.xlsx", rows)
    write_documentation(payload, results)

    print(json.dumps(final_status(payload, results), ensure_ascii=False, indent=2))
    return 0


def collect_environment() -> dict[str, Any]:
    return {
        "ram_total_bytes": powershell_value("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"),
        "cpu": powershell_value("(Get-CimInstance Win32_Processor).Name"),
        "gpu": powershell_value("(Get-CimInstance Win32_VideoController).Name"),
        "ollama_installed": shutil.which("ollama") is not None,
        "ollama_models": list_ollama_models(),
        "ollama_model": OLLAMA_MODEL,
        "local_install_commands": [
            "winget install Ollama.Ollama",
            f"ollama pull {OLLAMA_MODEL}",
        ],
    }


def powershell_value(command: str) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return " ".join(result.stdout.split()) or "unknown"


def list_ollama_models() -> list[str]:
    if shutil.which("ollama") is None:
        return []
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0:
        return []
    lines = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
    return [line.split()[0] for line in lines if line.split()]


def load_source_context() -> dict[str, Any]:
    with SessionLocal() as db:
        course = db.scalar(select(Course).where(Course.id == COURSE_ID))
        if course is None:
            raise RuntimeError(f"Course {COURSE_ID} not found")
        chapter = db.scalar(
            select(CourseChapter).where(CourseChapter.course_id == COURSE_ID, CourseChapter.position == CHAPTER_POSITION)
        )
        if chapter is None:
            raise RuntimeError(f"Chapter position {CHAPTER_POSITION} not found for course {COURSE_ID}")
        chapter_source_id = stable_chapter_source_id(chapter)
        settings = {**ai_course_generation_service.get_settings(), "ai_variant_min_interval_seconds": 0}
        compact_sources = prepare_compact_variant_sources(chapter_sources(chapter, chapter_source_id), settings)
        return {
            "course_id": course.id,
            "course_title": course.title,
            "subject": course.subject.name if course.subject else "Francais",
            "chapter_id": chapter.id,
            "chapter_position": chapter.position,
            "chapter_title": chapter.title,
            "chapter_source_id": chapter_source_id,
            "sources": compact_sources,
            "source_hash": source_hash(compact_sources),
            "settings": public_settings(settings),
        }


def chapter_sources(chapter: CourseChapter, chapter_source_id: str) -> list[dict[str, Any]]:
    raw_blocks = chapter.structured_content or []
    if isinstance(raw_blocks, dict):
        raw_blocks = raw_blocks.get("blocks") or raw_blocks.get("content_blocks") or [raw_blocks]
    sources: list[dict[str, Any]] = []
    for index, block in enumerate(raw_blocks if isinstance(raw_blocks, list) else [], start=1):
        if not isinstance(block, dict):
            continue
        text = block.get("content") or block.get("text") or block.get("summary") or ""
        if isinstance(text, (list, dict)):
            text = json.dumps(text, ensure_ascii=False)
        if not str(text).strip():
            continue
        sources.append(
            {
                "id": str(block.get("id") or block.get("source_block_id") or f"{chapter_source_id}_block_{index}"),
                "source_block_id": str(block.get("source_block_id") or block.get("id") or f"{chapter_source_id}_block_{index}"),
                "source_chapter_id": chapter_source_id,
                "type": block.get("type") or "paragraph",
                "section": block.get("section") or "",
                "title": block.get("title") or chapter.title,
                "text": str(text).strip(),
                "metadata": block.get("metadata") or {},
            }
        )
    if not sources and chapter.content:
        sources.append(
            {
                "id": f"{chapter_source_id}_content",
                "source_block_id": f"{chapter_source_id}_content",
                "source_chapter_id": chapter_source_id,
                "type": "paragraph",
                "section": "source",
                "title": chapter.title,
                "text": chapter.content,
            }
        )
    return sources


def public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "groq_model": GROQ_MODEL,
        "ollama_model": OLLAMA_MODEL,
        "ai_variant_max_input_tokens": settings.get("ai_variant_max_input_tokens"),
        "ai_variant_source_max_chars": settings.get("ai_variant_source_max_chars"),
        "ai_variant_level_max_output_tokens": settings.get("ai_variant_level_max_output_tokens"),
        "prompt_version": PROMPT_VERSIONS["adaptive_course_variant"],
    }


def run_ollama_benchmark(level: str, source_context: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    if not environment.get("ollama_installed"):
        return unavailable_ollama_result(level, environment, "Ollama non installe ou absent du PATH.")
    if OLLAMA_MODEL not in (environment.get("ollama_models") or []):
        return unavailable_ollama_result(level, environment, f"Modele Ollama absent: {OLLAMA_MODEL}.")
    return run_provider_benchmark(
        provider_name="ollama",
        provider=OllamaProvider(model_name=OLLAMA_MODEL),
        model=OLLAMA_MODEL,
        level=level,
        source_context=source_context,
        environment=environment,
    )


def unavailable_ollama_result(level: str, environment: dict[str, Any], message: str) -> dict[str, Any]:
    metrics = build_metrics(
        level=level,
        solution="Ollama local",
        model=OLLAMA_MODEL,
        execution_type="local",
        status="not_available",
        duration_seconds=0,
        calls=0,
        http_statuses=["not_available"],
        json_valid=False,
        repairs=0,
        content=None,
        errors=[message],
        resources=environment,
        cost="0 EUR API, mais installation et ressources locales requises",
        strengths=["confidentialite locale", "pas de quota API apres installation"],
        limits=["Ollama/model non disponible dans cet environnement", "performance dependante CPU/RAM/GPU"],
    )
    return {"provider": "ollama", "level": level, "model": OLLAMA_MODEL, "status": "not_available", "content": None, "errors": [message], "metrics": metrics}


def run_provider_benchmark(
    *,
    provider_name: str,
    provider: Any,
    model: str,
    level: str,
    source_context: dict[str, Any],
    environment: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    status = "failed"
    content: dict[str, Any] | None = None
    calls = 0
    http_statuses: list[int | str] = []
    errors: list[str] = []
    repairs = 0
    try:
        content, call_info = generate_with_provider_no_retry(provider, source_context, model, level)
        calls = call_info["calls"]
        http_statuses = call_info["http_statuses"]
        repairs = call_info["repairs"]
        status = "completed"
    except AIProviderError as exc:
        error = sanitize_error(str(exc))
        status_code = extract_http_status(error)
        status = "rate_limited" if provider_name == "groq" and status_code == 429 else "failed"
        calls = max(1, calls)
        if status_code:
            http_statuses.append(status_code)
        errors.append(error)
        retry_after = extract_retry_after_seconds(error)
        if retry_after is not None:
            errors.append(f"retry_after_seconds={retry_after}")
    except Exception as exc:
        errors.append(sanitize_error(str(exc)))
    execution_type = "api" if provider_name == "groq" else "local"
    solution = "Groq" if provider_name == "groq" else "Ollama local"
    metrics = build_metrics(
        level=level,
        solution=solution,
        model=model,
        execution_type=execution_type,
        status=status,
        duration_seconds=time.perf_counter() - started,
        calls=calls,
        http_statuses=http_statuses or ([200] if status == "completed" else [execution_type]),
        json_valid=bool(content),
        repairs=repairs,
        content=content,
        errors=errors,
        resources=environment,
        cost="cout API estime selon tokens Groq; aucune cle stockee" if execution_type == "api" else "0 EUR API; electricite et temps machine locaux",
        strengths=["rapidite potentielle", "integration backend existante"] if execution_type == "api" else ["donnees locales", "pas de cle API"],
        limits=["quota TPM/RPM", "dependance reseau"] if execution_type == "api" else ["installation locale", "performance machine"],
    )
    return {
        "provider": provider_name,
        "level": level,
        "model": model,
        "status": status,
        "content": content,
        "errors": errors,
        "metrics": metrics,
        "source_context": {key: value for key, value in source_context.items() if key != "sources"} | {"source_count": len(source_context["sources"])},
    }


def generate_with_provider_no_retry(provider: Any, source_context: dict[str, Any], model: str, level: str) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = ai_course_generation_service.get_settings()
    max_tokens = int(settings.get("ai_variant_level_max_output_tokens") or settings.get("ai_variant_max_output_tokens") or 1800)
    main_payload = {
        "phase": "main_content",
        "chapter_source_id": source_context["chapter_source_id"],
        "chapter_title": source_context["chapter_title"],
        "level": level,
        "sources": source_context["sources"],
        "strict_word_targets": variant_word_targets(level),
        "required_fields": ["summary", "explanation", "key_points", "vocabulary"],
    }
    support_base = {
        "phase": "pedagogical_support",
        "chapter_source_id": source_context["chapter_source_id"],
        "chapter_title": source_context["chapter_title"],
        "level": level,
        "sources": source_context["sources"],
        "strict_word_targets": variant_word_targets(level),
        "required_fields": ["guided_example", "learning_support", "practice_question", "blocks"],
    }
    calls = 0
    http_statuses: list[int | str] = []
    repairs = 0

    main_response = provider.generate_structured(
        AIRequest(
            system_prompt=adaptive_course_variant_main_prompt(source_context["subject"], level),
            user_prompt=json.dumps(main_payload, ensure_ascii=False),
            response_schema=None,
            temperature=0.0,
            max_tokens=max(700, min(max_tokens, 1400)),
            timeout_seconds=float(settings.get("ai_variant_timeout_seconds") or 20),
            model_name=model,
        )
    )
    calls += 1
    http_statuses.append(200)
    main_content = load_json_object_response(main_response.text)
    main_errors = validate_main_content_payload(main_content, level)
    if main_errors:
        repairs += 1
        raise ValueError("; ".join(main_errors))

    support_payload = {
        **support_base,
        "main_content": {
            "summary": main_content.get("summary"),
            "explanation": main_content.get("explanation"),
            "key_points": main_content.get("key_points"),
            "vocabulary": main_content.get("vocabulary"),
        },
    }
    support_response = provider.generate_structured(
        AIRequest(
            system_prompt=adaptive_course_variant_support_prompt(source_context["subject"], level),
            user_prompt=json.dumps(support_payload, ensure_ascii=False),
            response_schema=None,
            temperature=0.0,
            max_tokens=max(700, min(max_tokens, 1400)),
            timeout_seconds=float(settings.get("ai_variant_timeout_seconds") or 20),
            model_name=model,
        )
    )
    calls += 1
    http_statuses.append(200)
    support_content = load_json_object_response(support_response.text)
    support_content = ai_course_generation_service.unwrap_support_content_payload(support_content)
    support_errors = validate_support_content_payload(support_content, level)
    if support_errors:
        repairs += 1
        raise ValueError("; ".join(support_errors))

    merged = normalize_adaptive_content_payload(
        {
            "summary": main_content.get("summary"),
            "explanation": main_content.get("explanation"),
            "key_points": main_content.get("key_points"),
            "vocabulary": main_content.get("vocabulary"),
            "guided_example": support_content.get("guided_example"),
            "learning_support": support_content.get("learning_support"),
            "practice_question": support_content.get("practice_question"),
            "blocks": support_content.get("blocks") or [],
        }
    )
    content_model = AdaptiveChapterVariantContent.model_validate(merged)
    variant = build_variant_from_content(
        content=content_model,
        level=level,
        chapter_source_id=source_context["chapter_source_id"],
        chapter_title=source_context["chapter_title"],
        source_block_ids=source_ids_from_sources(source_context["sources"]),
        source_digest=source_context["source_hash"],
        model_name=model,
    )
    quality_errors = validate_adaptive_variant_quality(variant)
    if quality_errors:
        raise ValueError("; ".join(quality_errors))
    return variant.model_dump(mode="json"), {"calls": calls, "http_statuses": http_statuses, "repairs": repairs}


def write_documentation(payload: dict[str, Any], results: list[dict[str, Any]]) -> None:
    metrics = payload["metrics"]
    by_level = {level: [metric for metric in metrics if metric.get("level") == level] for level in LEVELS}
    lines = [
        "# BENCHMARK ET JUSTIFICATION GENERATION",
        "",
        "## 1. Objectif du benchmark",
        "",
        "Comparer de maniere isolee Groq et Ollama sur deux niveaux adaptatifs, Debutant et Intermediaire, pour le cours 23 chapitre 1. Le benchmark ne modifie pas `CourseLevelVariant`.",
        "",
        "## 2. Architecture du pipeline de generation",
        "",
        "- Lecture des sources du chapitre depuis PostgreSQL (`Course`, `CourseChapter`).",
        "- Compactage identique avec `prepare_compact_variant_sources`.",
        "- Deux appels par execution valide: `main_content`, puis `pedagogical_support`.",
        "- Validation avec les schemas Pydantic et les validateurs de production.",
        "",
        "## 3. Conditions experimentales",
        "",
        f"- Course: `{COURSE_ID}`.",
        f"- Chapitre position: `{CHAPTER_POSITION}`.",
        f"- Modele Groq: `{GROQ_MODEL}`.",
        f"- Modele Ollama: `{OLLAMA_MODEL}`.",
        "- Aucun parallelisme.",
        "- Aucun retry automatique Groq dans le benchmark.",
        "- Aucun fallback marque comme succes.",
        "",
        "## 4. Seuils pedagogiques",
        "",
        "- Debutant: seuils actuels du pipeline Debutant.",
        "- Intermediaire: resume >= 110 mots, explication >= 200 mots, learning_support >= 100 mots, au moins 5 key_points, au moins 5 termes de vocabulaire, cinq sections completes.",
        "",
        "## 5. Tableau comparatif",
        "",
        "| Niveau | Solution | Modele | Statut | Appels | JSON valide | Resume | Explication | Support | Sections | Qualite |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in metrics:
        lines.append(
            f"| {metric['level']} | {metric['solution']} | {metric['model']} | {metric['status']} | {metric['calls']} | {metric['json_valid']} | {metric['summary_words']} | {metric['explanation_words']} | {metric['learning_support_words']} | {metric['has_five_sections']} | {metric['pedagogical_quality']['qualite_generale']} |"
        )
    lines.extend(["", "## 6. Analyse par niveau", ""])
    for level, items in by_level.items():
        lines.append(f"### {level}")
        for item in items:
            errors = "; ".join(str(error) for error in item.get("errors") or []) or "aucune erreur"
            lines.append(
                f"- {item['solution']} / {item['model']}: statut `{item['status']}`, appels `{item['calls']}`, JSON valide `{item['json_valid']}`, erreurs: {errors}."
            )
        lines.append("")
    lines.extend(
        [
            "## 7. Impact de la complexite du niveau",
            "",
            "Le niveau Intermediaire impose des seuils plus eleves que Debutant. Il augmente donc la pression sur le budget de tokens, le respect du format JSON et la longueur utile du contenu.",
            "",
            "## 8. Justification du choix technique final",
            "",
            f"Recommendation mesuree: **{payload['recommendation']}**. {payload['justification']}",
            "",
            "## 9. Limites",
            "",
            "- Si Groq retourne HTTP 429, la comparaison de qualite est partielle.",
            "- Si Ollama ou `qwen3:1.7b` n'est pas installe, l'execution locale est partielle.",
            "- Les scores pedagogiques sont heuristiques et doivent etre confirmes par une evaluation enseignante.",
            "",
        ]
    )
    DOCUMENTATION_PATH.write_text("\n".join(lines), encoding="utf-8")


def final_status(payload: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    lookup = {(item["provider"], item["level"]): item for item in results}
    groq_debutant = status_label(lookup[("groq", "debutant")], groq=True)
    groq_intermediaire = status_label(lookup[("groq", "intermediaire")], groq=True)
    ollama_debutant = status_label(lookup[("ollama", "debutant")], groq=False)
    ollama_intermediaire = status_label(lookup[("ollama", "intermediaire")], groq=False)
    return {
        "GROQ_DEBUTANT": groq_debutant,
        "OLLAMA_DEBUTANT": ollama_debutant,
        "GROQ_INTERMEDIAIRE": groq_intermediaire,
        "OLLAMA_INTERMEDIAIRE": ollama_intermediaire,
        "COMPARISON_DEBUTANT": comparison_label(groq_debutant, ollama_debutant),
        "COMPARISON_INTERMEDIAIRE": comparison_label(groq_intermediaire, ollama_intermediaire),
        "EXCEL_UPDATED": "YES" if (PROJECT_ROOT / "benchmark_generation.xlsx").exists() else "NO",
        "DOCUMENTATION_UPDATED": "YES" if DOCUMENTATION_PATH.exists() else "NO",
        "RECOMMENDED_SOLUTION": payload["recommendation"],
        "JUSTIFICATION": payload["justification"],
    }


def status_label(result: dict[str, Any], *, groq: bool) -> str:
    if result["status"] == "completed":
        return "COMPLETED"
    if groq and result["status"] == "rate_limited":
        return "RATE_LIMITED"
    return "FAILED"


def comparison_label(left: str, right: str) -> str:
    return "COMPLETE" if left == "COMPLETED" and right == "COMPLETED" else "PARTIAL"


if __name__ == "__main__":
    raise SystemExit(main())
