from __future__ import annotations

from datetime import date, datetime
import json
import re
import unicodedata
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import (
    Assessment,
    AssessmentAnswer,
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentQuestion,
    CourseProgress,
    LiteraryWork,
    RegionalExamProfile,
    RemediationPlan,
    Skill,
    StudyPath,
    UserProfile,
)

from app.services import regional_auto_grader_service, student_weakness_model_service

REGIONAL_TRAINING_LABEL = "Entraînement pédagogique"
REGIONAL_INSPIRED_LABEL = "Entraînement inspiré des examens régionaux"


def get_student_preparation(db: Session, student: UserProfile) -> dict:
    profile = db.scalars(
        select(RegionalExamProfile)
        .where(RegionalExamProfile.student_id == student.id)
        .order_by(RegionalExamProfile.updated_at.desc())
    ).first()
    progress_rows = list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == student.id)))
    regional_attempts = list_regional_attempt_models(db, student)
    assigned = list_regional_assignment_models(db, student)
    study_path = db.scalars(
        select(StudyPath)
        .where(StudyPath.student_id == student.id, StudyPath.active.is_(True))
        .order_by(StudyPath.updated_at.desc())
    ).first()
    course_ids = {row.course_id for row in progress_rows}
    course_ids.update(assignment.assessment.course_id for assignment in assigned if assignment.assessment)
    works = list(db.scalars(select(LiteraryWork).where(LiteraryWork.course_id.in_(course_ids)))) if course_ids else []
    readiness = calculate_readiness(progress_rows, regional_attempts, study_path)
    weakness_prediction = student_weakness_model_service.predict_student_weaknesses(db, student)
    exams = [serialize_regional_exam_card(db, assignment, student) for assignment in assigned]
    completed_attempts = [attempt for attempt in regional_attempts if attempt.completed]
    best_score = max((attempt.percentage for attempt in completed_attempts), default=None)
    latest_attempt = completed_attempts[0] if completed_attempts else None
    if profile:
        profile.readiness_score = readiness["score"]
        profile.readiness_details = {
            **readiness,
            "regional_exam_count": len(exams),
            "best_score": best_score,
            "latest_attempt_id": latest_attempt.id if latest_attempt else None,
        }
        db.commit()

    return {
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "school_year": student.school_year or "1ere Bac",
            "region": student.region,
            "academic_year": student.academic_year,
            "study_stream": student.study_stream,
        },
        "days_remaining": days_remaining(profile.exam_date if profile else student.regional_exam_date),
        "readiness": readiness,
        "works": [
            {
                "id": work.id,
                "title": work.title,
                "author": work.author,
                "genre": work.genre,
                "chapters_count": len(work.chapters or []),
            }
            for work in works
        ],
        "progression": {
            "global": round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0,
            "chapters_completed": sum(completed_chapters(row.chapters) for row in progress_rows),
        },
        "regional_exams": exams,
        "regional_exam_stats": build_regional_stats(exams, completed_attempts),
        "next_mock_exam": next_regional_exam(exams),
        "weak_points": weakness_prediction.get("weak_points") or weak_points(db, regional_attempts),
        "weakness_prediction": weakness_prediction,
        "study_path": {"id": study_path.id, "title": study_path.title, "progress_percentage": study_path.progress_percentage} if study_path else None,
    }


def list_regional_exams(
    db: Session,
    student: UserProfile,
    filters: dict[str, str | None] | None = None,
) -> dict:
    filters = filters or {}
    cards = [serialize_regional_exam_card(db, assignment, student) for assignment in list_regional_assignment_models(db, student)]
    filtered = [card for card in cards if regional_card_matches(card, filters)]
    return {
        "total": len(filtered),
        "filters": build_filter_options(cards),
        "exams": filtered,
        "stats": build_regional_stats_from_cards(cards),
        "empty_message": "Aucun examen régional n'est encore disponible. Continuez vos cours et exercices en attendant une nouvelle évaluation.",
    }


