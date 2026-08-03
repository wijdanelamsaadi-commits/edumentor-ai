from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from statistics import median
import re
import urllib.error
import urllib.request
import unicodedata
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.roles import UserRole
from app.core.config import get_settings
from app.models.persistence import (
    AdminAuditLog,
    Assessment,
    AssessmentAnswer,
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentQuestion,
    Classroom,
    ClassroomMembership,
    Course,
    CourseChapter,
    DiagnosticResult,
    MasteryThreshold,
    Notification,
    PersonalizedLesson,
    Quiz,
    RemediationItem,
    RemediationPlan,
    Skill,
    UserProfile,
)
from app.services import course_service, personalized_lesson_service, rag_document_service, study_path_service
from app.services.groq_service import GROQ_CHAT_COMPLETIONS_URL

ASSESSMENT_TYPES = {"initial", "personalized", "final", "practice"}
ASSESSMENT_STATUSES = {"draft", "scheduled", "published", "closed", "archived"}
ITEM_TYPES = {"lesson", "chapter", "explanation", "example", "exercise", "chatbot_context", "revision"}
FORBIDDEN_PROPOSAL_TEXT = {
    "quel est le point essentiel du chapitre",
    "ignorer les objectifs",
    "changer de cours sans revision",
    "memoriser uniquement les titres",
    "mémoriser uniquement les titres",
}
PERSONALIZED_SIMILARITY_THRESHOLD = 0.82
PERSONALIZED_MIN_QUESTIONS = 3
PERSONALIZED_MAX_QUESTIONS = 10


def is_admin(user: UserProfile) -> bool:
    return user.role == UserRole.ADMIN.value


def list_professor_classrooms(db: Session, user: UserProfile) -> list[dict]:
    query = select(Classroom).options(selectinload(Classroom.memberships).selectinload(ClassroomMembership.student)).order_by(Classroom.updated_at.desc())
    if not is_admin(user):
        query = query.where(Classroom.professor_id == user.id)
    return [serialize_classroom(item, include_students=True) for item in db.scalars(query)]


def create_classroom(db: Session, user: UserProfile, payload: dict) -> dict:
    if not str(payload.get("name", "")).strip():
        raise HTTPException(status_code=422, detail="Le nom de la classe est obligatoire")
    code = str(payload.get("code") or "").strip().upper() or generate_class_code(db)
    classroom = Classroom(
        name=str(payload["name"]).strip(),
        code=code,
        professor_id=user.id,
        subject_id=payload.get("subject_id"),
        education_level_id=payload.get("education_level_id"),
        academic_year=payload.get("academic_year"),
        description=payload.get("description"),
        active=payload.get("active", True) is not False,
    )
    db.add(classroom)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ce code de classe existe deja") from exc
    db.refresh(classroom)
    return serialize_classroom(classroom, include_students=True)


def get_professor_classroom(db: Session, user: UserProfile, classroom_id: int) -> dict:
    classroom = get_owned_classroom(db, user, classroom_id)
    return serialize_classroom(classroom, include_students=True)


def update_classroom(db: Session, user: UserProfile, classroom_id: int, payload: dict) -> dict:
    classroom = get_owned_classroom(db, user, classroom_id)
    for field in ["name", "subject_id", "education_level_id", "academic_year", "description", "active"]:
        if field in payload:
            setattr(classroom, field, payload[field])
    if "code" in payload:
        classroom.code = str(payload["code"]).strip().upper()
    classroom.updated_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ce code de classe existe deja") from exc
    db.refresh(classroom)
    return serialize_classroom(classroom, include_students=True)


def add_student_to_classroom(db: Session, user: UserProfile, classroom_id: int, payload: dict) -> dict:
    classroom = get_owned_classroom(db, user, classroom_id)
    student = resolve_student(db, payload)
    membership = db.scalars(
        select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom.id,
            ClassroomMembership.student_id == student.id,
        )
    ).first()
    if membership:
        membership.active = True
    else:
        membership = ClassroomMembership(classroom_id=classroom.id, student_id=student.id, active=True)
        db.add(membership)
    db.commit()
    db.refresh(membership)
    return serialize_membership(membership)


def remove_student_from_classroom(db: Session, user: UserProfile, classroom_id: int, student_id: int) -> dict:
    get_owned_classroom(db, user, classroom_id)
    membership = db.scalars(
        select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.student_id == student_id,
        )
    ).first()
    if membership is None:
        raise HTTPException(status_code=404, detail="Etudiant non inscrit dans cette classe")
    membership.active = False
    db.commit()
    return {"removed": True, "student_id": student_id, "classroom_id": classroom_id}


def list_student_classrooms(db: Session, user: UserProfile) -> list[dict]:
    memberships = db.scalars(
        select(ClassroomMembership)
        .where(ClassroomMembership.student_id == user.id, ClassroomMembership.active.is_(True))
        .options(selectinload(ClassroomMembership.classroom))
        .order_by(ClassroomMembership.joined_at.desc())
    ).all()
    return [serialize_classroom(item.classroom, include_students=False) for item in memberships]


def get_student_dashboard(db: Session, user: UserProfile) -> dict:
    assignments = db.scalars(
        select(AssessmentAssignment)
        .where(AssessmentAssignment.student_id == user.id)
        .options(selectinload(AssessmentAssignment.assessment).selectinload(Assessment.course))
        .order_by(AssessmentAssignment.assigned_at.desc())
    ).all()
    assessments = [assignment.assessment for assignment in assignments]
    attempts = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.student_id == user.id)
        .options(
            selectinload(AssessmentAttempt.assessment),
            selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.skill),
            selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.chapter),
        )
        .order_by(AssessmentAttempt.submitted_at.desc())
    ).all()
    diagnostic_results = db.scalars(
        select(DiagnosticResult)
        .where(DiagnosticResult.user_id == user.id)
        .options(selectinload(DiagnosticResult.subject))
        .order_by(DiagnosticResult.created_at.desc(), DiagnosticResult.id.desc())
    ).all()
    latest_diagnostic = next(
        (
            result
            for result in diagnostic_results
            if is_french_subject(result.subject)
        ),
        None,
    )
    active_plans = db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.student_id == user.id, RemediationPlan.status == "active")
        .options(selectinload(RemediationPlan.items), selectinload(RemediationPlan.course))
        .order_by(RemediationPlan.created_at.desc())
    ).all()
    now = datetime.utcnow()
    available = [assessment for assessment in assessments if is_visible_to_student(assessment) and not _has_completed_attempt(attempts, assessment.id)]
    upcoming = [assessment for assessment in assessments if assessment.publication_at and assessment.publication_at > now]
    due_soon = [
        assessment
        for assessment in assessments
        if assessment.expires_at and assessment.expires_at >= now and assessment.status == "published"
    ]
    latest_attempt = attempts[0] if attempts else None
    weakest_skill = None
    if latest_attempt:
        skill_rows = aggregate_by_dimension(db, list(latest_attempt.answers), "skill")
        weak_rows = [row for row in skill_rows if row["id"] is not None]
        weakest_skill = sorted(weak_rows, key=lambda row: row["percentage"])[0] if weak_rows else None
    if weakest_skill is None and latest_diagnostic:
        weakest_skill = weakest_diagnostic_competence(latest_diagnostic)
    active_plan = active_plans[0] if active_plans else None
    active_study_path = study_path_service.get_active_path_summary(db, user)
    personalized_available = [
        assessment for assessment in available if assessment.assessment_type == "personalized"
    ]
    next_action = active_study_path["next_action"] if active_study_path else build_student_next_action(available, active_plan, personalized_available, weakest_skill)

    return {
        "available_assessments": [serialize_assessment(item, include_answers=False) for item in available[:5]],
        "available_count": len(available),
        "upcoming_assessments": [serialize_assessment(item, include_answers=False) for item in upcoming[:5]],
        "upcoming_count": len(upcoming),
        "near_deadlines": [serialize_assessment(item, include_answers=False) for item in sorted(due_soon, key=lambda item: item.expires_at)[:5]],
        "latest_result": serialize_attempt_report(db, latest_attempt, include_answers=False) if latest_attempt else serialize_diagnostic_dashboard_result(latest_diagnostic),
        "weakest_skill": weakest_skill,
        "active_remediation": serialize_remediation_plan(active_plan) if active_plan else None,
        "active_study_path": active_study_path,
        "personalized_assessment_available": serialize_assessment(personalized_available[0], include_answers=False) if personalized_available else None,
        "next_action": next_action,
    }


def is_french_subject(subject) -> bool:
    if subject is None:
        return False
    value = f"{getattr(subject, 'slug', '')} {getattr(subject, 'name', '')}"
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).lower()
    return "francais" in normalized


DIAGNOSTIC_COMPETENCE_LABELS = {
    "comprehension": "Compréhension",
    "langue_grammaire": "Langue et grammaire",
    "connaissance_oeuvres": "Connaissance des œuvres",
    "figures_procedes": "Figures de style et procédés",
    "interpretation_justification": "Interprétation et justification",
}


def weakest_diagnostic_competence(result: DiagnosticResult) -> dict | None:
    rows = [
        row for row in (result.results_by_topic or [])
        if isinstance(row, dict) and row.get("name") is not None
    ]
    if not rows:
        return None
    weakest = min(rows, key=lambda row: float(row.get("percentage") or 0))
    raw_name = str(weakest.get("name") or "")
    return {
        "id": None,
        "name": DIAGNOSTIC_COMPETENCE_LABELS.get(
            raw_name,
            raw_name.replace("_", " ").title(),
        ),
        "percentage": float(weakest.get("percentage") or 0),
        "source": "diagnostic",
    }


def serialize_diagnostic_dashboard_result(result: DiagnosticResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "id": result.id,
        "percentage": float(result.score or 0),
        "score": float(result.score or 0),
        "level": result.level,
        "subject_id": result.subject_id,
        "source": "diagnostic",
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


def list_student_remediation_plans(db: Session, user: UserProfile) -> list[dict]:
    plans = db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.student_id == user.id)
        .options(selectinload(RemediationPlan.items), selectinload(RemediationPlan.course))
        .order_by(RemediationPlan.created_at.desc())
    ).all()
    return [serialize_remediation_plan(plan) for plan in plans]


def list_professor_assessments(db: Session, user: UserProfile) -> list[dict]:
    query = select(Assessment).options(*assessment_options()).order_by(Assessment.updated_at.desc())
    if not is_admin(user):
        query = query.where(Assessment.professor_id == user.id)
    return [serialize_assessment(item, include_answers=True) for item in db.scalars(query)]


def create_assessment(db: Session, user: UserProfile, payload: dict) -> dict:
    course = db.get(Course, int(payload.get("course_id") or 0))
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if not is_admin(user) and course.professor_id != user.id:
        raise HTTPException(status_code=403, detail="Cours non autorise")
    subject_id = int(payload.get("subject_id") or course.subject_id or 0)
    if not subject_id:
        raise HTTPException(status_code=422, detail="La matiere est obligatoire")
    classroom_id = payload.get("classroom_id")
    if classroom_id is not None:
        get_owned_classroom(db, user, int(classroom_id))

    assessment = Assessment(
        professor_id=user.id,
        classroom_id=classroom_id,
        course_id=course.id,
        subject_id=subject_id,
        title=str(payload.get("title") or f"Evaluation - {course.title}").strip(),
        description=payload.get("description") or "",
        instructions=payload.get("instructions") or "",
        assessment_type=validate_choice(payload.get("assessment_type", "initial"), ASSESSMENT_TYPES, "Type d'evaluation invalide"),
        status=validate_choice(payload.get("status", "draft"), ASSESSMENT_STATUSES, "Statut invalide"),
        difficulty_level_id=payload.get("difficulty_level_id"),
        publication_at=parse_datetime(payload.get("publication_at")),
        expires_at=parse_datetime(payload.get("expires_at")),
        time_limit_minutes=payload.get("time_limit_minutes"),
        max_attempts=max(1, int(payload.get("max_attempts") or 1)),
    )
    db.add(assessment)
    db.flush()
    replace_assessment_questions(db, assessment, payload.get("questions") or [])
    create_audit_log(db, user, "create_assessment", "assessment", assessment.id, None, {"title": assessment.title})
    db.commit()
    db.refresh(assessment)
    return serialize_assessment(assessment, include_answers=True)


def get_professor_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_assessment(db, user, assessment_id)
    return serialize_assessment(assessment, include_answers=True)


def update_assessment(db: Session, user: UserProfile, assessment_id: int, payload: dict) -> dict:
    assessment = get_owned_assessment(db, user, assessment_id)
    if assessment.status in {"closed", "archived"} and "questions" in payload:
        raise HTTPException(status_code=409, detail="Evaluation fermee non modifiable")
    before = serialize_assessment(assessment, include_answers=True)
    for field in ["title", "description", "instructions", "difficulty_level_id", "time_limit_minutes", "max_attempts"]:
        if field in payload:
            setattr(assessment, field, payload[field])
    if "assessment_type" in payload:
        assessment.assessment_type = validate_choice(payload["assessment_type"], ASSESSMENT_TYPES, "Type d'evaluation invalide")
    if "status" in payload:
        assessment.status = validate_choice(payload["status"], ASSESSMENT_STATUSES, "Statut invalide")
    if "publication_at" in payload:
        assessment.publication_at = parse_datetime(payload.get("publication_at"))
    if "expires_at" in payload:
        assessment.expires_at = parse_datetime(payload.get("expires_at"))
    if "questions" in payload:
        replace_assessment_questions(db, assessment, payload.get("questions") or [])
    assessment.updated_at = datetime.utcnow()
    create_audit_log(db, user, "update_assessment", "assessment", assessment.id, before, {"title": assessment.title})
    db.commit()
    db.refresh(assessment)
    return serialize_assessment(assessment, include_answers=True)


