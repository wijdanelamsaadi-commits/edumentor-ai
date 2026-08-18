from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from functools import lru_cache
import logging
from pathlib import Path
from typing import Any
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.models.persistence import CourseChapter, QuizResult, UserProfile
from app.services import answer_quality_model_service, course_service

EVALUATOR_VERSION = "hybrid-v4-20260801"
EXERCISE_BANK_VERSION = "regional-bank-v1-20260801"
EXERCISE_BANK_PATH = Path(__file__).resolve().parents[1] / "data" / "regional_exercise_bank_v1.json"
logger = logging.getLogger(__name__)

OPEN_REVIEW_MESSAGE = "Réponse enregistrée — vérification enseignante recommandée"


def get_evaluator_debug() -> dict:
    model_debug = answer_quality_model_service.get_model_debug()
    return {
        "version": EVALUATOR_VERSION,
        "module": __file__,
        "has_semantic_match": "semantic_text_match_score" in globals(),
        "exercise_bank_version": EXERCISE_BANK_VERSION,
        "exercise_bank_path": str(EXERCISE_BANK_PATH),
        "exercise_bank_questions": len(load_exercise_bank()),
        "answer_model": model_debug,
    }


@lru_cache(maxsize=1)
def load_exercise_bank() -> list[dict]:
    if not EXERCISE_BANK_PATH.exists():
        return []
    try:
        import json

        payload = json.loads(EXERCISE_BANK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        logger.exception("Impossible de charger la banque d'exercices: %s", EXERCISE_BANK_PATH)
        return []

    questions = payload.get("questions") if isinstance(payload, dict) else payload
    return [item for item in (questions or []) if isinstance(item, dict)]


def chapter_bank_questions(chapter_id: int) -> list[dict]:
    return [
        item
        for item in load_exercise_bank()
        if int(item.get("chapter_id") or 0) == int(chapter_id)
    ]


def select_adaptive_bank_questions(chapter_id: int, learner_level: str, limit: int = 10) -> list[dict]:
    questions = chapter_bank_questions(chapter_id)
    if not questions:
        return []

    normalized_level = normalize_text(learner_level).replace(" ", "_")
    quotas = {
        "debutant": {"debutant": 6, "intermediaire": 4, "avance": 0},
        "intermediaire": {"debutant": 3, "intermediaire": 5, "avance": 2},
        "avance": {"debutant": 2, "intermediaire": 4, "avance": 4},
    }.get(normalized_level, {"debutant": 3, "intermediaire": 5, "avance": 2})

    by_level: dict[str, list[dict]] = {"debutant": [], "intermediaire": [], "avance": []}
    for item in questions:
        difficulty = normalize_text(item.get("difficulty")).replace(" ", "_")
        by_level.setdefault(difficulty, []).append(item)

    selected: list[dict] = []
    for difficulty in ("debutant", "intermediaire", "avance"):
        selected.extend(by_level.get(difficulty, [])[: quotas.get(difficulty, 0)])

    if len(selected) < limit:
        selected_ids = {str(item.get("id")) for item in selected}
        for item in questions:
            if str(item.get("id")) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(str(item.get("id")))
            if len(selected) >= limit:
                break

    selected = selected[:limit]
    return [
        normalize_bank_exercise(item, learner_level, position)
        for position, item in enumerate(selected, start=1)
    ]


def normalize_bank_exercise(item: dict, learner_level: str, position: int) -> dict:
    choices = [str(value).strip() for value in item.get("choices", []) if str(value).strip()]
    expected = [str(value).strip() for value in item.get("expected_elements", []) if str(value).strip()]
    correct_answer = str(item.get("correct_answer") or "").strip()
    if correct_answer and not expected:
        expected = [correct_answer]

    return {
        "id": str(item.get("id") or f"bank-{item.get('chapter_id')}-{position}"),
        "source_block_id": str(item.get("id") or ""),
        "chapter_id": int(item.get("chapter_id") or 0),
        "question": str(item.get("question") or "").strip(),
        "type": normalize_question_type(str(item.get("type") or ""), choices),
        "competence": str(item.get("competence") or "Compréhension").strip(),
        "points": float(item.get("points") or 1),
        "choices": choices,
        "expected_elements": expected,
        "correct_answer": correct_answer,
        "correction": str(item.get("correction") or correct_answer).strip(),
        "explanation": str(item.get("explanation") or item.get("correction") or correct_answer).strip(),
        "level": learner_level,
        "difficulty": str(item.get("difficulty") or "intermediaire"),
        "order": position,
        "bank_version": EXERCISE_BANK_VERSION,
    }


def list_chapter_exercises(db: Session, student: UserProfile, course_id: int, chapter_id: int) -> dict:
    course, chapter = get_accessible_course_chapter(db, student, course_id, chapter_id)
    learner_level = course_service.resolve_learner_level(db, student, course)
    exercises = extract_chapter_exercises(course, chapter, learner_level)
    bank_total = len(chapter_bank_questions(chapter.id))
    return {
        "course_id": course.id,
        "chapter_id": chapter.id,
        "learner_level": learner_level,
        "total": len(exercises),
        "bank_total": bank_total or len(exercises),
        "series_size": len(exercises),
        "bank_version": EXERCISE_BANK_VERSION if bank_total else None,
        "exercises": [public_exercise_payload(item) for item in exercises],
        "progress": get_chapter_exercise_progress(db, student, course_id, chapter_id),
    }


def submit_chapter_exercise(
    db: Session,
    student: UserProfile,
    course_id: int,
    chapter_id: int,
    question_id: str,
    payload: dict,
) -> dict:
    course, chapter = get_accessible_course_chapter(db, student, course_id, chapter_id)
    learner_level = course_service.resolve_learner_level(db, student, course)
    exercises = extract_chapter_exercises(course, chapter, learner_level)
    exercise = next((item for item in exercises if item["id"] == question_id), None)
    if exercise is None:
        raise HTTPException(status_code=404, detail="Exercice introuvable")

    answer = str(payload.get("answer", "") or "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="La réponse est obligatoire")

    evaluation = evaluate_exercise(exercise, answer)
    evaluation["evaluator_version"] = EVALUATOR_VERSION
    logger.warning(
        "EXERCISE_EVALUATOR version=%s module=%s question=%s correct=%s percentage=%s",
        EVALUATOR_VERSION,
        __file__,
        question_id,
        evaluation.get("correct"),
        evaluation.get("percentage"),
    )
    attempt_number = next_exercise_attempt_number(db, student.id, course_id, chapter_id, question_id)
    result = QuizResult(
        user_id=student.id,
        course_id=course_id,
        score=int(round(evaluation["percentage"])),
        correct=1 if evaluation["correct"] is True else 0,
        total=1,
        answers=[{
            "course_id": course_id,
            "chapter_id": chapter_id,
            "question_id": question_id,
            "answer": answer,
            "question_type": exercise["type"],
            "competence": exercise["competence"],
            "level": learner_level,
            "attempt_number": attempt_number,
            "status": evaluation["status"],
        }],
        corrections=[{
            "course_id": course_id,
            "chapter_id": chapter_id,
            "question_id": question_id,
            "question": exercise["question"],
            "user_answer": answer,
            "correct_answer": evaluation.get("correct_answer"),
            "expected_elements": exercise.get("expected_elements", []),
            "correction": evaluation.get("correction", ""),
            "explanation": evaluation.get("explanation", ""),
            "recommendation": evaluation.get("recommendation", ""),
            "is_correct": evaluation["correct"] is True,
            "status": evaluation["status"],
            "points_awarded": evaluation["points_awarded"],
            "max_points": exercise["points"],
            "competence": exercise["competence"],
            "attempt_number": attempt_number,
            "evaluator_version": EVALUATOR_VERSION,
            "evaluation_method": evaluation.get("evaluation_method", "rules"),
            "model_label": evaluation.get("model_label"),
            "model_confidence": evaluation.get("model_confidence"),
            "model_version": evaluation.get("model_version"),
        }],
        recommendation=evaluation.get("recommendation", ""),
    )
    db.add(result)
    db.flush()
    db.refresh(result)

    progress = get_chapter_exercise_progress(db, student, course_id, chapter_id)

    from app.services import study_path_service

    study_path_sync = study_path_service.sync_chapter_exercise_item(
        db,
        student,
        course_id=course_id,
        chapter_id=chapter_id,
        progress=progress,
        minimum_score=60,
    )

    db.commit()
    db.refresh(result)

    return {
        "result_id": result.id,
        "course_id": course_id,
        "chapter_id": chapter_id,
        "question_id": question_id,
        "attempt_number": attempt_number,
        "answer": answer,
        "max_points": exercise["points"],
        "competence": exercise["competence"],
        **evaluation,
        "progress": progress,
        "study_path_sync": study_path_sync,
    }


def get_chapter_exercise_progress(db: Session, student: UserProfile, course_id: int, chapter_id: int) -> dict:
    course, chapter = get_accessible_course_chapter(db, student, course_id, chapter_id)
    learner_level = course_service.resolve_learner_level(db, student, course)
    active_exercises = extract_chapter_exercises(course, chapter, learner_level)
    active_question_ids = {str(item.get("id") or "") for item in active_exercises}
    total_questions = len(active_exercises)
    bank_total = len(chapter_bank_questions(chapter.id)) or total_questions

    rows = list(db.scalars(
        select(QuizResult)
        .where(QuizResult.user_id == student.id, QuizResult.course_id == course_id)
        .order_by(QuizResult.created_at.desc(), QuizResult.id.desc())
    ))
    latest_by_question: dict[str, dict] = {}
    attempts_by_question: dict[str, int] = {}
    history = []
    for row in rows:
        answer_items = row.answers if isinstance(row.answers, list) else []
        correction_items = row.corrections if isinstance(row.corrections, list) else []
        answer = answer_items[0] if answer_items and isinstance(answer_items[0], dict) else {}
        correction = correction_items[0] if correction_items and isinstance(correction_items[0], dict) else {}
        if int(answer.get("chapter_id") or 0) != int(chapter_id):
            continue
        question_id = str(answer.get("question_id") or correction.get("question_id") or "")
        if not question_id or question_id not in active_question_ids:
            continue
        attempts_by_question[question_id] = attempts_by_question.get(question_id, 0) + 1
        item = {
            "result_id": row.id,
            "question_id": question_id,
            "answer": answer.get("answer", ""),
            "score": row.score,
            "correct": correction.get("is_correct", False),
            "status": correction.get("status", answer.get("status", "validated")),
            "points_awarded": correction.get("points_awarded", 0),
            "max_points": correction.get("max_points", 1),
            "competence": correction.get("competence", answer.get("competence", "")),
            "submitted_at": row.created_at.isoformat() if row.created_at else None,
            "attempt_number": correction.get("attempt_number", answer.get("attempt_number", 1)),
            "evaluator_version": correction.get("evaluator_version", "legacy"),
            "evaluation_method": correction.get("evaluation_method", "rules"),
            "model_label": correction.get("model_label"),
            "model_confidence": correction.get("model_confidence"),
            "model_version": correction.get("model_version"),
        }
        history.append(item)
        latest_by_question.setdefault(question_id, item)

    validated = len(latest_by_question)
    successful = sum(1 for item in latest_by_question.values() if item["correct"] is True)
    total_points = sum(float(item.get("max_points") or 1) for item in latest_by_question.values())
    awarded = sum(float(item.get("points_awarded") or 0) for item in latest_by_question.values())
    weak_competencies = sorted({
        item["competence"]
        for item in latest_by_question.values()
        if item.get("competence") and item.get("correct") is not True
    })

    pending_review_questions = sum(
        1
        for item in latest_by_question.values()
        if item.get("status") == "pending_teacher_review"
    )
    definitive_results = [
        item
        for item in latest_by_question.values()
        if item.get("status") != "pending_teacher_review"
    ]
    definitive_total_points = sum(
        float(item.get("max_points") or 1)
        for item in definitive_results
    )
    definitive_awarded = sum(
        float(item.get("points_awarded") or 0)
        for item in definitive_results
    )
    mastery_score = (
        round((definitive_awarded / definitive_total_points) * 100, 2)
        if definitive_total_points
        else 100.0 if validated and pending_review_questions == validated else 0.0
    )
    all_questions_submitted = total_questions > 0 and validated >= total_questions
    completion_ready = (
        all_questions_submitted
        and (not definitive_results or mastery_score >= 60)
    )

    return {
        "course_id": course_id,
        "chapter_id": chapter_id,
        "total_questions": total_questions,
        "bank_total": bank_total,
        "bank_version": EXERCISE_BANK_VERSION if chapter_bank_questions(chapter.id) else None,
        "validated_questions": validated,
        "successful_questions": successful,
        "failed_questions": max(0, validated - successful),
        "pending_review_questions": pending_review_questions,
        "attempts_count": len(history),
        "best_score": max((item["score"] for item in history), default=0),
        "current_score": round((awarded / total_points) * 100, 2) if total_points else 0,
        "mastery_score": mastery_score,
        "minimum_score": 60,
        "all_questions_submitted": all_questions_submitted,
        "completion_ready": completion_ready,
        "weak_competencies": weak_competencies,
        "latest_results": list(latest_by_question.values()),
        "history": history[:20],
    }


def get_accessible_course_chapter(
    db: Session,
    student: UserProfile,
    course_id: int,
    chapter_id: int,
) -> tuple[Any, CourseChapter]:
    course = course_service.get_course_model(db, course_id)
    if course is None or not course_service.can_access_course(db, course, student):
        raise HTTPException(status_code=404, detail="Cours introuvable")
    chapter = next((item for item in course.chapters if item.id == chapter_id and item.active), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable")
    return course, chapter


def extract_chapter_exercises(course: Any, chapter: CourseChapter, learner_level: str) -> list[dict]:
    bank_exercises = select_adaptive_bank_questions(chapter.id, learner_level, limit=10)
    if bank_exercises:
        return bank_exercises

    blocks = selected_chapter_blocks(course, chapter, learner_level)
    exercises = []
    pending_corrections = [
        block for block in blocks
        if normalize_type(block.get("type")) in {"correction", "solution"} and has_text(block)
    ]
    correction_index = 0
    for index, block in enumerate(blocks):
        block_type = normalize_type(block.get("type"))
        if block_type not in {"exercise", "mini_assessment", "knowledge_check"}:
            continue
        exercise = normalize_exercise_block(block, chapter, learner_level, len(exercises) + 1)
        if not exercise:
            continue
        if not exercise.get("correction") and correction_index < len(pending_corrections):
            exercise["correction"] = text_from_block(pending_corrections[correction_index])
            correction_index += 1
        exercises.append(exercise)
    return exercises


def selected_chapter_blocks(course: Any, chapter: CourseChapter, learner_level: str) -> list[dict]:
    selected_variant = None
    session = object_session(course)
    if session is not None:
        selected_variant = course_service.serialize_selected_course_variant(session, course, learner_level)
    if selected_variant and isinstance(selected_variant.get("chapters"), list):
        for variant_chapter in selected_variant["chapters"]:
            if not isinstance(variant_chapter, dict):
                continue
            if chapter_matches_variant(chapter, variant_chapter):
                blocks = variant_chapter.get("blocks")
                if isinstance(blocks, list) and blocks:
                    return [block for block in blocks if isinstance(block, dict)]
    raw = chapter.structured_content or []
    if isinstance(raw, dict):
        candidates = raw.get("variants", {}).get(learner_level) if isinstance(raw.get("variants"), dict) else None
        if isinstance(candidates, list):
            return [block for block in candidates if isinstance(block, dict)]
        blocks = raw.get("blocks") or raw.get("source_blocks") or []
        return [block for block in blocks if isinstance(block, dict)]
    if isinstance(raw, list):
        return [block for block in raw if isinstance(block, dict)]
    return []


def chapter_matches_variant(chapter: CourseChapter, variant_chapter: dict) -> bool:
    course_chapter_id = variant_chapter.get("course_chapter_id")
    if course_chapter_id and int(course_chapter_id) == chapter.id:
        return True
    source = str(variant_chapter.get("chapter_source_id") or variant_chapter.get("source_chapter_id") or "")
    return source == course_service.stable_chapter_source_id(chapter)


def normalize_exercise_block(block: dict, chapter: CourseChapter, learner_level: str, position: int) -> dict | None:
    content = block.get("content")
    data = content if isinstance(content, dict) else {}
    question = first_text(
        data.get("question"),
        block.get("question"),
        content if isinstance(content, str) else "",
        block.get("title"),
    )
    if not question:
        return None
    choices = first_list(data.get("options"), data.get("choices"), block.get("options"), block.get("choices"))
    expected = first_list(
        data.get("expected_elements"),
        block.get("expected_elements"),
        data.get("answer_elements"),
        data.get("answers"),
    )
    correct_answer = first_text(
        data.get("correct_answer"),
        data.get("answer"),
        data.get("expected_answer"),
        block.get("correct_answer"),
        block.get("answer"),
        block.get("expected_answer"),
    )
    if correct_answer and not expected:
        expected = split_expected_elements(correct_answer)
    question_type = normalize_question_type(first_text(data.get("type"), block.get("question_type"), block.get("subtype"), block.get("type")), choices)
    correction = first_text(data.get("correction"), data.get("solution"), data.get("explanation"), block.get("correction"), block.get("solution"))
    return {
        "id": str(block.get("id") or block.get("source_block_id") or f"chapter-{chapter.id}-exercise-{position}"),
        "source_block_id": block.get("source_block_id") or block.get("id"),
        "chapter_id": chapter.id,
        "question": question,
        "type": question_type,
        "competence": first_text(data.get("competence"), block.get("competence"), block.get("skill"), infer_competence(question, question_type)),
        "points": float(data.get("points") or block.get("points") or data.get("bareme") or block.get("bareme") or 1),
        "choices": choices,
        "expected_elements": expected,
        "correct_answer": correct_answer,
        "correction": correction,
        "explanation": first_text(data.get("explanation"), block.get("explanation"), correction),
        "level": learner_level,
        "order": int(block.get("position") or position),
    }


def public_exercise_payload(exercise: dict) -> dict:
    return {
        "id": exercise["id"],
        "chapter_id": exercise["chapter_id"],
        "question": exercise["question"],
        "type": exercise["type"],
        "competence": exercise["competence"],
        "points": exercise["points"],
        "choices": exercise["choices"],
        "level": exercise["level"],
        "difficulty": exercise.get("difficulty", exercise["level"]),
        "order": exercise["order"],
        "bank_version": exercise.get("bank_version"),
    }


def evaluate_exercise(exercise: dict, answer: str) -> dict:
    question_type = exercise["type"]
    points = float(exercise["points"] or 1)
    correct_answer = str(exercise.get("correct_answer") or "").strip()
    expected = exercise.get("expected_elements") or split_expected_elements(correct_answer)

    if question_type in {"response_long", "production_ecrite"}:
        return {
            "status": "pending_teacher_review",
            "correct": None,
            "points_awarded": 0,
            "percentage": 0,
            "correct_answer": None,
            "correction": exercise.get("correction") or OPEN_REVIEW_MESSAGE,
            "explanation": OPEN_REVIEW_MESSAGE,
            "recommendation": "Votre réponse longue est enregistrée pour une validation enseignante.",
            "evaluation_method": "teacher_review",
            "model_label": None,
            "model_confidence": None,
            "model_version": None,
        }

    if question_type in {"qcm", "true_false", "figure_style"}:
        correct = normalize_text(answer) == normalize_text(correct_answer)
        if question_type == "figure_style" and not correct and expected:
            correct = normalize_text(answer) in {normalize_text(item) for item in expected}
        awarded = points if correct else 0
        return {
            "status": "validated",
            "correct": correct,
            "points_awarded": awarded,
            "percentage": round((awarded / points) * 100, 2) if points else 0,
            "correct_answer": correct_answer,
            "correction": exercise.get("correction") or correct_answer,
            "explanation": exercise.get("explanation") or default_explanation(correct, question_type),
            "recommendation": "" if correct else "Relisez la notion évaluée puis réessayez.",
            "evaluation_method": "rules",
            "model_label": None,
            "model_confidence": None,
            "model_version": None,
        }

    matched = matched_expected_elements(answer, expected)
    ratio = matched / len(expected) if expected else 0

    whole_answer_score = semantic_text_match_score(answer, correct_answer)
    if whole_answer_score >= 0.90:
        ratio = max(ratio, 1.0)
    elif whole_answer_score >= 0.78:
        ratio = max(ratio, whole_answer_score)

    if not expected and correct_answer:
        ratio = whole_answer_score

    model_result = answer_quality_model_service.predict_answer_quality(
        question=str(exercise.get("question") or ""),
        reference=correct_answer or "; ".join(expected),
        answer=answer,
    )
    if model_result:
        model_label = model_result.get("label")
        model_confidence = float(model_result.get("confidence") or 0)
        model_coverage = float(model_result.get("coverage") or 0)

        if model_label == "correct" and model_confidence >= 0.55 and model_coverage >= 0.25:
            ratio = max(ratio, 0.90)
        elif model_label == "partiel" and model_confidence >= 0.50 and model_coverage >= 0.15:
            ratio = max(ratio, 0.50)

    if question_type in {"justification", "interpretation"} and expected:
        ratio = min(ratio, 0.5) if matched < len(expected) and whole_answer_score < 0.90 else ratio

    ratio = max(0.0, min(1.0, ratio))
    correct = ratio >= 0.6
    awarded = round(points * ratio, 2)
    return {
        "status": "validated",
        "correct": correct,
        "points_awarded": awarded,
        "percentage": round((awarded / points) * 100, 2) if points else 0,
        "correct_answer": correct_answer or "; ".join(expected),
        "correction": exercise.get("correction") or correct_answer or "; ".join(expected),
        "explanation": exercise.get("explanation") or f"{matched}/{len(expected) or 1} élément(s) attendu(s) retrouvés.",
        "recommendation": "" if correct else "Ajoutez une justification plus précise et les éléments attendus.",
        "evaluation_method": "hybrid_rules_model" if model_result else "rules",
        "model_label": model_result.get("label") if model_result else None,
        "model_confidence": round(float(model_result.get("confidence") or 0), 4) if model_result else None,
        "model_version": model_result.get("version") if model_result else None,
    }


def next_exercise_attempt_number(db: Session, user_id: int, course_id: int, chapter_id: int, question_id: str) -> int:
    rows = list(db.scalars(select(QuizResult).where(QuizResult.user_id == user_id, QuizResult.course_id == course_id)))
    count = 0
    for row in rows:
        answers = row.answers if isinstance(row.answers, list) else []
        first = answers[0] if answers and isinstance(answers[0], dict) else {}
        if int(first.get("chapter_id") or 0) == int(chapter_id) and str(first.get("question_id") or "") == question_id:
            count += 1
    return count + 1


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, dict)):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def first_list(*values: Any) -> list[str]:
    for value in values:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return split_expected_elements(value)
    return []


def split_expected_elements(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[|;,\n]", str(value or "")) if part.strip()]


def matched_expected_elements(answer: str, expected: list[str]) -> int:
    normalized_answer = normalize_text(answer)
    matched = 0

    for item in expected:
        normalized_item = normalize_text(item)
        if not normalized_item:
            continue

        if normalized_item in normalized_answer:
            matched += 1
            continue

        item_tokens = meaningful_tokens(normalized_item)
        answer_tokens = meaningful_tokens(normalized_answer)
        token_coverage = (
            len(item_tokens & answer_tokens) / len(item_tokens)
            if item_tokens
            else 0
        )
        similarity = SequenceMatcher(
            None,
            normalized_item,
            normalized_answer,
        ).ratio()

        if token_coverage >= 0.85 or similarity >= 0.86:
            matched += 1

    return matched


def semantic_text_match_score(answer: str, expected: str) -> float:
    normalized_answer = normalize_text(answer)
    normalized_expected = normalize_text(expected)

    if not normalized_answer or not normalized_expected:
        return 0.0
    if normalized_answer == normalized_expected:
        return 1.0
    if normalized_expected in normalized_answer or normalized_answer in normalized_expected:
        shorter = min(len(normalized_answer), len(normalized_expected))
        longer = max(len(normalized_answer), len(normalized_expected))
        return shorter / longer if longer else 0.0

    answer_tokens = meaningful_tokens(normalized_answer)
    expected_tokens = meaningful_tokens(normalized_expected)
    token_coverage = (
        len(answer_tokens & expected_tokens) / len(expected_tokens)
        if expected_tokens
        else 0.0
    )
    sequence_similarity = SequenceMatcher(
        None,
        normalized_answer,
        normalized_expected,
    ).ratio()

    return max(token_coverage, sequence_similarity)


def meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) >= 2
    }