def get_regional_exam(db: Session, student: UserProfile, exam_id: int) -> dict:
    assignment = get_regional_assignment(db, student, exam_id)
    return serialize_regional_exam_detail(db, assignment.assessment, student, include_correction=False)


def start_regional_exam(db: Session, student: UserProfile, exam_id: int) -> dict:
    assignment = get_regional_assignment(db, student, exam_id)
    assessment = assignment.assessment
    enforce_regional_assessment_available(assessment)
    if completed_attempt_count(db, student, assessment) >= assessment.max_attempts:
        raise HTTPException(status_code=409, detail="Nombre maximal de tentatives atteint")
    attempt = db.scalars(
        select(AssessmentAttempt).where(
            AssessmentAttempt.assessment_id == assessment.id,
            AssessmentAttempt.student_id == student.id,
            AssessmentAttempt.completed.is_(False),
        )
    ).first()
    if attempt is None:
        attempt = AssessmentAttempt(
            assessment_id=assessment.id,
            student_id=student.id,
            attempt_number=next_attempt_number(db, student, assessment),
            completed=False,
        )
        db.add(attempt)
    assignment.status = "in_progress"
    db.commit()
    db.refresh(attempt)
    return {
        "attempt_id": attempt.id,
        "exam_id": assessment.id,
        "status": "in_progress",
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "attempt_number": attempt.attempt_number,
    }


def submit_regional_exam(db: Session, student: UserProfile, exam_id: int, payload: dict) -> dict:
    assignment = get_regional_assignment(db, student, exam_id)
    assessment = assignment.assessment
    enforce_regional_assessment_available(assessment)
    attempt = resolve_regional_attempt_for_submit(db, student, assessment, payload)
    answers = normalize_answers(payload.get("answers") or {})
    answer_times = normalize_answer_times(payload.get("time_spent_seconds") or payload.get("answer_times") or {})
    now = datetime.utcnow()
    total_points = 0.0
    awarded = 0.0
    questions_to_grade = active_questions(assessment)
    grading_results = regional_auto_grader_service.grade_exam_answers(questions_to_grade, answers)
    feedback_records: dict[str, dict[str, Any]] = {}
    attempt.answers.clear()
    db.flush()
    for question in questions_to_grade:
        selected = str(answers.get(str(question.id), "") or "").strip()
        evaluation = grading_results.get(question.id) or score_regional_answer(question, selected)
        points = float(question.points or 1)
        total_points += points
        awarded += evaluation["points_awarded"]
        feedback_records[str(question.id)] = evaluation
        attempt.answers.append(
            AssessmentAnswer(
                question_id=question.id,
                selected_answer=selected,
                correct=evaluation["correct"],
                points_awarded=evaluation["points_awarded"],
                response_time_seconds=0,
                time_spent_seconds=validate_time_spent(answer_times.get(str(question.id))),
            )
        )
    attempt.submitted_at = now
    attempt.completed = True
    attempt.duration_seconds = int(payload.get("duration_seconds") or max(0, (now - attempt.started_at).total_seconds()))
    attempt.score = round(awarded, 2)
    attempt.percentage = round((awarded / total_points) * 100, 2) if total_points else 0
    assignment.status = "completed"
    db.commit()
    db.refresh(attempt)
    regional_auto_grader_service.save_attempt_feedback(attempt.id, feedback_records)
    return serialize_regional_attempt(db, attempt, include_correction=True)


def list_regional_attempts(db: Session, student: UserProfile, exam_id: int) -> dict:
    get_regional_assignment(db, student, exam_id)
    attempts = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.assessment_id == exam_id, AssessmentAttempt.student_id == student.id)
        .options(selectinload(AssessmentAttempt.assessment))
        .order_by(AssessmentAttempt.started_at.desc())
    ).all()
    return {
        "exam_id": exam_id,
        "total": len(attempts),
        "attempts": [serialize_regional_attempt_summary(attempt) for attempt in attempts],
    }