def delete_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_assessment(db, user, assessment_id)
    if assessment.attempts:
        assessment.status = "archived"
        db.commit()
        return {"archived": True, "assessment_id": assessment_id}
    db.delete(assessment)
    db.commit()
    return {"deleted": True, "assessment_id": assessment_id}


def publish_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_assessment(db, user, assessment_id)
    if assessment.assessment_type == "personalized":
        return publish_personalized_assessment(db, user, assessment_id)
    active_questions = [question for question in assessment.questions if question.active]
    if len(active_questions) < 2:
        raise HTTPException(status_code=422, detail="Ajoutez au moins deux questions avant publication")
    for question in active_questions:
        validate_question_payload(
            db,
            assessment,
            {
                "question": question.question,
                "choices": question.choices,
                "correct_answer": question.correct_answer,
                "chapter_id": question.chapter_id,
                "skill_id": question.skill_id,
            },
        )
    if assessment.classroom_id is None:
        raise HTTPException(status_code=422, detail="Associez une classe avant publication")
    active_members = active_classroom_memberships(db, assessment.classroom_id)
    if not active_members:
        raise HTTPException(status_code=422, detail="La classe associee ne contient aucun etudiant actif")
    assessment.status = "published"
    assessment.publication_at = assessment.publication_at or datetime.utcnow()
    assigned_count = assign_assessment_to_classroom(db, assessment, active_members)
    for membership in active_members:
        create_notification(db, membership.student_id, "assessment", "Nouveau test publie", f"{assessment.title} est disponible.")
    create_audit_log(db, user, "publish_assessment", "assessment", assessment.id, None, {"status": "published"})
    db.commit()
    db.refresh(assessment)
    data = serialize_assessment(assessment, include_answers=True)
    data["assigned_student_count"] = assigned_count
    return data


def close_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_assessment(db, user, assessment_id)
    assessment.status = "closed"
    db.commit()
    return serialize_assessment(assessment, include_answers=True)


def get_professor_personalized_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_personalized_assessment(db, user, assessment_id)
    return serialize_assessment(assessment, include_answers=True)


def add_personalized_assessment_question(db: Session, user: UserProfile, assessment_id: int, payload: dict) -> dict:
    assessment = get_owned_personalized_assessment(db, user, assessment_id)
    if assessment.status not in {"draft", "scheduled"}:
        raise HTTPException(status_code=409, detail="Seul un test personnalise brouillon peut etre modifie")
    validate_question_payload(db, assessment, payload)
    existing = [question.question for question in assessment.questions] + source_questions_for_personalized_assessment(db, assessment)
    if max_similarity(payload["question"], existing) >= PERSONALIZED_SIMILARITY_THRESHOLD:
        raise HTTPException(status_code=422, detail="Question trop proche d'une question existante")
    question = AssessmentQuestion(
        assessment_id=assessment.id,
        chapter_id=payload.get("chapter_id"),
        skill_id=payload.get("skill_id"),
        question=str(payload["question"]).strip(),
        choices=payload.get("choices") or [],
        correct_answer=payload.get("correct_answer") or payload.get("answer"),
        explanation=payload.get("explanation") or "",
        difficulty_level_id=payload.get("difficulty_level_id"),
        points=float(payload.get("points") or 1),
        order_index=int(payload.get("order_index") or len(assessment.questions) + 1),
        active=payload.get("active", True) is not False,
        source_document_id=payload.get("source_document_id"),
        source_page_start=payload.get("source_page_start"),
        source_page_end=payload.get("source_page_end"),
        source_attempt_id=payload.get("source_attempt_id"),
        source_question_id=payload.get("source_question_id"),
        generation_method=payload.get("generation_method") or "manual",
        similarity_score=payload.get("similarity_score"),
        adaptation_reason=payload.get("adaptation_reason") or "Question ajoutee manuellement par le professeur.",
    )
    db.add(question)
    db.commit()
    db.refresh(assessment)
    return serialize_assessment(assessment, include_answers=True)


