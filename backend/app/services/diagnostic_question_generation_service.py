from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import Course, CourseChapter, DiagnosticAnswer, DiagnosticQuestion, DifficultyLevel
from app.schemas.automatic_import import PedagogicalPackage

LEVELS = ("debutant", "intermediaire", "avance")
DEFAULT_THEMES = {
    "debutant": ["Comprehension", "Personnages", "Evenements", "Vocabulaire", "Resume simple"],
    "intermediaire": ["Chronologie", "Relations", "Themes", "Justification", "Inference", "Langue"],
    "avance": ["Analyse litteraire", "Interpretation", "Implicite", "Argumentation", "Figures de style", "Comparaison"],
}
MIN_BANK_SIZE = 20


def generate_bank_for_import(
    db: Session,
    package: PedagogicalPackage,
    course: Course,
    subject_id: int,
    education_level_id: int | None,
    chapter_by_source: dict[str, CourseChapter],
    imported_package_hash: str,
    classroom_id: int | None = None,
    import_job_id: int | None = None,
    academic_year: str | None = None,
    latex_structure: dict | None = None,
) -> dict[str, Any]:
    """Create or update the persistent positioning question bank for one imported course."""

    blueprint = normalize_blueprint(package)
    sources = collect_sources(package, chapter_by_source, latex_structure or {})
    if not sources:
        raise HTTPException(status_code=422, detail="Aucune source exploitable pour generer la banque diagnostic")

    candidates = build_candidate_questions(package, course, sources, blueprint, imported_package_hash, classroom_id, import_job_id, academic_year)
    if len(candidates) < MIN_BANK_SIZE:
        raise HTTPException(status_code=422, detail="Banque diagnostic minimale impossible a generer")

    difficulty_by_slug = {row.slug: row for row in db.scalars(select(DifficultyLevel))}
    missing_difficulty = [slug for slug in LEVELS if slug not in difficulty_by_slug]
    if missing_difficulty:
        raise HTTPException(status_code=422, detail=f"Difficultes absentes: {', '.join(missing_difficulty)}")

    existing_questions = list(db.scalars(
        select(DiagnosticQuestion).where(
            DiagnosticQuestion.subject_id == subject_id,
            DiagnosticQuestion.education_level_id == education_level_id,
            DiagnosticQuestion.source_course_id == course.id,
        )
    ))
    existing_by_hash = {question.question_hash: question for question in existing_questions if question.question_hash}
    used_question_ids = set(db.scalars(
        select(DiagnosticAnswer.question_id).where(DiagnosticAnswer.question_id.in_([question.id for question in existing_questions]))
    )) if existing_questions else set()

    created = 0
    updated = 0
    kept = 0
    generated_hashes = set()
    for candidate in candidates:
        generated_hashes.add(candidate["question_hash"])
        existing = existing_by_hash.get(candidate["question_hash"])
        payload = {
            "subject_id": subject_id,
            "education_level_id": education_level_id,
            "difficulty_level_id": difficulty_by_slug[candidate["difficulty"]].id,
            "classroom_id": classroom_id,
            "import_job_id": import_job_id,
            "academic_year": academic_year,
            "topic": candidate["theme"],
            "question": candidate["question"],
            "choices": candidate["choices"],
            "correct_answer": candidate["correct_answer"],
            "explanation": candidate["explanation"],
            "active": True,
            "source_course_id": course.id,
            "source_chapter_id": candidate["source_chapter_id"],
            "source_block_id": candidate["source_block_id"],
            "generation_method": candidate["generation_method"],
            "source_hash": candidate["source_hash"],
            "question_hash": candidate["question_hash"],
            "imported_package_hash": imported_package_hash,
            "source_snapshot": candidate["source_snapshot"],
            "updated_at": datetime.utcnow(),
        }
        if existing is None:
            db.add(DiagnosticQuestion(**payload))
            created += 1
        elif existing.id in used_question_ids:
            existing.active = True
            existing.updated_at = datetime.utcnow()
            kept += 1
        else:
            for field, value in payload.items():
                setattr(existing, field, value)
            updated += 1

    deactivated = 0
    for question in existing_questions:
        if question.generation_method in {"automatic_import", "deterministic_fallback"} and question.question_hash not in generated_hashes:
            question.active = False
            question.updated_at = datetime.utcnow()
            deactivated += 1

    active_count = len(generated_hashes)
    if active_count < MIN_BANK_SIZE:
        raise HTTPException(status_code=422, detail="La banque diagnostic generee contient moins de 20 questions")

    by_difficulty = Counter(candidate["difficulty"] for candidate in candidates)
    by_theme = Counter(candidate["theme"] for candidate in candidates)
    return {
        "active_questions": active_count,
        "created": created,
        "updated": updated,
        "kept": kept,
        "deactivated": deactivated,
        "questions_per_test": blueprint["questions_per_test"],
        "by_difficulty": dict(by_difficulty),
        "by_theme": dict(by_theme),
        "generation_method": "deterministic_fallback",
    }