def get_regional_attempt(db: Session, student: UserProfile, attempt_id: int) -> dict:
    attempt = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.id == attempt_id)
        .options(
            selectinload(AssessmentAttempt.assessment).selectinload(Assessment.questions).selectinload(AssessmentQuestion.skill),
            selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.skill),
        )
    ).first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Tentative introuvable")
    if attempt.student_id != student.id:
        raise HTTPException(status_code=403, detail="Tentative non autorisée")
    if not is_regional_assessment(attempt.assessment):
        raise HTTPException(status_code=404, detail="Tentative régionale introuvable")
    return serialize_regional_attempt(db, attempt, include_correction=attempt.completed)


def list_regional_assignment_models(db: Session, student: UserProfile) -> list[AssessmentAssignment]:
    assignments = db.scalars(
        select(AssessmentAssignment)
        .where(AssessmentAssignment.student_id == student.id)
        .options(
            selectinload(AssessmentAssignment.assessment).selectinload(Assessment.course),
            selectinload(AssessmentAssignment.assessment).selectinload(Assessment.questions).selectinload(AssessmentQuestion.skill),
            selectinload(AssessmentAssignment.classroom),
        )
        .order_by(AssessmentAssignment.assigned_at.desc())
    ).all()
    return [assignment for assignment in assignments if assignment.assessment and is_visible_regional(assignment.assessment)]


def list_regional_attempt_models(db: Session, student: UserProfile) -> list[AssessmentAttempt]:
    attempts = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.student_id == student.id, AssessmentAttempt.completed.is_(True))
        .options(
            selectinload(AssessmentAttempt.assessment),
            selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.skill),
        )
        .order_by(AssessmentAttempt.submitted_at.desc())
    ).all()
    return [attempt for attempt in attempts if is_regional_assessment(attempt.assessment)]


def serialize_regional_exam_card(db: Session, assignment: AssessmentAssignment, student: UserProfile) -> dict:
    assessment = assignment.assessment
    metadata = regional_metadata(assessment)
    attempts = regional_attempts_for_assessment(db, student, assessment)
    completed = [attempt for attempt in attempts if attempt.completed]
    latest = attempts[0] if attempts else None
    best_score = max((attempt.percentage for attempt in completed), default=None)
    status = regional_status(assignment, attempts)
    return {
        "id": assessment.id,
        "title": assessment.title,
        "description": clean_optional_text(assessment.description),
        "year": metadata.get("year"),
        "region": metadata.get("region"),
        "session": metadata.get("session"),
        "work_id": metadata.get("work_id"),
        "work_title": metadata.get("work_title") or infer_work_title(assessment),
        "duration_minutes": int(metadata.get("duration_minutes") or assessment.time_limit_minutes or 0),
        "total_points": regional_total_points(assessment),
        "question_count": len(active_questions(assessment)),
        "status": status,
        "best_score": best_score,
        "attempts_count": len(completed),
        "attempts_used": len(completed),
        "max_attempts": assessment.max_attempts,
        "latest_attempt": serialize_regional_attempt_summary(latest) if latest else None,
        "type": regional_type(metadata),
        "type_label": regional_type_label(metadata),
        "source_status": metadata.get("source_status") or "training",
        "assignment_status": assignment.status,
        "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
    }


def serialize_regional_exam_detail(db: Session, assessment: Assessment, student: UserProfile, include_correction: bool) -> dict:
    metadata = regional_metadata(assessment)
    card = serialize_regional_exam_card(db, get_regional_assignment(db, student, assessment.id), student)
    return {
        **card,
        "instructions": clean_instructions(assessment.instructions),
        "support_text": str(metadata.get("support_text") or ""),
        "sections": build_sections(assessment, include_correction),
        "questions": [serialize_regional_question(question, include_correction) for question in active_questions(assessment)],
        "correction_available": include_correction,
    }