def update_personalized_assessment_question(db: Session, user: UserProfile, assessment_id: int, question_id: int, payload: dict) -> dict:
    assessment = get_owned_personalized_assessment(db, user, assessment_id)
    if assessment.status not in {"draft", "scheduled"}:
        raise HTTPException(status_code=409, detail="Seul un test personnalise brouillon peut etre modifie")
    question = next((item for item in assessment.questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable")
    data = {
        "question": payload.get("question", question.question),
        "choices": payload.get("choices", question.choices),
        "correct_answer": payload.get("correct_answer", question.correct_answer),
        "chapter_id": payload.get("chapter_id", question.chapter_id),
        "skill_id": payload.get("skill_id", question.skill_id),
    }
    validate_question_payload(db, assessment, data)
    for field in [
        "chapter_id",
        "skill_id",
        "question",
        "choices",
        "correct_answer",
        "explanation",
        "difficulty_level_id",
        "points",
        "order_index",
        "active",
        "source_document_id",
        "source_page_start",
        "source_page_end",
        "source_attempt_id",
        "source_question_id",
        "generation_method",
        "similarity_score",
        "adaptation_reason",
    ]:
        if field in payload:
            setattr(question, field, payload[field])
    if "correct_answer" not in payload and "answer" in payload:
        question.correct_answer = payload["answer"]
    assessment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assessment)
    return serialize_assessment(assessment, include_answers=True)


def delete_personalized_assessment_question(db: Session, user: UserProfile, assessment_id: int, question_id: int) -> dict:
    assessment = get_owned_personalized_assessment(db, user, assessment_id)
    if assessment.status not in {"draft", "scheduled"}:
        raise HTTPException(status_code=409, detail="Seul un test personnalise brouillon peut etre modifie")
    question = next((item for item in assessment.questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable")
    question.active = False
    assessment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(assessment)
    return serialize_assessment(assessment, include_answers=True)


def approve_personalized_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_personalized_assessment(db, user, assessment_id)
    active_questions = [question for question in assessment.questions if question.active]
    if len(active_questions) < 2:
        raise HTTPException(status_code=422, detail="Ajoutez au moins deux questions avant validation")
    assessment.status = "scheduled"
    assessment.updated_at = datetime.utcnow()
    create_audit_log(db, user, "approve_personalized_assessment", "assessment", assessment.id, None, {"status": "scheduled"})
    db.commit()
    db.refresh(assessment)
    return serialize_assessment(assessment, include_answers=True)


def publish_personalized_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_personalized_assessment(db, user, assessment_id)
    active_questions = [question for question in assessment.questions if question.active]
    if len(active_questions) < 2:
        raise HTTPException(status_code=422, detail="Ajoutez au moins deux questions avant publication")
    for question in active_questions:
        validate_question_payload(
            db,
            assessment,
            {
                "question": question.question,
                "choices": question.choices,
                "correct_answer": question.correct_answer,
                "chapter_id": question.chapter_id,
                "skill_id": question.skill_id,
            },
        )
    source_attempt = db.get(AssessmentAttempt, active_questions[0].source_attempt_id) if active_questions[0].source_attempt_id else None
    if source_attempt is None:
        raise HTTPException(status_code=422, detail="Tentative source introuvable pour ce test personnalise")
    assessment.status = "published"
    assessment.publication_at = datetime.utcnow()
    if not db.scalars(select(AssessmentAssignment).where(AssessmentAssignment.assessment_id == assessment.id, AssessmentAssignment.student_id == source_attempt.student_id)).first():
        db.add(AssessmentAssignment(assessment_id=assessment.id, student_id=source_attempt.student_id, classroom_id=assessment.classroom_id, status="assigned"))
    create_notification(db, source_attempt.student_id, "assessment", "Test personnalise pret", f"{assessment.title} est disponible.")
    create_audit_log(db, user, "publish_personalized_assessment", "assessment", assessment.id, None, {"status": "published", "student_id": source_attempt.student_id})
    plan = db.scalars(select(RemediationPlan).where(RemediationPlan.source_attempt_id == source_attempt.id)).first()
    if plan:
        study_path_service.create_or_refresh_for_plan(db, plan)
    db.commit()
    db.refresh(assessment)
    data = serialize_assessment(assessment, include_answers=True)
    data["assigned_student_count"] = 1
    return data


def propose_questions(db: Session, user: UserProfile, assessment_id: int, payload: dict) -> dict:
    assessment = get_owned_assessment(db, user, assessment_id)
    course = course_service.get_course_model(db, assessment.course_id)
    count = max(1, min(10, int(payload.get("count") or 5)))
    chapters = sorted(
        [chapter for chapter in (course.chapters if course else []) if chapter.active],
        key=lambda chapter: chapter.position or chapter.id,
    )
    source = first_rag_document_for_course(db, assessment.course_id)
    existing_questions = {normalize_question_key(item.question) for item in assessment.questions}
    results = []

    for chapter in chapters:
        if len(results) >= count:
            break
        skill = ensure_skill_for_chapter(db, assessment.subject_id, assessment.course_id, chapter)
        question = build_question_from_chapter_blocks(
            chapter=chapter,
            assessment=assessment,
            skill=skill,
            source=source,
            order_index=len(assessment.questions) + len(results) + 1,
        )
        if question and validate_generated_question(question, assessment.course_id, {item.id for item in chapters}, existing_questions):
            results.append(question)
            existing_questions.add(normalize_question_key(question["question"]))

    return {
        "assessment_id": assessment.id,
        "questions": results,
        "requires_professor_validation": True,
        "generation_mode": "structured_content_fallback",
        "message": "" if results else "Aucune question de qualite n'a pu etre proposee depuis le contenu du cours.",
    }


def build_question_from_chapter_blocks(
    chapter: CourseChapter,
    assessment: Assessment,
    skill: Skill | None,
    source,
    order_index: int,
) -> dict | None:
    blocks = normalize_structured_blocks(chapter)
    if not blocks:
        return None

    block = select_best_question_block(blocks)
    if block is None:
        return None

    question, correct_answer, choices, explanation = build_question_text(chapter, block)
    if not question:
        return None

    page_start = block.get("source_page_start") or block.get("page") or (1 if source else None)
    page_end = block.get("source_page_end") or page_start
    return {
        "chapter_id": chapter.id,
        "skill_id": skill.id if skill else None,
        "topic": skill.name if skill else chapter.title,
        "question": question,
        "choices": choices,
        "correct_answer": correct_answer,
        "explanation": explanation,
        "difficulty_level_id": assessment.difficulty_level_id,
        "points": 1,
        "order_index": order_index,
        "active": True,
        "draft": True,
        "source_document_id": source.id if source else None,
        "source_page_start": int(page_start) if str(page_start or "").isdigit() else page_start,
        "source_page_end": int(page_end) if str(page_end or "").isdigit() else page_end,
    }


def normalize_structured_blocks(chapter: CourseChapter) -> list[dict]:
    raw_blocks = chapter.structured_content or []
    if isinstance(raw_blocks, dict):
        raw_blocks = raw_blocks.get("blocks") or raw_blocks.get("items") or []
    blocks = [block for block in raw_blocks if isinstance(block, dict) and block_content_text(block)]
    if blocks:
        return blocks
    if chapter.content and len(chapter.content.strip()) >= 40:
        return [{"type": "paragraph", "title": chapter.title, "content": chapter.content}]
    return []


def select_best_question_block(blocks: list[dict]) -> dict | None:
    priority = ["definition", "bullet_list", "key_point", "example", "warning", "summary", "paragraph"]
    for block_type in priority:
        for block in blocks:
            if str(block.get("type", "")).lower() == block_type:
                return block
    return blocks[0] if blocks else None


def build_question_text(chapter: CourseChapter, block: dict) -> tuple[str, str, list[str], str]:
    block_type = str(block.get("type") or "").lower()
    title = clean_text(block.get("title") or chapter.title)
    text = block_content_text(block)
    chapter_title = clean_text(chapter.title)
    lower_title = normalize_question_key(f"{title} {chapter_title}")
    lower_text = normalize_question_key(text)

    if "erreur de syntaxe" in lower_title or "syntaxe bloque" in lower_text:
        correct = "Une erreur de syntaxe."
        return (
            "Quelle erreur empeche generalement l'execution d'un programme ?",
            correct,
            distinct_choices([
                correct,
                "Une erreur semantique qui produit un resultat incorrect.",
                "Un commentaire trop detaille dans le code.",
                "Un nom de fichier choisi par l'utilisateur.",
            ]),
            "Une erreur de syntaxe viole les regles d'ecriture du langage et bloque souvent le lancement du programme.",
        )

    if "programmation" in lower_title:
        correct = "Traduire une idee en instructions structurees executables par un ordinateur."
        return (
            "Qu'est-ce que la programmation ?",
            correct,
            distinct_choices([
                correct,
                "Choisir une interface graphique sans definir d'instructions.",
                "Stocker des fichiers sans logique de traitement.",
                "Utiliser un ordinateur sans lui indiquer les etapes a suivre.",
            ]),
            "Le cours explique que programmer consiste a transformer une intention en instructions precises qu'un ordinateur peut executer.",
        )

    if "regles d'or" in lower_text or "commentaires utiles" in lower_text or "bien programmer" in lower_title:
        correct = "Ecrire des commentaires pour expliquer les parties complexes."
        return (
            "Quelle pratique fait partie des cinq regles d'or pour bien programmer ?",
            correct,
            distinct_choices([
                correct,
                "Copier-coller de longs blocs pour aller plus vite.",
                "Regrouper tout le programme dans un seul sous-programme.",
                "Utiliser des fonctionnalites que l'on ne comprend pas.",
            ]),
            "Le support insiste sur la lisibilite : commentaires utiles, decoupage clair et sous-programmes courts facilitent la maintenance.",
        )

    if "python" in lower_title and ("portable" in lower_text or "lisible" in lower_text):
        correct = "Il est portable, lisible et utilisable sur plusieurs systemes."
        return (
            "Quelle caracteristique correspond a Python ?",
            correct,
            distinct_choices([
                correct,
                "Il fonctionne uniquement sur un seul systeme d'exploitation.",
                "Il interdit l'utilisation de bibliotheques externes.",
                "Il est concu pour rendre les programmes volontairement illisibles.",
            ]),
            "Le chapitre presente Python comme un langage gratuit, lisible, extensible et portable entre plusieurs environnements.",
        )

    if "installer" in lower_title or "idle" in lower_text or "environnement" in lower_title:
        correct = "Installer Python depuis une source fiable puis ouvrir un environnement comme IDLE."
        return (
            "Quelle action permet de commencer a utiliser Python ?",
            correct,
            distinct_choices([
                correct,
                "Modifier les fichiers systeme sans installer l'interpreteur.",
                "Lire uniquement le titre du support sans tester d'instruction.",
                "Choisir une version au hasard sans verifier son lancement.",
            ]),
            "Le cours recommande de passer par une installation fiable, puis de verifier le demarrage avec un environnement de travail comme IDLE.",
        )

    if block_type == "definition":
        correct = shorten_answer(text)
        return (
            f"Quelle definition correspond a la notion : {title} ?",
            correct,
            plausible_definition_choices(correct, title),
            f"La definition du chapitre precise que {lowercase_first(correct)}",
        )

    if block_type == "bullet_list":
        items = block_content_items(block)
        correct = clean_text(items[0]) if items else shorten_answer(text)
        return (
            f"Quel element est explicitement presente dans le chapitre {chapter_title} ?",
            correct,
            plausible_list_choices(correct, items),
            f"Cet element apparait dans la liste du chapitre et fait partie des points a retenir sur {chapter_title}.",
        )

    if block_type == "key_point":
        correct = shorten_answer(text)
        return (
            f"Quel point cle faut retenir dans le chapitre {chapter_title} ?",
            correct,
            plausible_definition_choices(correct, chapter_title),
            f"Le point cle du chapitre insiste sur cette idee : {lowercase_first(correct)}",
        )

    if block_type == "example":
        correct = shorten_answer(text)
        return (
            f"Quel exemple illustre correctement le chapitre {chapter_title} ?",
            correct,
            plausible_example_choices(correct),
            f"L'exemple est issu du contenu du chapitre et montre une application concrete de la notion etudiee.",
        )

    if block_type == "warning":
        correct = shorten_answer(text)
        return (
            f"Quelle precaution faut-il garder en tete dans le chapitre {chapter_title} ?",
            correct,
            plausible_warning_choices(correct),
            f"Le bloc d'avertissement du cours signale cette precaution pour eviter une mauvaise interpretation.",
        )

    correct = shorten_answer(text)
    return (
        f"Quelle synthese correspond au chapitre {chapter_title} ?",
        correct,
        plausible_definition_choices(correct, chapter_title),
        f"La synthese reprend les idees centrales du chapitre sans se limiter au titre.",
    )


def validate_generated_question(question: dict, course_id: int, chapter_ids: set[int], existing_questions: set[str]) -> bool:
    question_text = clean_text(question.get("question"))
    choices = [clean_text(choice) for choice in question.get("choices") or []]
    correct_answer = clean_text(question.get("correct_answer"))
    explanation = clean_text(question.get("explanation"))

    if not question_text or not explanation:
        return False
    if question.get("chapter_id") not in chapter_ids:
        return False
    if len(question_text) < 16 or len(question_text) > 180:
        return False
    if len(choices) != 4 or len(set(choices)) != 4:
        return False
    if choices.count(correct_answer) != 1:
        return False
    if normalize_question_key(question_text) in existing_questions:
        return False
    searchable = normalize_question_key(" ".join([question_text, *choices, correct_answer]))
    if any(forbidden in searchable for forbidden in FORBIDDEN_PROPOSAL_TEXT):
        return False
    return bool(course_id)


def block_content_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        return clean_text(" ".join(str(item) for item in content))
    return clean_text(content)


def block_content_items(block: dict) -> list[str]:
    content = block.get("content")
    if isinstance(content, list):
        return [clean_text(item) for item in content if clean_text(item)]
    text = block_content_text(block)
    return [item.strip(" -") for item in re.split(r"[.;]\s+", text) if len(item.strip()) > 8]


def clean_text(value) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)


def shorten_answer(value: str, max_length: int = 150) -> str:
    text = clean_text(value)
    if len(text) <= max_length:
        return text
    cut = text[:max_length].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{cut}."


def distinct_choices(choices: list[str]) -> list[str]:
    cleaned = []
    for choice in choices:
        text = clean_text(choice)
        if text and text not in cleaned:
            cleaned.append(text)
    fillers = [
        "Une interpretation partielle qui oublie la logique du cours.",
        "Une reponse possible seulement dans un autre contexte.",
        "Une affirmation trop generale pour etre la bonne reponse.",
    ]
    for filler in fillers:
        if len(cleaned) >= 4:
            break
        if filler not in cleaned:
            cleaned.append(filler)
    return cleaned[:4]


def plausible_definition_choices(correct: str, topic: str) -> list[str]:
    return distinct_choices([
        correct,
        f"Une description vague de {topic} sans etapes ni objectif precis.",
        "Une simple memorisation de mots sans mise en pratique.",
        "Une procedure sans verification ni lien avec le probleme traite.",
    ])


def plausible_list_choices(correct: str, items: list[str]) -> list[str]:
    alternatives = [item for item in items[1:] if item != correct]
    return distinct_choices([
        correct,
        *alternatives[:2],
        "Appliquer une solution sans lire le probleme ni tester le resultat.",
    ])


def plausible_example_choices(correct: str) -> list[str]:
    return distinct_choices([
        correct,
        "Appliquer une action sans identifier les donnees necessaires.",
        "Conserver une idee generale sans la traduire en etapes.",
        "Ignorer le resultat obtenu apres l'execution.",
    ])


def plausible_warning_choices(correct: str) -> list[str]:
    return distinct_choices([
        correct,
        "Considerer que toutes les versions et captures restent toujours identiques.",
        "Supprimer les etapes de verification apres installation.",
        "Utiliser un outil sans verifier sa source ni son fonctionnement.",
    ])


def normalize_question_key(value: str) -> str:
    text = clean_text(value).lower()
    text = text.translate(str.maketrans({"é": "e", "è": "e", "ê": "e", "à": "a", "ù": "u", "ç": "c", "î": "i", "ô": "o"}))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def lowercase_first(value: str) -> str:
    text = clean_text(value)
    return f"{text[:1].lower()}{text[1:]}" if text else text


def list_student_assessments(db: Session, user: UserProfile) -> list[dict]:
    assignments = db.scalars(
        select(AssessmentAssignment)
        .where(AssessmentAssignment.student_id == user.id)
        .options(selectinload(AssessmentAssignment.assessment).selectinload(Assessment.questions))
        .order_by(AssessmentAssignment.assigned_at.desc())
    ).all()
    return [serialize_student_assessment(item.assessment, item, db, user) for item in assignments if is_visible_to_student(item.assessment)]


def get_student_assessment(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_student_assessment_model(db, user, assessment_id)
    enforce_assessment_available(db, user, assessment)
    return serialize_assessment(assessment, include_answers=False)


def submit_assessment(db: Session, user: UserProfile, assessment_id: int, payload: dict) -> dict:
    assessment = get_student_assessment_model(db, user, assessment_id)
    enforce_assessment_available(db, user, assessment)
    existing_attempts = db.scalar(
        select(func.count(AssessmentAttempt.id)).where(
            AssessmentAttempt.assessment_id == assessment.id,
            AssessmentAttempt.student_id == user.id,
        )
    ) or 0
    if existing_attempts >= assessment.max_attempts:
        raise HTTPException(status_code=409, detail="Nombre maximal de tentatives atteint")

    answers = payload.get("answers") or {}
    answer_times = payload.get("time_spent_seconds") or payload.get("answer_times") or {}
    if isinstance(answers, list):
        answers = {str(item.get("question_id")): item.get("selected_answer", "") for item in answers}
    if isinstance(answer_times, list):
        answer_times = {str(item.get("question_id")): item.get("time_spent_seconds") for item in answer_times}
    started_at = parse_datetime(payload.get("started_at")) or datetime.utcnow()
    now = datetime.utcnow()
    if assessment.time_limit_minutes and (now - started_at).total_seconds() > assessment.time_limit_minutes * 60 + 30:
        raise HTTPException(status_code=409, detail="Temps limite depasse")

    attempt = AssessmentAttempt(
        assessment_id=assessment.id,
        student_id=user.id,
        started_at=started_at,
        submitted_at=now,
        attempt_number=existing_attempts + 1,
        duration_seconds=max(0, int((now - started_at).total_seconds())),
        completed=True,
    )
    db.add(attempt)
    db.flush()

    total_points = 0.0
    awarded = 0.0
    for question in [item for item in assessment.questions if item.active]:
        selected = str(answers.get(str(question.id), answers.get(question.id, "")) or "")
        correct = selected == question.correct_answer
        points = float(question.points or 1)
        total_points += points
        if correct:
            awarded += points
        attempt.answers.append(
            AssessmentAnswer(
                question_id=question.id,
                selected_answer=selected,
                correct=correct,
                points_awarded=points if correct else 0,
                response_time_seconds=0,
                time_spent_seconds=validate_time_spent(answer_times.get(str(question.id), answer_times.get(question.id))),
            )
        )
    attempt.score = awarded
    attempt.percentage = round((awarded / total_points) * 100, 2) if total_points else 0
    assignment = get_assignment(db, user, assessment.id)
    if assignment:
        assignment.status = "completed"
    plan = create_remediation_from_attempt(db, attempt, assessment)
    if plan:
        try:
            personalized_lesson_service.generate_lessons_for_plan(db, user, plan.id, use_groq=False, commit=False)
        except HTTPException:
            pass
        study_path_service.create_or_refresh_for_plan(db, plan)
    elif assessment.assessment_type == "personalized":
        source_attempt_id = next((question.source_attempt_id for question in assessment.questions if question.source_attempt_id), None)
        source_plan = db.scalars(select(RemediationPlan).where(RemediationPlan.source_attempt_id == source_attempt_id)).first() if source_attempt_id else None
        if source_plan:
            study_path_service.create_or_refresh_for_plan(db, source_plan)
    create_notification(db, user.id, "assessment", "Resultat disponible", f"Votre resultat pour {assessment.title} est disponible.")
    db.commit()
    db.refresh(attempt)
    return serialize_attempt_report(db, attempt, include_answers=True, remediation_plan_id=plan.id if plan else None)


def get_attempt_report(db: Session, user: UserProfile, attempt_id: int) -> dict:
    attempt = get_attempt_for_user(db, user, attempt_id)
    return serialize_attempt_report(db, attempt, include_answers=True)


def get_detailed_attempt_report(db: Session, user: UserProfile, attempt_id: int) -> dict:
    attempt = get_attempt_for_user(db, user, attempt_id)
    report = build_detailed_attempt_report(db, attempt, include_answers=True)
    plan = get_remediation_plan_for_attempt(db, attempt.id)
    if plan:
        path = study_path_service.create_or_refresh_for_plan(db, plan)
        report["study_path"] = study_path_service.serialize_path(db, path, detail=False)
        report["next_action"] = report["study_path"]["next_action"]
        db.commit()
    return report


def get_professor_assessment_results(db: Session, user: UserProfile, assessment_id: int) -> dict:
    assessment = get_owned_assessment(db, user, assessment_id)
    attempts = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.assessment_id == assessment.id)
        .options(selectinload(AssessmentAttempt.student), selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question))
        .order_by(AssessmentAttempt.submitted_at.desc())
    ).all()
    results = [serialize_attempt_summary(db, item) for item in attempts]
    return {
        "assessment": serialize_assessment(assessment, include_answers=True),
        "results": results,
        "analytics": build_professor_assessment_analytics(db, assessment, attempts, results),
    }