def normalize_question_type(raw: str, choices: list[str]) -> str:
    normalized = normalize_text(raw)
    if choices:
        return "true_false" if len(choices) == 2 and all(normalize_text(item) in {"vrai", "faux", "true", "false"} for item in choices) else "qcm"
    if "figure" in normalized or "style" in normalized:
        return "figure_style"
    if "justification" in normalized or "justifie" in normalized:
        return "justification"
    if "interpretation" in normalized:
        return "interpretation"
    if "langue" in normalized or "grammaire" in normalized:
        return "langue"
    if "long" in normalized or "production" in normalized:
        return "response_long"
    if "vrai" in normalized and "faux" in normalized:
        return "true_false"
    return "response_short"


def infer_competence(question: str, question_type: str) -> str:
    normalized = normalize_text(question)
    if question_type == "figure_style" or "figure" in normalized:
        return "Figures de style"
    if question_type == "justification" or "justifie" in normalized:
        return "Justification"
    if question_type == "interpretation":
        return "Interprétation"
    if question_type == "langue":
        return "Langue"
    return "Compréhension"


def normalize_text(value: Any) -> str:
    clean = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    ).lower()
    clean = clean.replace("’", "'")
    return re.sub(r"[^a-z0-9']+", " ", clean).strip()


def has_text(block: dict) -> bool:
    return bool(text_from_block(block).strip())


def text_from_block(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return first_text(content.get("correction"), content.get("solution"), content.get("explanation"), content.get("answer"))
    return first_text(block.get("correction"), block.get("solution"), block.get("explanation"))


def normalize_type(value: Any) -> str:
    return normalize_text(value).replace(" ", "_") or "paragraph"


def default_explanation(correct: bool, question_type: str) -> str:
    if correct:
        return "La réponse correspond aux éléments attendus."
    if question_type == "figure_style":
        return "La figure attendue ne correspond pas à la réponse proposée."
    return "La réponse ne correspond pas à la correction attendue."