def serialize_regional_question(question: AssessmentQuestion, include_correction: bool) -> dict:
    metadata = question_metadata(question)
    data = {
        "id": question.id,
        "question": question.question,
        "choices": question.choices if isinstance(question.choices, list) else [],
        "question_type": metadata.get("question_type") or infer_question_type(question),
        "competence": metadata.get("competence") or (question.skill.name if question.skill else ""),
        "section": metadata.get("section") or "Questions",
        "points": float(question.points or 1),
        "order_index": question.order_index,
    }
    if include_correction:
        data.update({
            "correct_answer": question.correct_answer,
            "correction": question.correct_answer,
            "explanation": question.explanation,
            "expected_elements": expected_elements(question),
        })
    return data


def serialize_regional_attempt(db: Session, attempt: AssessmentAttempt, include_correction: bool) -> dict:
    assessment = attempt.assessment
    answers = list(attempt.answers)
    answer_by_question = {answer.question_id: answer for answer in answers}
    questions = []
    feedback_by_question = regional_auto_grader_service.load_attempt_feedback(attempt.id)
    score_by_competence: dict[str, dict[str, float]] = {}
    for question in active_questions(assessment):
        answer = answer_by_question.get(question.id)
        competence = question_metadata(question).get("competence") or (question.skill.name if question.skill else "Sans compétence")
        bucket = score_by_competence.setdefault(competence, {"score": 0.0, "max_score": 0.0})
        bucket["max_score"] += float(question.points or 1)
        if answer:
            bucket["score"] += float(answer.points_awarded or 0)
        row = serialize_regional_question(question, include_correction)
        row["selected_answer"] = answer.selected_answer if answer else ""
        row["correct"] = answer.correct if answer else False
        row["points_awarded"] = answer.points_awarded if answer else 0
        evaluation = feedback_by_question.get(str(question.id)) or {}
        if evaluation:
            row["auto_feedback"] = evaluation.get("feedback")
            row["grading_method"] = evaluation.get("grading_method")
            row["grading_details"] = evaluation.get("grading_details") or []
            row["automatically_graded"] = True
            row["teacher_validation_required"] = False
            if evaluation.get("feedback"):
                row["explanation"] = evaluation["feedback"]
        questions.append(row)
    competence_rows = [
        {
            "competence": key,
            "score": round(value["score"], 2),
            "max_score": round(value["max_score"], 2),
            "percentage": round((value["score"] / value["max_score"]) * 100, 2) if value["max_score"] else 0,
        }
        for key, value in score_by_competence.items()
    ]
    weak = [row for row in competence_rows if row["percentage"] < 70]
    return {
        "attempt_id": attempt.id,
        "exam_id": attempt.assessment_id,
        "assessment_id": attempt.assessment_id,
        "title": assessment.title if assessment else "",
        "status": "completed" if attempt.completed else "in_progress",
        "attempt_number": attempt.attempt_number,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "duration_seconds": attempt.duration_seconds,
        "score": attempt.score,
        "max_score": regional_total_points(assessment),
        "score_on_20": round((attempt.score / regional_total_points(assessment)) * 20, 2) if regional_total_points(assessment) else 0,
        "percentage": attempt.percentage,
        "score_by_competence": competence_rows,
        "weak_points": weak,
        "recommendations": build_recommendations(weak),
        "questions": questions,
        "correction_available": include_correction,
        "automatic_grading": {
            "enabled": True,
            **regional_auto_grader_service.get_grader_debug(),
        },
    }


def serialize_regional_attempt_summary(attempt: AssessmentAttempt | None) -> dict | None:
    if attempt is None:
        return None
    return {
        "attempt_id": attempt.id,
        "exam_id": attempt.assessment_id,
        "status": "completed" if attempt.completed else "in_progress",
        "attempt_number": attempt.attempt_number,
        "score": attempt.score,
        "percentage": attempt.percentage,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
    }