def get_remediation_plan(db: Session, user: UserProfile, plan_id: int) -> dict:
    plan = db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.id == plan_id)
        .options(selectinload(RemediationPlan.items).selectinload(RemediationItem.chapter), selectinload(RemediationPlan.items).selectinload(RemediationItem.skill))
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    if not is_admin(user) and plan.student_id != user.id:
        raise HTTPException(status_code=403, detail="Parcours non autorise")
    return serialize_remediation_plan(plan)


def complete_remediation_item(db: Session, user: UserProfile, plan_id: int, item_id: int) -> dict:
    plan = db.get(RemediationPlan, plan_id)
    if plan is None or plan.student_id != user.id:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    item = next((entry for entry in plan.items if entry.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Etape introuvable")
    item.completed = True
    item.completed_at = datetime.utcnow()
    if all(entry.completed for entry in plan.items):
        plan.status = "completed"
        plan.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return serialize_remediation_plan(plan)


def create_personalized_assessment(db: Session, user: UserProfile, plan_id: int, payload: dict | None = None) -> dict:
    payload = payload or {}
    plan = db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.id == plan_id, RemediationPlan.student_id == user.id)
        .options(
            selectinload(RemediationPlan.items).selectinload(RemediationItem.chapter),
            selectinload(RemediationPlan.items).selectinload(RemediationItem.skill),
            selectinload(RemediationPlan.personalized_lessons),
        )
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    source_attempt = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.id == plan.source_attempt_id)
        .options(
            selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.chapter),
            selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.skill),
            selectinload(AssessmentAttempt.assessment).selectinload(Assessment.questions),
        )
    ).first()
    source_assessment = db.get(Assessment, source_attempt.assessment_id) if source_attempt else None
    if source_assessment is None:
        raise HTTPException(status_code=404, detail="Evaluation initiale introuvable")
    mode = str(payload.get("validation_mode") or "auto").strip().lower()
    professor_validation = mode in {"professor", "manual", "validation_professor"}
    existing = find_existing_personalized_assessment(db, plan, source_assessment)
    if existing:
        return serialize_assessment(existing, include_answers=False)

    generated_questions = generate_personalized_questions(
        db,
        plan,
        source_attempt,
        source_assessment,
        use_groq=payload.get("use_groq") is True,
        requested_count=payload.get("question_count"),
    )
    if not generated_questions:
        raise HTTPException(status_code=422, detail="Aucune question personnalisee fiable n'a pu etre generee")

    assessment = Assessment(
        professor_id=source_assessment.professor_id,
        classroom_id=source_assessment.classroom_id,
        course_id=plan.course_id,
        subject_id=plan.subject_id,
        title=f"Test personnalise - {source_assessment.title}",
        description=build_personalized_assessment_description(plan, generated_questions),
        instructions="Ce test cible les competences a renforcer apres votre parcours personnalise.",
        assessment_type="personalized",
        status="draft" if professor_validation else "published",
        difficulty_level_id=source_assessment.difficulty_level_id,
        max_attempts=1,
        publication_at=None if professor_validation else datetime.utcnow(),
    )
    db.add(assessment)
    db.flush()
    for index, question in enumerate(generated_questions, start=1):
        db.add(
            AssessmentQuestion(
            assessment_id=assessment.id,
                chapter_id=question.get("chapter_id"),
                skill_id=question.get("skill_id"),
                question=question["question"],
                choices=question["choices"],
                correct_answer=question["correct_answer"],
                explanation=question["explanation"],
                difficulty_level_id=question.get("difficulty_level_id"),
                points=float(question.get("points") or 1),
            order_index=index,
            active=True,
                source_document_id=question.get("source_document_id"),
                source_page_start=question.get("source_page_start"),
                source_page_end=question.get("source_page_end"),
                source_attempt_id=source_attempt.id,
                source_question_id=question.get("source_question_id"),
                generation_method=question.get("generation_method"),
                similarity_score=question.get("similarity_score"),
                adaptation_reason=question.get("adaptation_reason"),
            )
        )
    if not professor_validation:
        db.add(AssessmentAssignment(assessment_id=assessment.id, student_id=user.id, classroom_id=assessment.classroom_id, status="assigned"))
        create_notification(db, user.id, "assessment", "Test personnalise pret", f"{assessment.title} est disponible.")
    else:
        create_notification(db, source_assessment.professor_id, "assessment", "Test personnalise a valider", f"{assessment.title} attend votre validation.")
    db.commit()
    db.refresh(assessment)
    if not professor_validation:
        study_path = study_path_service.create_or_refresh_for_plan(db, plan)
        db.commit()
        data = serialize_assessment(assessment, include_answers=False)
        data["study_path_id"] = study_path.id
        data["validation_mode"] = "automatic"
        data["availability_reason"] = personalized_availability_reason(assessment, plan)
        return data
    data = serialize_assessment(assessment, include_answers=False)
    data["validation_mode"] = "professor" if professor_validation else "automatic"
    data["availability_reason"] = personalized_availability_reason(assessment, plan)
    return data


def compare_attempts(db: Session, user: UserProfile, initial_attempt_id: int, personalized_attempt_id: int) -> dict:
    initial = get_attempt_for_user(db, user, initial_attempt_id)
    personalized = get_attempt_for_user(db, user, personalized_attempt_id)
    initial_report = serialize_attempt_report(db, initial, include_answers=False)
    personalized_report = serialize_attempt_report(db, personalized, include_answers=False)
    return {
        "initial_score": initial.percentage,
        "personalized_score": personalized.percentage,
        "variation_points": round(personalized.percentage - initial.percentage, 2),
        "initial": initial_report,
        "after_remediation": personalized_report,
        "next_recommendation": "Continuer le parcours" if personalized.percentage >= initial.percentage else "Revoir les competences encore faibles",
    }


def find_existing_personalized_assessment(db: Session, plan: RemediationPlan, source_assessment: Assessment) -> Assessment | None:
    return db.scalars(
        select(Assessment)
        .where(
            Assessment.assessment_type == "personalized",
            Assessment.course_id == plan.course_id,
            Assessment.classroom_id == source_assessment.classroom_id,
            Assessment.title == f"Test personnalise - {source_assessment.title}",
        )
        .options(*assessment_options())
        .order_by(Assessment.created_at.desc())
    ).first()


def generate_personalized_questions(
    db: Session,
    plan: RemediationPlan,
    source_attempt: AssessmentAttempt,
    source_assessment: Assessment,
    *,
    use_groq: bool,
    requested_count,
) -> list[dict]:
    target_groups = build_personalized_targets(db, plan, source_attempt)
    if not target_groups:
        return []
    source_question_ids = [answer.question_id for answer in source_attempt.answers]
    source_questions = db.scalars(
        select(AssessmentQuestion)
        .where(AssessmentQuestion.id.in_(source_question_ids))
        .options(selectinload(AssessmentQuestion.chapter), selectinload(AssessmentQuestion.skill))
    ).all()
    existing_texts = [question.question for question in source_questions]
    selected: list[dict] = []
    max_count = max(PERSONALIZED_MIN_QUESTIONS, min(PERSONALIZED_MAX_QUESTIONS, int(requested_count or PERSONALIZED_MAX_QUESTIONS)))
    source = first_rag_document_for_course(db, plan.course_id)

    target_total = min(max_count, PERSONALIZED_MIN_QUESTIONS if len(target_groups) == 1 else len(target_groups))
    cycle = 0
    while len(selected) < target_total and cycle < target_total * 3:
        group = target_groups[cycle % len(target_groups)]
        cycle += 1
        if len(selected) >= max_count:
            break
        source_answer = group["answers"][0] if group["answers"] else None
        source_question = group.get("source_questions", [None])[0] if group.get("source_questions") else (source_answer.question if source_answer else None)
        chapter = group.get("chapter")
        skill = group.get("skill")
        blocks = personalized_lesson_service.select_relevant_blocks(chapter) if chapter else []
        rag_results = search_personalized_question_sources(db, plan, chapter, skill)
        difficulty_id, difficulty_reason = choose_personalized_difficulty(db, source_question, plan, group)
        candidate = None
        method = "deterministic"
        if use_groq:
            candidate = generate_personalized_question_with_groq(group, source_question, blocks, rag_results, difficulty_reason)
            method = "groq" if candidate else "deterministic"
        if candidate is None:
            candidate = build_deterministic_personalized_question(group, source_question, blocks, rag_results, len(selected) + 1)
        if candidate is None:
            continue
        candidate.update(
            {
                "chapter_id": chapter.id if chapter else None,
                "skill_id": skill.id if skill else None,
                "difficulty_level_id": difficulty_id,
                "points": source_question.points if source_question else 1,
                "source_document_id": source.id if source else (source_question.source_document_id if source_question else None),
                "source_page_start": extract_source_page(blocks, rag_results, source_question, "start"),
                "source_page_end": extract_source_page(blocks, rag_results, source_question, "end"),
                "source_question_id": source_question.id if source_question else None,
                "generation_method": method,
                "adaptation_reason": difficulty_reason,
            }
        )
        if not validate_personalized_question(candidate, source_questions, selected, plan.course_id):
            candidate = build_fallback_personalized_question(group, source_question, blocks, selected)
            if candidate:
                candidate.update(
                    {
                        "chapter_id": chapter.id if chapter else None,
                        "skill_id": skill.id if skill else None,
                        "difficulty_level_id": difficulty_id,
                        "points": source_question.points if source_question else 1,
                        "source_document_id": source.id if source else (source_question.source_document_id if source_question else None),
                        "source_page_start": extract_source_page(blocks, rag_results, source_question, "start"),
                        "source_page_end": extract_source_page(blocks, rag_results, source_question, "end"),
                        "source_question_id": source_question.id if source_question else None,
                        "generation_method": "deterministic",
                        "adaptation_reason": f"{difficulty_reason} Fallback deterministe apres rejet anti-duplication.",
                    }
                )
        if validate_personalized_question(candidate, source_questions, selected, plan.course_id):
            candidate["similarity_score"] = max_similarity(candidate["question"], [*existing_texts, *[item["question"] for item in selected]])
            selected.append(candidate)

    return selected[:max_count]


def build_personalized_targets(db: Session, plan: RemediationPlan, source_attempt: AssessmentAttempt) -> list[dict]:
    source_question_by_id = {
        question.id: question
        for question in db.scalars(
            select(AssessmentQuestion)
            .where(AssessmentQuestion.id.in_([answer.question_id for answer in source_attempt.answers]))
            .options(selectinload(AssessmentQuestion.chapter), selectinload(AssessmentQuestion.skill))
        ).all()
    }
    incorrect_answers = [answer for answer in source_attempt.answers if not answer.correct and source_question_by_id.get(answer.question_id)]
    preferred_key_by_chapter = {
        source_question_by_id[answer.question_id].chapter_id: (
            source_question_by_id[answer.question_id].chapter_id,
            source_question_by_id[answer.question_id].skill_id,
        )
        for answer in incorrect_answers
        if source_question_by_id[answer.question_id].chapter_id and source_question_by_id[answer.question_id].skill_id
    }
    completed_lessons = {(lesson.chapter_id, lesson.skill_id): lesson for lesson in plan.personalized_lessons if lesson.status == "completed"}
    groups: dict[tuple[int | None, int | None], dict] = {}
    for item in plan.items:
        key = preferred_key_by_chapter.get(item.chapter_id) if item.skill_id is None else None
        key = key or (item.chapter_id, item.skill_id)
        key_chapter_id, key_skill_id = key
        groups.setdefault(
            key,
            {
                "chapter": item.chapter or (db.get(CourseChapter, key_chapter_id) if key_chapter_id else None),
                "skill": item.skill or (db.get(Skill, key_skill_id) if key_skill_id else None),
                "answers": [],
                "source_questions": [],
                "remediation_items": [],
                "completed_lesson": completed_lessons.get(key),
            },
        )
        groups[key]["remediation_items"].append(item)
    for answer in incorrect_answers:
        question = source_question_by_id[answer.question_id]
        key = (question.chapter_id, question.skill_id)
        groups.setdefault(
            key,
            {
                "chapter": question.chapter,
                "skill": question.skill,
                "answers": [],
                "source_questions": [],
                "remediation_items": [],
                "completed_lesson": completed_lessons.get(key),
            },
        )
        groups[key]["answers"].append(answer)
        groups[key]["source_questions"].append(question)
    result = []
    for group in groups.values():
        chapter = group.get("chapter")
        skill = group.get("skill")
        if chapter and chapter.course_id != plan.course_id:
            continue
        if skill and skill.course_id and skill.course_id != plan.course_id:
            continue
        if not group["answers"] and not group["remediation_items"]:
            continue
        result.append(group)
    return result


def search_personalized_question_sources(db: Session, plan: RemediationPlan, chapter: CourseChapter | None, skill: Skill | None) -> list[dict]:
    query = " ".join(item for item in [skill.name if skill else "", chapter.title if chapter else ""] if item).strip()
    if not query:
        return []
    try:
        results = rag_document_service.filtered_semantic_search(db, query, course_id=plan.course_id, subject_id=plan.subject_id, top_k=3, published_only=True)
    except Exception:
        return []
    return [result for result in results if int(result.get("course_id") or plan.course_id) == plan.course_id]