def normalize_blueprint(package: PedagogicalPackage) -> dict[str, Any]:
    raw = package.diagnostic_blueprint
    levels = dict(raw.levels) if raw else {"debutant": 10, "intermediaire": 10, "avance": 10}
    bank_size = raw.questions_bank_size if raw else 30
    questions_per_test = raw.questions_per_test if raw else 20
    themes = raw.themes if raw and raw.themes else []
    return {
        "questions_bank_size": max(MIN_BANK_SIZE, int(bank_size)),
        "questions_per_test": max(5, min(30, int(questions_per_test))),
        "levels": {slug: max(1, int(levels.get(slug, 1))) for slug in LEVELS},
        "themes": [theme for theme in themes if str(theme).strip()],
    }


def collect_sources(
    package: PedagogicalPackage,
    chapter_by_source: dict[str, CourseChapter],
    latex_structure: dict,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for chapter in sorted(package.chapters, key=lambda item: item.order):
        db_chapter = chapter_by_source.get(chapter.id)
        if db_chapter is None:
            continue
        for index, block in enumerate(chapter.content_blocks, start=1):
            text = clean_spaces(block.content or block.question or "")
            if not text:
                continue
            source_block_id = block.id or f"{chapter.id}_block_{index}"
            sources.append({
                "chapter_source_id": chapter.id,
                "chapter_id": db_chapter.id,
                "chapter_title": chapter.title,
                "source_block_id": source_block_id,
                "text": text,
                "themes": list(chapter.skills or []) + list(chapter.objectives or []),
                "method": "source_json",
            })
        for index, block in enumerate(latex_structure.get("sections", {}).get(normalize_ref(chapter.latex_reference or ""), []), start=1):
            text = clean_spaces(block.get("content") or "")
            if not text:
                continue
            sources.append({
                "chapter_source_id": chapter.id,
                "chapter_id": db_chapter.id,
                "chapter_title": chapter.title,
                "source_block_id": f"{chapter.id}_latex_{index}",
                "text": text,
                "themes": list(chapter.skills or []) + list(chapter.objectives or []),
                "method": "source_latex",
            })

    for work in package.works:
        work_texts = [work.title, work.author, work.genre, work.context]
        for work_chapter in work.chapters:
            work_texts.extend([work_chapter.title, work_chapter.summary])
            work_texts.extend(work_chapter.characters)
            work_texts.extend(work_chapter.themes)
            work_texts.extend([f"{item.term}: {item.definition}" for item in work_chapter.vocabulary])
        text = clean_spaces(". ".join(item for item in work_texts if item))
        if text and package.chapters:
            first_chapter = chapter_by_source.get(package.chapters[0].id)
            sources.append({
                "chapter_source_id": package.chapters[0].id,
                "chapter_id": first_chapter.id if first_chapter else None,
                "chapter_title": work.title,
                "source_block_id": f"work_{work.id}",
                "text": text,
                "themes": [theme for chapter in work.chapters for theme in chapter.themes] or ["Oeuvre"],
                "method": "source_json",
            })
    return sources


def build_candidate_questions(
    package: PedagogicalPackage,
    course: Course,
    sources: list[dict[str, Any]],
    blueprint: dict[str, Any],
    imported_package_hash: str,
    classroom_id: int | None,
    import_job_id: int | None,
    academic_year: str | None,
) -> list[dict[str, Any]]:
    targets = distribute_by_levels(blueprint)
    candidates: list[dict[str, Any]] = []
    seen = set()
    source_index = 0
    max_attempts = blueprint["questions_bank_size"] * max(8, len(sources))

    while len(candidates) < blueprint["questions_bank_size"] and source_index < max_attempts:
        level = level_for_index(targets, len(candidates))
        source = sources[source_index % len(sources)]
        variant_number = source_index // len(sources)
        candidate = make_question(package, course, source, level, blueprint, variant_number, imported_package_hash, classroom_id, import_job_id, academic_year)
        normalized = normalize_text(candidate["question"])
        if normalized not in seen and candidate["correct_answer"] in candidate["choices"]:
            seen.add(normalized)
            candidates.append(candidate)
        source_index += 1
    return candidates


def distribute_by_levels(blueprint: dict[str, Any]) -> list[str]:
    targets = []
    for level in LEVELS:
        targets.extend([level] * blueprint["levels"].get(level, 1))
    while len(targets) < blueprint["questions_bank_size"]:
        targets.extend(LEVELS)
    return targets[: blueprint["questions_bank_size"]]


def level_for_index(targets: list[str], index: int) -> str:
    return targets[index % len(targets)]


def make_question(
    package: PedagogicalPackage,
    course: Course,
    source: dict[str, Any],
    level: str,
    blueprint: dict[str, Any],
    variant_number: int,
    imported_package_hash: str,
    classroom_id: int | None,
    import_job_id: int | None,
    academic_year: str | None,
) -> dict[str, Any]:
    theme = theme_for_question(source, level, blueprint, variant_number)
    correct = answer_from_source(source, level, variant_number)
    choices = build_choices(package, source, correct, level, variant_number)
    question = question_prompt(level, theme, source["chapter_title"], variant_number)
    source_hash = stable_hash({
        "course_id": course.id,
        "chapter": source["chapter_source_id"],
        "block": source["source_block_id"],
        "text": source["text"],
        "level": level,
        "variant": variant_number,
    })
    question_hash = stable_hash({
        "course_id": course.id,
        "source_hash": source_hash,
        "question": question,
        "choices": choices,
        "answer": correct,
    })
    return {
        "difficulty": level,
        "theme": theme,
        "question": question,
        "choices": choices,
        "correct_answer": correct,
        "explanation": explanation_for(level, source),
        "source_chapter_id": source["chapter_id"],
        "source_block_id": source["source_block_id"],
        "generation_method": "deterministic_fallback",
        "source_hash": source_hash,
        "question_hash": question_hash,
        "imported_package_hash": imported_package_hash,
            "source_snapshot": {
                "course_title": course.title,
                "classroom_id": classroom_id,
                "import_job_id": import_job_id,
                "academic_year": academic_year,
                "chapter_source_id": source["chapter_source_id"],
            "chapter_title": source["chapter_title"],
            "source_block_id": source["source_block_id"],
            "source_excerpt": source["text"][:500],
            "package_hash": imported_package_hash,
        },
    }


def theme_for_question(source: dict[str, Any], level: str, blueprint: dict[str, Any], variant_number: int) -> str:
    candidates = blueprint["themes"] or DEFAULT_THEMES[level]
    source_themes = [theme for theme in source.get("themes", []) if str(theme).strip()]
    merged = source_themes + candidates
    return str(merged[variant_number % len(merged)]).strip()


def answer_from_source(source: dict[str, Any], level: str, variant_number: int) -> str:
    text = source["text"]
    if level == "debutant":
        return shorten(text, 90)
    if level == "intermediaire":
        sentences = split_sentences(text)
        return shorten(sentences[variant_number % len(sentences)] if sentences else text, 110)
    return shorten(text, 130)


def build_choices(package: PedagogicalPackage, source: dict[str, Any], correct: str, level: str, variant_number: int) -> list[str]:
    sourced_distractors = []
    for chapter in package.chapters:
        for block in chapter.content_blocks:
            text = clean_spaces(block.content or block.question or "")
            if text and normalize_text(text) != normalize_text(source["text"]):
                sourced_distractors.append(shorten(text, 110))
    for work in package.works:
        sourced_distractors.extend([shorten(value, 90) for value in [work.title, work.author, work.genre, work.context] if value])
        for chapter in work.chapters:
            sourced_distractors.extend([shorten(value, 90) for value in [chapter.title, chapter.summary] + chapter.characters + chapter.themes if value])

    generic = [
        f"Une information d'un autre passage du package",
        f"Un element secondaire non central pour {source['chapter_title']}",
        f"Une formulation qui ne correspond pas au passage source",
    ]
    distractors = unique_keep_order(sourced_distractors + generic)
    distractors = [item for item in distractors if normalize_text(item) != normalize_text(correct)]
    rotated = distractors[variant_number:] + distractors[:variant_number]
    choices = unique_keep_order([correct] + rotated)[:4]
    while len(choices) < 4:
        choices.append(f"Choix source {len(choices) + 1}")
    offset = {"debutant": 0, "intermediaire": 1, "avance": 2}[level] + variant_number
    return rotate(choices[:4], offset)


def question_prompt(level: str, theme: str, chapter_title: str, variant_number: int) -> str:
    suffix = "" if variant_number == 0 else f" - situation {variant_number + 1}"
    if level == "debutant":
        return f"Dans le theme {theme}, quel element explicite est associe a {chapter_title}{suffix} ?"
    if level == "intermediaire":
        return f"Dans {chapter_title}, quelle information aide le mieux a justifier le theme {theme}{suffix} ?"
    return f"Quelle interpretation argumentee du theme {theme} s'appuie sur {chapter_title}{suffix} ?"


def explanation_for(level: str, source: dict[str, Any]) -> str:
    if level == "debutant":
        return f"La reponse reprend une information explicite du chapitre {source['chapter_title']}."
    if level == "intermediaire":
        return f"La reponse est justifiee par le passage source du chapitre {source['chapter_title']}."
    return f"La reponse demande de relier l'idee au passage source tout en restant fondee sur {source['chapter_title']}."


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def normalize_ref(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower().replace("_", "-")).strip("-")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", value.lower())).strip()


def clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_sentences(value: str) -> list[str]:
    sentences = [clean_spaces(item) for item in re.split(r"(?<=[.!?])\s+", value) if clean_spaces(item)]
    return sentences or [value]


def shorten(value: str, limit: int) -> str:
    text = clean_spaces(value)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].strip() or text[:limit].strip()


def unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        clean = clean_spaces(item)
        key = normalize_text(clean)
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def rotate(items: list[str], offset: int) -> list[str]:
    if not items:
        return items
    offset = offset % len(items)
    return items[offset:] + items[:offset]