def get_regional_assignment(db: Session, student: UserProfile, exam_id: int) -> AssessmentAssignment:
    assignment = db.scalars(
        select(AssessmentAssignment)
        .where(AssessmentAssignment.assessment_id == exam_id, AssessmentAssignment.student_id == student.id)
        .options(
            selectinload(AssessmentAssignment.assessment).selectinload(Assessment.course),
            selectinload(AssessmentAssignment.assessment).selectinload(Assessment.questions).selectinload(AssessmentQuestion.skill),
        )
    ).first()
    if assignment is None or not assignment.assessment or not is_visible_regional(assignment.assessment):
        raise HTTPException(status_code=404, detail="Examen régional introuvable")
    return assignment


def is_visible_regional(assessment: Assessment) -> bool:
    return is_regional_assessment(assessment) and assessment.status == "published" and not is_future_or_expired(assessment)


def is_regional_assessment(assessment: Assessment | None) -> bool:
    if assessment is None:
        return False
    metadata = regional_metadata(assessment)
    if metadata.get("is_regional_exam") is True or metadata.get("exam_kind") == "regional":
        return True
    searchable = " ".join([assessment.title or "", assessment.description or "", assessment.instructions or ""]).lower()
    return "regional" in searchable or "régional" in searchable


def regional_metadata(assessment: Assessment) -> dict:
    for raw in (assessment.description, assessment.instructions):
        data = parse_json_object(raw)
        if not data:
            continue
        if isinstance(data.get("regional_exam"), dict):
            return data["regional_exam"]
        if data.get("is_regional_exam") is True or data.get("exam_kind") == "regional":
            return data
    return {}


def question_metadata(question: AssessmentQuestion) -> dict:
    return parse_json_object(question.adaptation_reason) or {}


def parse_json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip().startswith("{"):
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def clean_optional_text(value: str | None) -> str:
    if not value:
        return ""
    return "" if value.strip().startswith("{") else value


def clean_instructions(value: str | None) -> str:
    if not value:
        return "Répondez aux questions puis soumettez votre examen."
    return "Répondez aux questions puis soumettez votre examen." if value.strip().startswith("{") else value


def build_sections(assessment: Assessment, include_correction: bool) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for question in active_questions(assessment):
        section = question_metadata(question).get("section") or "Questions"
        grouped.setdefault(section, []).append(serialize_regional_question(question, include_correction))
    return [{"title": title, "questions": rows} for title, rows in grouped.items()]


def active_questions(assessment: Assessment | None) -> list[AssessmentQuestion]:
    if not assessment:
        return []
    return sorted([question for question in assessment.questions if question.active], key=lambda item: (item.order_index, item.id or 0))


def infer_question_type(question: AssessmentQuestion) -> str:
    metadata = question_metadata(question)
    if metadata.get("question_type"):
        return str(metadata["question_type"])
    choices = question.choices if isinstance(question.choices, list) else []
    if choices:
        return "qcm"
    text = (question.question or "").lower()
    if "rédige" in text or "redige" in text or "production" in text:
        return "response_long"
    return "response_short"


def regional_type(metadata: dict) -> str:
    value = str(metadata.get("type") or metadata.get("source_status") or "training").lower()
    return "official" if value in {"official", "officiel", "verified_official"} else "training"


def regional_type_label(metadata: dict) -> str:
    return "Officiel vérifié" if regional_type(metadata) == "official" else REGIONAL_INSPIRED_LABEL


def infer_work_title(assessment: Assessment) -> str:
    metadata = regional_metadata(assessment)
    if metadata.get("work_title"):
        return str(metadata["work_title"])
    return assessment.course.title if assessment.course else ""


def regional_total_points(assessment: Assessment | None) -> float:
    return round(sum(float(question.points or 1) for question in active_questions(assessment)), 2)


def regional_status(assignment: AssessmentAssignment, attempts: list[AssessmentAttempt]) -> str:
    if any(attempt.completed for attempt in attempts):
        return "terminé"
    if any(not attempt.completed for attempt in attempts) or assignment.status == "in_progress":
        return "en cours"
    return "non commencé"