def choose_personalized_difficulty(db: Session, source_question: AssessmentQuestion | None, plan: RemediationPlan, group: dict) -> tuple[int | None, str]:
    base_id = source_question.difficulty_level_id if source_question else None
    completed_lesson = group.get("completed_lesson")
    if completed_lesson and lesson_knowledge_check_success(completed_lesson):
        return base_id, "Mini-cours termine et knowledge check reussi : maintien du niveau avec contexte nouveau."
    weak_count = len(group.get("answers") or [])
    if weak_count >= 2:
        easier_id = adjacent_difficulty_id(db, base_id, direction=-1)
        if easier_id and easier_id != base_id:
            return easier_id, "Faiblesse importante : niveau legerement simplifie pour consolider la competence."
    return base_id, "Competence ciblee apres erreur initiale : niveau conserve avec formulation differente."


def adjacent_difficulty_id(db: Session, difficulty_id: int | None, direction: int) -> int | None:
    if difficulty_id is None:
        return None
    from app.models.persistence import DifficultyLevel

    levels = db.scalars(select(DifficultyLevel).where(DifficultyLevel.active.is_(True)).order_by(DifficultyLevel.display_order, DifficultyLevel.id)).all()
    ids = [level.id for level in levels]
    if difficulty_id not in ids:
        return difficulty_id
    index = ids.index(difficulty_id)
    next_index = max(0, min(len(ids) - 1, index + direction))
    return ids[next_index]


def lesson_knowledge_check_success(lesson: PersonalizedLesson) -> bool:
    content = lesson.structured_content or []
    if isinstance(content, dict):
        content = content.get("blocks") or content.get("items") or []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "knowledge_check":
            check = block.get("content") if isinstance(block.get("content"), dict) else {}
            if check.get("last_result") is True or check.get("correct") is True:
                return True
    return lesson.status == "completed"


def build_deterministic_personalized_question(group: dict, source_question: AssessmentQuestion | None, blocks: list[dict], rag_results: list[dict], variant: int = 1) -> dict | None:
    chapter = group.get("chapter")
    skill = group.get("skill")
    topic = clean_text(skill.name if skill else chapter.title if chapter else "notion ciblee")
    evidence = first_personalized_evidence(blocks, rag_results, source_question)
    if not evidence:
        return None
    correct = f"Identifier {topic} puis l'appliquer dans un nouveau contexte."
    return {
        "question": f"Situation {variant} : quelle demarche montre que vous maitrisez {topic} dans un autre contexte ?",
        "choices": distinct_choices(
            [
                correct,
                f"Repeter le libelle de {topic} sans verifier son application.",
                "Choisir une reponse uniquement parce qu'elle ressemble a l'exemple initial.",
                "Ignorer les indices du probleme et passer directement a la conclusion.",
            ]
        ),
        "correct_answer": correct,
        "explanation": shorten_answer(f"La competence est validee quand l'apprenant reutilise la notion dans un contexte different. Indice du cours : {evidence}", 420),
    }


def build_fallback_personalized_question(group: dict, source_question: AssessmentQuestion | None, blocks: list[dict], selected: list[dict]) -> dict | None:
    chapter = group.get("chapter")
    skill = group.get("skill")
    topic = clean_text(skill.name if skill else chapter.title if chapter else "cette notion")
    variant = len(selected) + 1
    evidence = first_personalized_evidence(blocks, [], source_question) or "la notion etudiee dans le mini-cours"
    correct = f"Analyser le cas {variant}, citer l'indice utile, puis justifier la solution liee a {topic}."
    return {
        "question": f"Cas pratique {variant} : quelle action permet de corriger une erreur liee a {topic} ?",
        "choices": distinct_choices(
            [
                correct,
                "Reprendre exactement l'ancienne reponse sans analyser le nouveau cas.",
                "Choisir la proposition la plus longue sans lire l'enonce.",
                "Traiter la question comme si elle appartenait a un autre chapitre.",
            ]
        ),
        "correct_answer": correct,
        "explanation": shorten_answer(f"Cette question reformule l'objectif initial et change le contexte pour verifier la comprehension. Source pedagogique : {evidence}", 420),
    }


def first_personalized_evidence(blocks: list[dict], rag_results: list[dict], source_question: AssessmentQuestion | None) -> str:
    for block in blocks:
        text = personalized_lesson_service.block_content_text(block) if hasattr(personalized_lesson_service, "block_content_text") else block_content_text(block)
        if text:
            return shorten_answer(text, 220)
    for result in rag_results:
        text = clean_text(result.get("text") or result.get("text_preview"))
        if text:
            return shorten_answer(text, 220)
    if source_question and source_question.explanation:
        return shorten_answer(source_question.explanation, 220)
    return ""