def regional_attempts_for_assessment(db: Session, student: UserProfile, assessment: Assessment) -> list[AssessmentAttempt]:
    return list(db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.assessment_id == assessment.id, AssessmentAttempt.student_id == student.id)
        .options(selectinload(AssessmentAttempt.answers))
        .order_by(AssessmentAttempt.started_at.desc())
    ))


def completed_attempt_count(db: Session, student: UserProfile, assessment: Assessment) -> int:
    return db.scalar(
        select(func.count(AssessmentAttempt.id)).where(
            AssessmentAttempt.assessment_id == assessment.id,
            AssessmentAttempt.student_id == student.id,
            AssessmentAttempt.completed.is_(True),
        )
    ) or 0


def next_attempt_number(db: Session, student: UserProfile, assessment: Assessment) -> int:
    return (db.scalar(
        select(func.count(AssessmentAttempt.id)).where(
            AssessmentAttempt.assessment_id == assessment.id,
            AssessmentAttempt.student_id == student.id,
        )
    ) or 0) + 1


def resolve_regional_attempt_for_submit(db: Session, student: UserProfile, assessment: Assessment, payload: dict) -> AssessmentAttempt:
    attempt_id = payload.get("attempt_id")
    if attempt_id:
        attempt = db.get(AssessmentAttempt, int(attempt_id))
        if attempt is None or attempt.student_id != student.id or attempt.assessment_id != assessment.id:
            raise HTTPException(status_code=404, detail="Tentative introuvable")
        if attempt.completed:
            raise HTTPException(status_code=409, detail="Tentative déjà soumise")
        return attempt
    if completed_attempt_count(db, student, assessment) >= assessment.max_attempts:
        raise HTTPException(status_code=409, detail="Nombre maximal de tentatives atteint")
    attempt = AssessmentAttempt(
        assessment_id=assessment.id,
        student_id=student.id,
        started_at=parse_datetime(payload.get("started_at")) or datetime.utcnow(),
        attempt_number=next_attempt_number(db, student, assessment),
        completed=False,
    )
    db.add(attempt)
    db.flush()
    return attempt


def score_regional_answer(question: AssessmentQuestion, selected: str) -> dict:
    return regional_auto_grader_service.grade_single_answer(question, selected)


def expected_elements(question: AssessmentQuestion) -> list[str]:
    metadata = question_metadata(question)
    values = metadata.get("expected_elements")
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    if isinstance(values, str):
        return [part.strip() for part in re.split(r"[|;,]", values) if part.strip()]
    answer = question.correct_answer or ""
    return [part.strip() for part in re.split(r"[|;]", answer) if part.strip()]


def normalize_answers(value: Any) -> dict[str, str]:
    if isinstance(value, list):
        return {str(item.get("question_id")): str(item.get("selected_answer", "") or "") for item in value if isinstance(item, dict)}
    if isinstance(value, dict):
        return {str(key): str(item or "") for key, item in value.items()}
    return {}