def generate_personalized_question_with_groq(group: dict, source_question: AssessmentQuestion | None, blocks: list[dict], rag_results: list[dict], adaptation_reason: str) -> dict | None:
    settings = get_settings()
    api_key = settings.get("groq_api_key")
    if not api_key or source_question is None:
        return None
    excerpts = [first_personalized_evidence(blocks, rag_results, source_question)]
    topic = clean_text((group.get("skill").name if group.get("skill") else "") or (group.get("chapter").title if group.get("chapter") else "notion"))
    payload = {
        "model": settings.get("groq_model") or "openai/gpt-oss-20b",
        "temperature": 0.2,
        "max_tokens": 700,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Generate exactly one new multiple-choice question in French. "
                    "Return strict JSON with keys question, choices, correct_answer, explanation. "
                    "Use only provided excerpts. Do not copy the original wording, choices, or explanation."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "topic": topic,
                        "adaptation_reason": adaptation_reason,
                        "original_question": source_question.question,
                        "original_choices": source_question.choices,
                        "excerpts": excerpts,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    request = urllib.request.Request(
        GROQ_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "EduMentorAI/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(content)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    choices = parsed.get("choices")
    correct = parsed.get("correct_answer")
    if not isinstance(choices, list) or correct not in choices:
        return None
    return {
        "question": clean_text(parsed.get("question")),
        "choices": distinct_choices(choices),
        "correct_answer": clean_text(correct),
        "explanation": clean_text(parsed.get("explanation")),
    }


def validate_personalized_question(candidate: dict | None, source_questions: list[AssessmentQuestion], selected: list[dict], course_id: int) -> bool:
    if not candidate:
        return False
    question_text = clean_text(candidate.get("question"))
    choices = [clean_text(choice) for choice in candidate.get("choices") or []]
    correct_answer = clean_text(candidate.get("correct_answer"))
    explanation = clean_text(candidate.get("explanation"))
    if not question_text or not explanation or len(choices) != 4 or len(set(choices)) != 4 or correct_answer not in choices:
        return False
    if not course_id:
        return False
    source_texts = [question.question for question in source_questions] + [item["question"] for item in selected]
    source_choice_sets = [set(clean_text(choice) for choice in (question.choices or [])) for question in source_questions]
    source_choice_sets.extend(set(clean_text(choice) for choice in (item.get("choices") or [])) for item in selected)
    if max_similarity(question_text, source_texts) >= PERSONALIZED_SIMILARITY_THRESHOLD:
        return False
    if set(choices) in source_choice_sets:
        return False
    if source_questions and any(normalize_question_key(explanation) == normalize_question_key(question.explanation) for question in source_questions):
        return False
    return True


def max_similarity(text: str, others: list[str]) -> float:
    if not others:
        return 0.0
    return round(max(token_similarity(text, other) for other in others), 4)


def token_similarity(left: str, right: str) -> float:
    left_tokens = set(normalize_question_key(left).split())
    right_tokens = set(normalize_question_key(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def extract_source_page(blocks: list[dict], rag_results: list[dict], source_question: AssessmentQuestion | None, bound: str) -> int | None:
    start_keys = ["source_page_start", "page", "page_start"]
    end_keys = ["source_page_end", "page", "page_end"]
    keys = start_keys if bound == "start" else end_keys
    for block in blocks:
        for key in keys:
            value = block.get(key)
            if str(value or "").isdigit():
                return int(value)
    for result in rag_results:
        for key in keys + ["page_number"]:
            value = result.get(key)
            if str(value or "").isdigit():
                return int(value)
    if source_question:
        return source_question.source_page_start if bound == "start" else source_question.source_page_end
    return None


def build_personalized_assessment_description(plan: RemediationPlan, questions: list[dict]) -> str:
    skills = sorted({str(question.get("skill_id")) for question in questions if question.get("skill_id")})
    chapters = sorted({str(question.get("chapter_id")) for question in questions if question.get("chapter_id")})
    return (
        "Evaluation ciblee apres remediation. "
        f"Competences ciblees: {len(skills)}. Chapitres cibles: {len(chapters)}. "
        f"Questions nouvelles: {len(questions)}."
    )


def personalized_availability_reason(assessment: Assessment, plan: RemediationPlan) -> dict:
    questions = [question for question in assessment.questions if question.active]
    return {
        "reason": "Test genere a partir des competences faibles et des mini-cours du parcours.",
        "targeted_skills": sorted({question.skill_id for question in questions if question.skill_id}),
        "targeted_chapters": sorted({question.chapter_id for question in questions if question.chapter_id}),
        "question_count": len(questions),
        "difficulty": assessment.difficulty_level.name if assessment.difficulty_level else "Non disponible",
        "status": assessment.status,
        "available": assessment.status == "published",
        "plan_id": plan.id,
    }


def compare_attempts_detailed(db: Session, user: UserProfile, initial_attempt_id: int, personalized_attempt_id: int) -> dict:
    initial = get_attempt_for_user(db, user, initial_attempt_id)
    personalized = get_attempt_for_user(db, user, personalized_attempt_id)
    initial_report = build_detailed_attempt_report(db, initial, include_answers=False)
    final_report = build_detailed_attempt_report(db, personalized, include_answers=False)
    skill_comparison = compare_dimension_results(
        initial_report["skill_results"],
        final_report["skill_results"],
        "Non evaluee dans le test personnalise",
    )
    chapter_comparison = compare_dimension_results(
        initial_report["chapter_results"],
        final_report["chapter_results"],
        "Non evalue dans le test personnalise",
    )
    delta = round(final_report["global_metrics"]["percentage"] - initial_report["global_metrics"]["percentage"], 2)
    return {
        "available": True,
        "initial_attempt_id": initial.id,
        "personalized_attempt_id": personalized.id,
        "initial": initial_report,
        "after_remediation": final_report,
        "score_delta": delta,
        "trend": "amelioration" if delta > 0 else "baisse" if delta < 0 else "stabilite",
        "skill_comparison": skill_comparison,
        "chapter_comparison": chapter_comparison,
        "improved_skills": [item for item in skill_comparison if item.get("delta") is not None and item["delta"] > 0],
        "unchanged_skills": [item for item in skill_comparison if item.get("delta") == 0],
        "still_weak_skills": [item for item in skill_comparison if item.get("final_percentage") is not None and item["final_percentage"] < 70],
        "next_action": build_comparison_next_action(delta, skill_comparison),
    }


def compare_latest_for_plan(db: Session, user: UserProfile, plan_id: int) -> dict:
    plan = db.scalars(select(RemediationPlan).where(RemediationPlan.id == plan_id, RemediationPlan.student_id == user.id)).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    initial = db.get(AssessmentAttempt, plan.source_attempt_id)
    personalized_attempts = db.scalars(
        select(AssessmentAttempt)
        .join(Assessment, Assessment.id == AssessmentAttempt.assessment_id)
        .where(
            AssessmentAttempt.student_id == user.id,
            Assessment.course_id == plan.course_id,
            Assessment.assessment_type == "personalized",
            AssessmentAttempt.completed.is_(True),
            AssessmentAttempt.submitted_at >= plan.created_at,
        )
        .order_by(AssessmentAttempt.submitted_at.desc())
    ).all()
    if initial is None or not personalized_attempts:
        return {
            "available": False,
            "message": "Aucun deuxième test n'existe encore pour ce parcours.",
            "initial_score": initial.percentage if initial else plan.initial_score,
            "personalized_score": None,
            "variation_points": None,
        }
    comparison = compare_attempts(db, user, initial.id, personalized_attempts[0].id)
    comparison["available"] = True
    return comparison


def compare_latest_for_plan_detailed(db: Session, user: UserProfile, plan_id: int) -> dict:
    plan = db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.id == plan_id)
        .options(selectinload(RemediationPlan.personalized_lessons), selectinload(RemediationPlan.items))
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    if not is_admin(user) and plan.student_id != user.id:
        raise HTTPException(status_code=403, detail="Parcours non autorise")
    initial = db.get(AssessmentAttempt, plan.source_attempt_id)
    personalized_attempt = db.scalars(
        select(AssessmentAttempt)
        .join(Assessment, Assessment.id == AssessmentAttempt.assessment_id)
        .where(
            AssessmentAttempt.student_id == plan.student_id,
            Assessment.course_id == plan.course_id,
            Assessment.assessment_type == "personalized",
            AssessmentAttempt.completed.is_(True),
            AssessmentAttempt.submitted_at >= plan.created_at,
        )
        .order_by(AssessmentAttempt.submitted_at.desc())
    ).first()
    if initial is None or personalized_attempt is None:
        return {
            "available": False,
            "message": "Aucun deuxieme test n'existe encore pour ce parcours.",
            "initial_attempt_id": initial.id if initial else None,
            "personalized_attempt_id": None,
            "remediation_progress": personalized_lesson_service.serialize_plan_with_lessons(plan),
            "next_action": build_remediation_next_action(plan),
        }
    comparison = compare_attempts_detailed(db, user, initial.id, personalized_attempt.id)
    comparison["remediation_progress"] = personalized_lesson_service.serialize_plan_with_lessons(plan)
    comparison["completed_lessons"] = [personalized_lesson_service.serialize_lesson(lesson) for lesson in plan.personalized_lessons if lesson.status == "completed"]
    return comparison


def serialize_classroom(classroom: Classroom, include_students: bool = False) -> dict:
    data = {
        "id": classroom.id,
        "name": classroom.name,
        "code": classroom.code,
        "professor_id": classroom.professor_id,
        "subject_id": classroom.subject_id,
        "education_level_id": classroom.education_level_id,
        "academic_year": classroom.academic_year,
        "description": classroom.description,
        "active": classroom.active,
        "created_at": classroom.created_at.isoformat() if classroom.created_at else None,
        "updated_at": classroom.updated_at.isoformat() if classroom.updated_at else None,
        "student_count": sum(1 for item in classroom.memberships if item.active),
    }
    if include_students:
        data["students"] = [serialize_membership(item) for item in classroom.memberships if item.active]
    return data


def serialize_membership(membership: ClassroomMembership) -> dict:
    return {
        "id": membership.id,
        "classroom_id": membership.classroom_id,
        "student_id": membership.student_id,
        "student_name": membership.student.full_name if membership.student else "Etudiant",
        "email": membership.student.email if membership.student else "",
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        "active": membership.active,
    }


def serialize_assessment(assessment: Assessment, include_answers: bool) -> dict:
    return {
        "id": assessment.id,
        "professor_id": assessment.professor_id,
        "classroom_id": assessment.classroom_id,
        "course_id": assessment.course_id,
        "course_title": assessment.course.title if assessment.course else "",
        "subject_id": assessment.subject_id,
        "title": assessment.title,
        "description": assessment.description,
        "instructions": assessment.instructions,
        "assessment_type": assessment.assessment_type,
        "status": assessment.status,
        "difficulty_level_id": assessment.difficulty_level_id,
        "publication_at": assessment.publication_at.isoformat() if assessment.publication_at else None,
        "expires_at": assessment.expires_at.isoformat() if assessment.expires_at else None,
        "time_limit_minutes": assessment.time_limit_minutes,
        "max_attempts": assessment.max_attempts,
        "question_count": len([item for item in assessment.questions if item.active]),
        "questions": [serialize_question(item, include_answers) for item in assessment.questions],
        "created_at": assessment.created_at.isoformat() if assessment.created_at else None,
        "updated_at": assessment.updated_at.isoformat() if assessment.updated_at else None,
    }


def serialize_question(question: AssessmentQuestion, include_answer: bool) -> dict:
    data = {
        "id": question.id,
        "chapter_id": question.chapter_id,
        "skill_id": question.skill_id,
        "question": question.question,
        "choices": question.choices,
        "explanation": question.explanation if include_answer else "",
        "difficulty_level_id": question.difficulty_level_id,
        "points": question.points,
        "order_index": question.order_index,
        "active": question.active,
        "source_document_id": question.source_document_id,
        "source_page_start": question.source_page_start,
        "source_page_end": question.source_page_end,
        "source_attempt_id": question.source_attempt_id,
        "source_question_id": question.source_question_id,
        "generation_method": question.generation_method,
        "similarity_score": question.similarity_score,
        "adaptation_reason": question.adaptation_reason,
    }
    if include_answer:
        data["correct_answer"] = question.correct_answer
    return data


def serialize_student_assessment(assessment: Assessment, assignment: AssessmentAssignment, db: Session, user: UserProfile) -> dict:
    data = serialize_assessment(assessment, include_answers=False)
    data["assignment_status"] = assignment.status
    data["assigned_at"] = assignment.assigned_at.isoformat() if assignment.assigned_at else None
    data["attempts_used"] = db.scalar(select(func.count(AssessmentAttempt.id)).where(AssessmentAttempt.assessment_id == assessment.id, AssessmentAttempt.student_id == user.id)) or 0
    if assessment.assessment_type == "personalized":
        plan = db.scalars(
            select(RemediationPlan)
            .where(RemediationPlan.student_id == user.id, RemediationPlan.course_id == assessment.course_id)
            .order_by(RemediationPlan.created_at.desc())
        ).first()
        if plan:
            data["personalized_context"] = personalized_availability_reason(assessment, plan)
    return data


def serialize_attempt_summary(db: Session, attempt: AssessmentAttempt) -> dict:
    report = serialize_attempt_report(db, attempt, include_answers=False)
    report["student_name"] = attempt.student.full_name if attempt.student else "Etudiant"
    report["student_email"] = attempt.student.email if attempt.student else ""
    return report


def serialize_attempt_report(db: Session, attempt: AssessmentAttempt, include_answers: bool, remediation_plan_id: int | None = None) -> dict:
    assessment = attempt.assessment
    answers = list(attempt.answers)
    by_chapter = aggregate_by_dimension(db, answers, "chapter")
    by_skill = aggregate_by_dimension(db, answers, "skill")
    correct_count = sum(1 for answer in answers if answer.correct)
    total_questions = len(answers)
    data = {
        "attempt_id": attempt.id,
        "assessment_id": attempt.assessment_id,
        "assessment_title": assessment.title if assessment else "",
        "student_id": attempt.student_id,
        "score": attempt.score,
        "percentage": attempt.percentage,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "completion_rate": 100 if attempt.completed else 0,
        "duration_seconds": attempt.duration_seconds,
        "precision": round((correct_count / total_questions) * 100, 2) if total_questions else 0,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "results_by_chapter": by_chapter,
        "results_by_skill": by_skill,
        "remediation_plan_id": remediation_plan_id or find_plan_id(db, attempt.id),
    }
    if include_answers:
        data["questions"] = [serialize_answer(answer) for answer in answers]
    return data


def build_detailed_attempt_report(db: Session, attempt: AssessmentAttempt, include_answers: bool) -> dict:
    assessment = attempt.assessment
    course = assessment.course if assessment else None
    subject = assessment.subject if assessment else None
    answers = list(attempt.answers)
    active_questions = (
        db.scalars(
            select(AssessmentQuestion)
            .where(AssessmentQuestion.assessment_id == assessment.id, AssessmentQuestion.active.is_(True))
            .options(selectinload(AssessmentQuestion.chapter), selectinload(AssessmentQuestion.skill))
            .order_by(AssessmentQuestion.order_index.asc(), AssessmentQuestion.id.asc())
        ).all()
        if assessment
        else []
    )
    answer_by_question_id = {answer.question_id: answer for answer in answers}
    correct_answers = [answer for answer in answers if answer.selected_answer and answer.correct]
    incorrect_answers = [answer for answer in answers if answer.selected_answer and not answer.correct]
    unanswered = [question for question in active_questions if not (answer_by_question_id.get(question.id) and answer_by_question_id[question.id].selected_answer)]
    max_score = sum(float(question.points or 1) for question in active_questions)
    score = float(attempt.score or 0)
    answered_count = len([answer for answer in answers if answer.selected_answer])
    total_questions = len(active_questions) or len(answers)
    valid_times = [answer.time_spent_seconds for answer in answers if answer.time_spent_seconds is not None]
    average_time = round(sum(valid_times) / len(valid_times), 2) if valid_times else None
    accuracy = round((len(correct_answers) / answered_count) * 100, 2) if answered_count else 0
    accuracy_note = None if answered_count else "Aucune reponse donnee : accuracy calculee a 0."
    completion_rate = round((answered_count / total_questions) * 100, 2) if total_questions else 0
    percentage = round((score / max_score) * 100, 2) if max_score else 0
    chapter_results = aggregate_detailed_by_dimension(db, answers, active_questions, "chapter")
    skill_results = aggregate_detailed_by_dimension(db, answers, active_questions, "skill")
    remediation_plan = get_remediation_plan_for_attempt(db, attempt.id)
    lessons = list(remediation_plan.personalized_lessons) if remediation_plan else []
    attach_lessons_to_skill_results(skill_results, lessons)
    strengths = build_strengths(chapter_results, skill_results)
    weaknesses = build_weaknesses(chapter_results, skill_results)
    slow_questions = detect_slow_questions(answers)

    return {
        "attempt_id": attempt.id,
        "assessment": serialize_assessment(assessment, include_answers=False) if assessment else None,
        "course": {"id": course.id, "title": course.title} if course else None,
        "subject": {"id": subject.id, "name": subject.name} if subject else None,
        "student": {"id": attempt.student_id, "name": attempt.student.full_name if attempt.student else "", "email": attempt.student.email if attempt.student else ""},
        "global_metrics": {
            "total_questions": total_questions,
            "answered_questions": answered_count,
            "correct_answers": len(correct_answers),
            "incorrect_answers": len(incorrect_answers),
            "unanswered_questions": len(unanswered),
            "score": score,
            "max_score": max_score,
            "percentage": percentage,
            "accuracy": accuracy,
            "accuracy_note": accuracy_note,
            "completion_rate": completion_rate,
            "duration_seconds": attempt.duration_seconds,
            "average_time_per_question": average_time,
            "average_time_per_question_label": f"{average_time}s" if average_time is not None else "Non disponible",
            "time_data_available": bool(valid_times),
            "mastery_status": mastery_label(db, percentage),
        },
        "chapter_results": chapter_results,
        "skill_results": skill_results,
        "correct_answers": [serialize_answer(answer) for answer in correct_answers] if include_answers else [],
        "incorrect_answers": [serialize_answer(answer) for answer in incorrect_answers] if include_answers else [],
        "unanswered_questions": [serialize_unanswered_question(question) for question in unanswered],
        "slow_questions": slow_questions,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "remediation_plan": serialize_remediation_plan(remediation_plan) if remediation_plan else None,
        "personalized_lessons": [personalized_lesson_service.serialize_lesson(lesson) for lesson in lessons],
        "next_action": build_attempt_next_action(remediation_plan, weaknesses, attempt),
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
    }


def aggregate_detailed_by_dimension(db: Session, answers: list[AssessmentAnswer], questions: list[AssessmentQuestion], dimension: str) -> list[dict]:
    buckets: dict[str, dict] = {}
    for question in questions:
        key, label = dimension_key_label(question, dimension)
        if key == "none":
            continue
        buckets.setdefault(
            key,
            {
                "id": int(key),
                "name": label,
                "total_questions": 0,
                "answered_questions": 0,
                "correct_answers": 0,
                "time_values": [],
                "question_ids": [],
            },
        )
        buckets[key]["total_questions"] += 1
        buckets[key]["question_ids"].append(question.id)

    answer_by_question_id = {answer.question_id: answer for answer in answers}
    for question in questions:
        key, _ = dimension_key_label(question, dimension)
        if key == "none" or key not in buckets:
            continue
        answer = answer_by_question_id.get(question.id)
        if answer and answer.selected_answer:
            buckets[key]["answered_questions"] += 1
            if answer.correct:
                buckets[key]["correct_answers"] += 1
        if answer and answer.time_spent_seconds is not None:
            buckets[key]["time_values"].append(answer.time_spent_seconds)

    rows = []
    for bucket in buckets.values():
        percentage = round((bucket["correct_answers"] / bucket["total_questions"]) * 100, 2) if bucket["total_questions"] else 0
        time_values = bucket.pop("time_values")
        rows.append(
            {
                **bucket,
                "correct": bucket["correct_answers"],
                "total": bucket["total_questions"],
                "percentage": percentage,
                "mastery": mastery_label(db, percentage),
                "mastery_status": mastery_label(db, percentage),
                "time_spent_seconds": sum(time_values) if time_values else None,
                "weak": percentage < 70,
                "recommended_action": "Revoir cette notion" if percentage < 70 else "Consolider avec des exercices",
            }
        )
    return sorted(rows, key=lambda row: row["percentage"])


def dimension_key_label(question: AssessmentQuestion, dimension: str) -> tuple[str, str]:
    if dimension == "chapter":
        return str(question.chapter_id or "none"), question.chapter.title if question.chapter else "Sans chapitre"
    return str(question.skill_id or "none"), question.skill.name if question.skill else "Sans competence"


def attach_lessons_to_skill_results(skill_results: list[dict], lessons: list) -> None:
    lessons_by_skill = {lesson.skill_id: lesson for lesson in lessons if lesson.skill_id}
    for row in skill_results:
        lesson = lessons_by_skill.get(row["id"])
        row["personalized_lesson"] = personalized_lesson_service.serialize_lesson(lesson) if lesson else None
        if lesson:
            row["recommended_action"] = f"Ouvrir le mini-cours : {lesson.title}"


def build_strengths(chapter_results: list[dict], skill_results: list[dict]) -> list[dict]:
    rows = [*skill_results, *chapter_results]
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "percentage": row["percentage"],
            "mastery_status": row["mastery_status"],
            "reason": f"{row['correct_answers']} reponse(s) correcte(s) sur {row['total_questions']}.",
        }
        for row in sorted([item for item in rows if item["percentage"] >= 70], key=lambda item: item["percentage"], reverse=True)[:5]
    ]


def build_weaknesses(chapter_results: list[dict], skill_results: list[dict]) -> list[dict]:
    rows = [*skill_results, *chapter_results]
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "percentage": row["percentage"],
            "mastery_status": row["mastery_status"],
            "reason": f"{row['name']} - {round(row['percentage'])}% - Mini-cours recommande." if row["percentage"] < 70 else "",
            "recommended_action": row["recommended_action"],
            "personalized_lesson": row.get("personalized_lesson"),
        }
        for row in sorted([item for item in rows if item["percentage"] < 70], key=lambda item: item["percentage"])[:5]
    ]


def detect_slow_questions(answers: list[AssessmentAnswer]) -> list[dict]:
    valid = [answer for answer in answers if answer.time_spent_seconds is not None]
    if len(valid) < 3:
        return []
    median_time = median([answer.time_spent_seconds for answer in valid])
    threshold = median_time * 1.5
    slow = []
    for answer in valid:
        if answer.time_spent_seconds <= threshold:
            continue
        question = answer.question
        slow.append(
            {
                "question_id": answer.question_id,
                "question": question.question if question else "",
                "time_spent_seconds": answer.time_spent_seconds,
                "median_time_seconds": median_time,
                "chapter": question.chapter.title if question and question.chapter else None,
                "skill": question.skill.name if question and question.skill else None,
                "correct": answer.correct,
            }
        )
    return slow


def serialize_unanswered_question(question: AssessmentQuestion) -> dict:
    return {
        "question_id": question.id,
        "question": question.question,
        "chapter_id": question.chapter_id,
        "chapter": question.chapter.title if question.chapter else None,
        "skill_id": question.skill_id,
        "skill": question.skill.name if question.skill else None,
        "points": question.points,
    }


def get_remediation_plan_for_attempt(db: Session, attempt_id: int) -> RemediationPlan | None:
    return db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.source_attempt_id == attempt_id)
        .options(
            selectinload(RemediationPlan.items).selectinload(RemediationItem.chapter),
            selectinload(RemediationPlan.items).selectinload(RemediationItem.skill),
            selectinload(RemediationPlan.personalized_lessons),
            selectinload(RemediationPlan.course),
        )
    ).first()


def validate_time_spent(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Temps par question invalide") from exc
    if seconds < 0:
        raise HTTPException(status_code=422, detail="Temps par question negatif refuse")
    return min(seconds, 24 * 60 * 60)


def build_attempt_next_action(plan: RemediationPlan | None, weaknesses: list[dict], attempt: AssessmentAttempt) -> dict:
    if plan:
        progress = personalized_lesson_service.serialize_plan_with_lessons(plan)
        next_step = progress.get("next_step") or {}
        if next_step.get("type") == "lesson":
            return {
                "type": "start_lesson",
                "label": "Commencer le premier mini-cours",
                "reason": "Des difficultes ont ete detectees dans cette tentative.",
                "route": f"/personalized-lessons/{next_step.get('id')}",
                "entity_id": next_step.get("id"),
            }
        if progress.get("percentage") == 100:
            return {
                "type": "personalized_assessment",
                "label": "Passer le test personnalise",
                "reason": "Le parcours de remediation est termine.",
                "route": f"/remediation/{plan.id}",
                "entity_id": plan.id,
            }
        return {
            "type": "continue_remediation",
            "label": "Continuer la remediation",
            "reason": "Le parcours personnalise est en cours.",
            "route": f"/remediation/{plan.id}",
            "entity_id": plan.id,
        }
    if weaknesses:
        return {
            "type": "review_skill",
            "label": "Revoir une competence encore faible",
            "reason": weaknesses[0]["reason"],
            "route": f"/assessment-results/{attempt.id}",
            "entity_id": attempt.id,
        }
    return {
        "type": "continue_course",
        "label": "Continuer vers le cours suivant",
        "reason": "Aucune difficulte prioritaire detectee.",
        "route": "/courses",
        "entity_id": None,
    }


def build_remediation_next_action(plan: RemediationPlan) -> dict:
    progress = personalized_lesson_service.serialize_plan_with_lessons(plan)
    step = progress.get("next_step") or {}
    if step.get("type") == "lesson":
        return {
            "type": "continue_lesson",
            "label": "Continuer un mini-cours",
            "reason": "Un mini-cours reste a terminer.",
            "route": f"/personalized-lessons/{step.get('id')}",
            "entity_id": step.get("id"),
        }
    return {
        "type": "personalized_assessment",
        "label": "Passer le test personnalise",
        "reason": "Les mini-cours obligatoires sont termines.",
        "route": f"/remediation/{plan.id}",
        "entity_id": plan.id,
    }


def compare_dimension_results(initial_rows: list[dict], final_rows: list[dict], missing_label: str) -> list[dict]:
    final_by_id = {row["id"]: row for row in final_rows}
    comparison = []
    for initial in initial_rows:
        final = final_by_id.get(initial["id"])
        if final is None:
            comparison.append(
                {
                    "id": initial["id"],
                    "name": initial["name"],
                    "initial_percentage": initial["percentage"],
                    "final_percentage": None,
                    "delta": None,
                    "initial_status": initial["mastery_status"],
                    "final_status": missing_label,
                    "initial_questions": initial["total_questions"],
                    "final_questions": 0,
                    "conclusion": missing_label,
                }
            )
            continue
        delta = round(final["percentage"] - initial["percentage"], 2)
        comparison.append(
            {
                "id": initial["id"],
                "name": initial["name"],
                "initial_percentage": initial["percentage"],
                "final_percentage": final["percentage"],
                "delta": delta,
                "initial_status": initial["mastery_status"],
                "final_status": final["mastery_status"],
                "initial_questions": initial["total_questions"],
                "final_questions": final["total_questions"],
                "conclusion": "Amelioration" if delta > 0 else "Stable" if delta == 0 else "Baisse",
            }
        )
    return comparison


def build_comparison_next_action(delta: float, skill_comparison: list[dict]) -> dict:
    still_weak = [item for item in skill_comparison if item.get("final_percentage") is not None and item["final_percentage"] < 70]
    if still_weak:
        return {
            "type": "review_skill",
            "label": "Revoir une competence encore faible",
            "reason": f"{still_weak[0]['name']} reste sous 70%.",
            "route": "/remediation",
            "entity_id": still_weak[0]["id"],
        }
    return {
        "type": "continue_course",
        "label": "Continuer vers le cours suivant",
        "reason": "Progression positive." if delta > 0 else "Resultat stable apres remediation.",
        "route": "/courses",
        "entity_id": None,
    }


def build_professor_assessment_analytics(db: Session, assessment: Assessment, attempts: list[AssessmentAttempt], results: list[dict]) -> dict:
    assigned_count = len(assessment.assignments)
    completed_attempts = [attempt for attempt in attempts if attempt.completed]
    detailed_reports = [build_detailed_attempt_report(db, attempt, include_answers=False) for attempt in completed_attempts]
    percentages = [report["global_metrics"]["percentage"] for report in detailed_reports]
    accuracies = [report["global_metrics"]["accuracy"] for report in detailed_reports]
    completion_rates = [report["global_metrics"]["completion_rate"] for report in detailed_reports]
    durations = [report["global_metrics"]["duration_seconds"] for report in detailed_reports if report["global_metrics"]["duration_seconds"] is not None]
    time_averages = [report["global_metrics"]["average_time_per_question"] for report in detailed_reports if report["global_metrics"]["average_time_per_question"] is not None]
    remediation_plans = db.scalars(
        select(RemediationPlan)
        .join(AssessmentAttempt, AssessmentAttempt.id == RemediationPlan.source_attempt_id)
        .where(AssessmentAttempt.assessment_id == assessment.id)
        .options(selectinload(RemediationPlan.personalized_lessons), selectinload(RemediationPlan.items))
    ).all()
    lessons = [lesson for plan in remediation_plans for lesson in plan.personalized_lessons if lesson.active]
    return {
        "assigned_students": assigned_count,
        "started_students": len({attempt.student_id for attempt in attempts}),
        "completed_students": len({attempt.student_id for attempt in completed_attempts}),
        "participation_rate": round((len({attempt.student_id for attempt in attempts}) / assigned_count) * 100, 2) if assigned_count else 0,
        "average_score": average_or_none(percentages),
        "average_accuracy": average_or_none(accuracies),
        "average_completion": average_or_none(completion_rates),
        "average_duration_seconds": average_or_none(durations),
        "average_time_per_question": average_or_none(time_averages),
        "score_distribution": score_distribution(percentages),
        "weakest_chapters": aggregate_professor_weaknesses(detailed_reports, "chapter_results"),
        "weakest_skills": aggregate_professor_weaknesses(detailed_reports, "skill_results"),
        "students_in_difficulty": len([report for report in detailed_reports if report["global_metrics"]["percentage"] < 70]),
        "open_remediation_plans": len([plan for plan in remediation_plans if plan.status == "active"]),
        "personalized_lessons_generated": len(lessons),
        "personalized_lessons_completed": len([lesson for lesson in lessons if lesson.status == "completed"]),
        "remediation_improvement": calculate_remediation_improvement(db, remediation_plans),
    }


def average_or_none(values: list[float | int]) -> float | None:
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 2)


def score_distribution(percentages: list[float]) -> dict:
    return {
        "0_39": len([value for value in percentages if value < 40]),
        "40_69": len([value for value in percentages if 40 <= value < 70]),
        "70_84": len([value for value in percentages if 70 <= value < 85]),
        "85_100": len([value for value in percentages if value >= 85]),
    }


def aggregate_professor_weaknesses(reports: list[dict], key: str) -> list[dict]:
    buckets: dict[int, dict] = {}
    for report in reports:
        for row in report.get(key, []):
            bucket = buckets.setdefault(row["id"], {"id": row["id"], "name": row["name"], "percentages": [], "total_questions": 0})
            bucket["percentages"].append(row["percentage"])
            bucket["total_questions"] += row["total_questions"]
    results = []
    for bucket in buckets.values():
        average = average_or_none(bucket["percentages"])
        if average is not None and average < 70:
            results.append({"id": bucket["id"], "name": bucket["name"], "average_percentage": average, "total_questions": bucket["total_questions"]})
    return sorted(results, key=lambda item: item["average_percentage"])[:5]


def calculate_remediation_improvement(db: Session, plans: list[RemediationPlan]) -> float | None:
    deltas = []
    for plan in plans:
        comparison = compare_latest_for_plan(db, plan.student, plan.id)
        if comparison.get("variation_points") is not None:
            deltas.append(comparison["variation_points"])
    return average_or_none(deltas)


def serialize_answer(answer: AssessmentAnswer) -> dict:
    question = answer.question
    return {
        "question_id": answer.question_id,
        "question": question.question if question else "",
        "selected_answer": answer.selected_answer,
        "correct_answer": question.correct_answer if question else "",
        "correct": answer.correct,
        "points_awarded": answer.points_awarded,
        "chapter_id": question.chapter_id if question else None,
        "skill_id": question.skill_id if question else None,
        "explanation": question.explanation if question else "",
        "source_document_id": question.source_document_id if question else None,
        "source_page_start": question.source_page_start if question else None,
        "source_page_end": question.source_page_end if question else None,
        "recommendation": "Revoir cette notion" if not answer.correct else "Notion acquise",
    }


def serialize_remediation_plan(plan: RemediationPlan) -> dict:
    total = len(plan.items)
    done = sum(1 for item in plan.items if item.completed)
    lessons = [lesson for lesson in getattr(plan, "personalized_lessons", []) if lesson.active]
    progress_details = personalized_lesson_service.serialize_plan_with_lessons(plan)
    return {
        "id": plan.id,
        "student_id": plan.student_id,
        "source_attempt_id": plan.source_attempt_id,
        "course_id": plan.course_id,
        "course_title": plan.course.title if plan.course else "",
        "subject_id": plan.subject_id,
        "status": plan.status,
        "initial_score": plan.initial_score,
        "progress": progress_details["percentage"] if progress_details["total_steps"] else round((done / total) * 100, 2) if total else 0,
        "total_steps": progress_details["total_steps"],
        "completed_steps": progress_details["completed_steps"],
        "next_step": progress_details["next_step"],
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
        "items": [
            {
                "id": item.id,
                "chapter_id": item.chapter_id,
                "chapter_title": item.chapter.title if item.chapter else "",
                "skill_id": item.skill_id,
                "skill_name": item.skill.name if item.skill else "",
                "item_type": item.item_type,
                "order_index": item.order_index,
                "required": item.required,
                "completed": item.completed,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "reason": item.reason,
                "personalized_lesson_id": item.personalized_lesson_id,
            }
            for item in plan.items
        ],
        "personalized_lessons": [personalized_lesson_service.serialize_lesson(lesson) for lesson in lessons],
    }