def normalize_answer_times(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {str(item.get("question_id")): item.get("time_spent_seconds") for item in value if isinstance(item, dict)}
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def validate_time_spent(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(0, min(24 * 60 * 60, int(value)))
    except (TypeError, ValueError):
        return None


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def normalize_text(value: str) -> str:
    clean = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    ).lower()
    return re.sub(r"\s+", " ", clean).strip()


def is_future_or_expired(assessment: Assessment) -> bool:
    now = datetime.utcnow()
    return bool((assessment.publication_at and assessment.publication_at > now) or (assessment.expires_at and assessment.expires_at < now))


def enforce_regional_assessment_available(assessment: Assessment) -> None:
    if assessment.status != "published":
        raise HTTPException(status_code=404, detail="Examen régional non disponible")
    if is_future_or_expired(assessment):
        raise HTTPException(status_code=409, detail="Examen régional indisponible à cette date")


def regional_card_matches(card: dict, filters: dict[str, str | None]) -> bool:
    for key in ("year", "region", "work_id", "session", "status"):
        expected = filters.get(key)
        if expected and str(card.get(key) or "") != str(expected):
            return False
    search = normalize_text(filters.get("search") or "")
    if search:
        haystack = normalize_text(" ".join(str(card.get(key) or "") for key in ("title", "description", "region", "work_title", "session", "type_label")))
        if search not in haystack:
            return False
    return True


def build_filter_options(cards: list[dict]) -> dict:
    def unique(key: str) -> list:
        return sorted({card.get(key) for card in cards if card.get(key)})

    works_by_key: dict[str, tuple[Any, str]] = {}
    for card in cards:
        work_id = card.get("work_id")
        work_title = card.get("work_title")
        if work_id or work_title:
            key = str(work_id or work_title)
            works_by_key[key] = (work_id or work_title, work_title or str(work_id))

    return {
        "years": unique("year"),
        "regions": unique("region"),
        "works": sorted(works_by_key.values(), key=lambda item: str(item[1] or item[0])),
        "sessions": unique("session"),
        "statuses": unique("status"),
    }


def build_regional_stats_from_cards(cards: list[dict]) -> dict:
    return {
        "total_exams": len(cards),
        "completed_exams": sum(1 for card in cards if card["status"] == "terminé"),
        "in_progress_exams": sum(1 for card in cards if card["status"] == "en cours"),
        "best_score": max((card["best_score"] for card in cards if card["best_score"] is not None), default=None),
        "attempts_count": sum(card["attempts_count"] for card in cards),
    }


def build_regional_stats(exams: list[dict], attempts: list[AssessmentAttempt]) -> dict:
    stats = build_regional_stats_from_cards(exams)
    completed = [attempt for attempt in attempts if attempt.completed]
    latest = completed[0] if completed else None
    previous = completed[1] if len(completed) > 1 else None
    stats["latest_attempt"] = serialize_regional_attempt_summary(latest) if latest else None
    stats["progress_between_attempts"] = round(latest.percentage - previous.percentage, 2) if latest and previous else None
    return stats


def calculate_readiness(progress_rows: list[CourseProgress], attempts: list[AssessmentAttempt], study_path: StudyPath | None) -> dict:
    progress_score = round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0
    assessment_score = round(sum(attempt.percentage for attempt in attempts[:5]) / min(len(attempts), 5), 2) if attempts else 0
    path_score = study_path.progress_percentage if study_path else 0
    score = round((progress_score * 0.4) + (assessment_score * 0.4) + (path_score * 0.2), 2)
    return {
        "score": score,
        "label": "Indicateur pédagogique de préparation",
        "progress_component": progress_score,
        "assessment_component": assessment_score,
        "study_path_component": path_score,
        "certainty": "Non predictif",
    }


def days_remaining(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return (date.fromisoformat(value) - date.today()).days
    except ValueError:
        return None


def completed_chapters(chapters) -> int:
    if not isinstance(chapters, list):
        return 0
    return sum(1 for chapter in chapters if chapter.get("completed") or chapter.get("status") == "completed")


def next_regional_exam(exams: list[dict]) -> dict | None:
    for exam in exams:
        if exam["status"] != "terminé":
            return {"id": exam["id"], "title": exam["title"], "status": exam["status"]}
    return None


def weak_points(db: Session, attempts: list[AssessmentAttempt]) -> list[dict]:
    weak: dict[str, dict] = {}
    for attempt in attempts:
        report = serialize_regional_attempt(db, attempt, include_correction=False)
        for item in report["weak_points"]:
            key = item["competence"]
            current = weak.get(key)
            if current is None or item["percentage"] < current["score"]:
                weak[key] = {
                    "assessment_id": attempt.assessment_id,
                    "score": item["percentage"],
                    "message": f"Revoir la compétence : {key}.",
                    "competence": key,
                }
    return list(weak.values())[:5]


def build_recommendations(weak_rows: list[dict]) -> list[str]:
    if not weak_rows:
        return ["Conserver le rythme de révision et refaire un entraînement complet avant l'examen."]
    return [f"Revoir les exercices liés à {row['competence']}." for row in weak_rows[:5]]