def aggregate_by_dimension(db: Session, answers: list[AssessmentAnswer], dimension: str) -> list[dict]:
    buckets: dict[str, dict] = {}
    for answer in answers:
        question = answer.question
        if question is None:
            continue
        if dimension == "chapter":
            key = str(question.chapter_id or "none")
            label = question.chapter.title if question.chapter else "Sans chapitre"
        else:
            key = str(question.skill_id or "none")
            label = question.skill.name if question.skill else "Sans competence"
        bucket = buckets.setdefault(key, {"id": None if key == "none" else int(key), "name": label, "correct": 0, "total": 0})
        bucket["total"] += 1
        if answer.correct:
            bucket["correct"] += 1
    return [
        {
            **bucket,
            "percentage": round((bucket["correct"] / bucket["total"]) * 100, 2) if bucket["total"] else 0,
            "mastery": mastery_label(db, round((bucket["correct"] / bucket["total"]) * 100, 2) if bucket["total"] else 0),
        }
        for bucket in buckets.values()
    ]


def create_remediation_from_attempt(db: Session, attempt: AssessmentAttempt, assessment: Assessment) -> RemediationPlan | None:
    weak_answers = [answer for answer in attempt.answers if not answer.correct]
    if not weak_answers:
        return None
    plan = RemediationPlan(
        student_id=attempt.student_id,
        source_attempt_id=attempt.id,
        course_id=assessment.course_id,
        subject_id=assessment.subject_id,
        initial_score=attempt.percentage,
    )
    db.add(plan)
    db.flush()
    seen = set()
    order = 1
    for answer in weak_answers:
        question = answer.question
        key = (question.chapter_id if question else None, question.skill_id if question else None)
        if key in seen:
            continue
        seen.add(key)
        for item_type in ["chapter", "example", "exercise", "chatbot_context"]:
            db.add(
                RemediationItem(
                    remediation_plan_id=plan.id,
                    chapter_id=key[0],
                    skill_id=key[1],
                    item_type=item_type,
                    order_index=order,
                    reason="Question incorrecte dans l'evaluation initiale.",
                )
            )
            order += 1
    create_notification(db, attempt.student_id, "remediation", "Parcours personnalise cree", "Un parcours cible est disponible apres votre evaluation.")
    return plan


def get_owned_classroom(db: Session, user: UserProfile, classroom_id: int) -> Classroom:
    classroom = db.scalars(select(Classroom).where(Classroom.id == classroom_id).options(selectinload(Classroom.memberships).selectinload(ClassroomMembership.student))).first()
    if classroom is None:
        raise HTTPException(status_code=404, detail="Classe introuvable")
    if not is_admin(user) and classroom.professor_id != user.id:
        raise HTTPException(status_code=403, detail="Classe non autorisee")
    return classroom


def get_owned_assessment(db: Session, user: UserProfile, assessment_id: int) -> Assessment:
    assessment = db.scalars(select(Assessment).where(Assessment.id == assessment_id).options(*assessment_options())).first()
    if assessment is None:
        raise HTTPException(status_code=404, detail="Evaluation introuvable")
    if not is_admin(user) and assessment.professor_id != user.id:
        raise HTTPException(status_code=403, detail="Evaluation non autorisee")
    return assessment


def get_owned_personalized_assessment(db: Session, user: UserProfile, assessment_id: int) -> Assessment:
    assessment = get_owned_assessment(db, user, assessment_id)
    if assessment.assessment_type != "personalized":
        raise HTTPException(status_code=422, detail="Cette evaluation n'est pas un test personnalise")
    return assessment


def source_questions_for_personalized_assessment(db: Session, assessment: Assessment) -> list[str]:
    source_ids = {question.source_question_id for question in assessment.questions if question.source_question_id}
    if not source_ids:
        return []
    return [
        question.question
        for question in db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.id.in_(source_ids))).all()
    ]


def get_student_assessment_model(db: Session, user: UserProfile, assessment_id: int) -> Assessment:
    assignment = get_assignment(db, user, assessment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Evaluation introuvable")
    return db.scalars(select(Assessment).where(Assessment.id == assessment_id).options(*assessment_options())).one()


def get_assignment(db: Session, user: UserProfile, assessment_id: int) -> AssessmentAssignment | None:
    return db.scalars(select(AssessmentAssignment).where(AssessmentAssignment.assessment_id == assessment_id, AssessmentAssignment.student_id == user.id)).first()


def get_attempt_for_user(db: Session, user: UserProfile, attempt_id: int) -> AssessmentAttempt:
    query = select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id).options(
        selectinload(AssessmentAttempt.assessment),
        selectinload(AssessmentAttempt.student),
        selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.chapter),
        selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question).selectinload(AssessmentQuestion.skill),
    )
    attempt = db.scalars(query).first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Tentative introuvable")
    if not is_admin(user) and attempt.student_id != user.id and attempt.assessment.professor_id != user.id:
        raise HTTPException(status_code=403, detail="Resultat non autorise")
    return attempt


def replace_assessment_questions(db: Session, assessment: Assessment, questions: list[dict]) -> None:
    if not questions:
        return
    assessment.questions.clear()
    db.flush()
    for index, item in enumerate(questions, start=1):
        validate_question_payload(db, assessment, item)
        assessment.questions.append(
            AssessmentQuestion(
                chapter_id=item.get("chapter_id"),
                skill_id=item.get("skill_id"),
                question=str(item["question"]).strip(),
                choices=item.get("choices") or [],
                correct_answer=item.get("correct_answer") or item.get("answer"),
                explanation=item.get("explanation") or "",
                difficulty_level_id=item.get("difficulty_level_id"),
                points=float(item.get("points") or 1),
                order_index=int(item.get("order_index") or index),
                active=item.get("active", True) is not False,
                source_document_id=item.get("source_document_id"),
                source_page_start=item.get("source_page_start"),
                source_page_end=item.get("source_page_end"),
                source_attempt_id=item.get("source_attempt_id"),
                source_question_id=item.get("source_question_id"),
                generation_method=item.get("generation_method"),
                similarity_score=item.get("similarity_score"),
                adaptation_reason=item.get("adaptation_reason"),
            )
        )


def validate_question_payload(db: Session, assessment: Assessment, payload: dict) -> None:
    choices = payload.get("choices") or []
    answer = payload.get("correct_answer") or payload.get("answer")
    if not str(payload.get("question", "")).strip():
        raise HTTPException(status_code=422, detail="La question est obligatoire")
    if not isinstance(choices, list) or len(choices) < 2:
        raise HTTPException(status_code=422, detail="Une question doit avoir au moins deux choix")
    if answer not in choices:
        raise HTTPException(status_code=422, detail="La bonne reponse doit etre presente dans les choix")
    chapter_id = payload.get("chapter_id")
    if chapter_id is not None:
        chapter = db.get(CourseChapter, int(chapter_id))
        if chapter is None or chapter.course_id != assessment.course_id:
            raise HTTPException(status_code=422, detail="Le chapitre doit appartenir au cours selectionne")
    skill_id = payload.get("skill_id")
    if skill_id is not None:
        skill = db.get(Skill, int(skill_id))
        if skill is None or (skill.course_id and skill.course_id != assessment.course_id):
            raise HTTPException(status_code=422, detail="La competence doit appartenir au cours selectionne")


def assign_assessment_to_classroom(db: Session, assessment: Assessment, memberships: list[ClassroomMembership] | None = None) -> int:
    if assessment.classroom_id is None:
        return 0
    memberships = memberships if memberships is not None else active_classroom_memberships(db, assessment.classroom_id)
    for membership in memberships:
        if not db.scalars(select(AssessmentAssignment).where(AssessmentAssignment.assessment_id == assessment.id, AssessmentAssignment.student_id == membership.student_id)).first():
            db.add(AssessmentAssignment(assessment_id=assessment.id, student_id=membership.student_id, classroom_id=assessment.classroom_id, status="assigned"))
    return len(memberships)


def active_classroom_memberships(db: Session, classroom_id: int) -> list[ClassroomMembership]:
    return db.scalars(
        select(ClassroomMembership).where(
            ClassroomMembership.classroom_id == classroom_id,
            ClassroomMembership.active.is_(True),
        )
    ).all()


def resolve_student(db: Session, payload: dict) -> UserProfile:
    student_id = payload.get("student_id")
    email = str(payload.get("email") or "").strip().lower()
    query = select(UserProfile)
    if student_id:
        query = query.where(UserProfile.id == int(student_id))
    elif email:
        query = query.where(func.lower(UserProfile.email) == email)
    else:
        raise HTTPException(status_code=422, detail="student_id ou email obligatoire")
    student = db.scalars(query).first()
    if student is None:
        raise HTTPException(status_code=404, detail="Etudiant introuvable")
    if student.role != UserRole.STUDENT.value:
        raise HTTPException(status_code=422, detail="Seuls les comptes student peuvent rejoindre une classe")
    return student


def enforce_assessment_available(db: Session, user: UserProfile, assessment: Assessment) -> None:
    if assessment.status != "published":
        raise HTTPException(status_code=404, detail="Evaluation non disponible")
    now = datetime.utcnow()
    if assessment.publication_at and assessment.publication_at > now:
        raise HTTPException(status_code=404, detail="Evaluation non encore publiee")
    if assessment.expires_at and assessment.expires_at < now:
        raise HTTPException(status_code=409, detail="Evaluation expiree")


def is_visible_to_student(assessment: Assessment) -> bool:
    now = datetime.utcnow()
    return assessment.status == "published" and (assessment.publication_at is None or assessment.publication_at <= now)


def ensure_skill_for_chapter(db: Session, subject_id: int, course_id: int, chapter: CourseChapter) -> Skill | None:
    skill = db.scalars(select(Skill).where(Skill.chapter_id == chapter.id, Skill.course_id == course_id)).first()
    if skill:
        return skill
    skill = Skill(subject_id=subject_id, course_id=course_id, chapter_id=chapter.id, name=chapter.title, description=f"Competence liee au chapitre {chapter.title}")
    db.add(skill)
    db.flush()
    return skill


def first_rag_document_for_course(db: Session, course_id: int):
    return rag_document_service.get_active_document_for_course(db, course_id)


def mastery_label(db: Session, percentage: float) -> str:
    thresholds = db.scalars(select(MasteryThreshold).where(MasteryThreshold.active.is_(True)).order_by(MasteryThreshold.min_percentage)).all()
    for threshold in thresholds:
        if threshold.min_percentage <= percentage <= threshold.max_percentage:
            return threshold.label
    if percentage < 40:
        return "Non acquis"
    if percentage < 70:
        return "En cours d'acquisition"
    if percentage < 85:
        return "Acquis"
    return "Maitrise"


def create_notification(db: Session, user_id: int, notification_type: str, title: str, message: str) -> None:
    existing = db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == notification_type,
            Notification.title == title,
            Notification.message == message,
        )
    ).first()
    if existing is not None:
        return
    db.add(Notification(id=str(uuid4()), user_id=user_id, type=notification_type, title=title, message=message, read=False))


def _has_completed_attempt(attempts: list[AssessmentAttempt], assessment_id: int) -> bool:
    return any(attempt.assessment_id == assessment_id and attempt.completed for attempt in attempts)


def build_student_next_action(available: list[Assessment], active_plan: RemediationPlan | None, personalized_available: list[Assessment], weakest_skill: dict | None) -> dict:
    if personalized_available:
        return {
            "title": "Passer le test personnalisé",
            "description": personalized_available[0].title,
            "path": f"/assessments/{personalized_available[0].id}",
        }
    if active_plan:
        return {
            "title": "Continuer le parcours personnalisé",
            "description": active_plan.course.title if active_plan.course else "Remédiation en cours",
            "path": f"/remediation/{active_plan.id}",
        }
    if available:
        return {
            "title": "Passer une évaluation",
            "description": available[0].title,
            "path": f"/assessments/{available[0].id}",
        }
    if weakest_skill:
        return {
            "title": "Revoir la compétence la plus faible",
            "description": weakest_skill["name"],
            "path": "/courses",
        }
    return {
        "title": "Continuer le parcours",
        "description": "Aucune évaluation prioritaire pour le moment.",
        "path": "/courses",
    }


def create_audit_log(db: Session, actor: UserProfile, action: str, target_type: str, target_id: str | int | None, before_data, after_data) -> None:
    db.add(AdminAuditLog(admin_user_id=actor.id, action=action, target_type=target_type, target_id=str(target_id) if target_id is not None else None, before_data=before_data, after_data=after_data))


def assessment_options():
    return [
        selectinload(Assessment.course),
        selectinload(Assessment.classroom),
        selectinload(Assessment.questions).selectinload(AssessmentQuestion.chapter),
        selectinload(Assessment.questions).selectinload(AssessmentQuestion.skill),
        selectinload(Assessment.assignments),
        selectinload(Assessment.attempts),
    ]


def generate_class_code(db: Session) -> str:
    base = "EDU"
    for _ in range(20):
        code = f"{base}-{uuid4().hex[:6].upper()}"
        if db.scalar(select(Classroom.id).where(Classroom.code == code).limit(1)) is None:
            return code
    raise HTTPException(status_code=500, detail="Impossible de generer un code de classe")


def validate_choice(value: str, allowed: set[str], message: str) -> str:
    clean = str(value or "").strip()
    if clean not in allowed:
        raise HTTPException(status_code=422, detail=message)
    return clean


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    clean = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(clean)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date invalide") from exc


def find_plan_id(db: Session, attempt_id: int) -> int | None:
    return db.scalar(select(RemediationPlan.id).where(RemediationPlan.source_attempt_id == attempt_id).limit(1))
