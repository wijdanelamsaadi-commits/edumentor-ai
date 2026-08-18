from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.roles import UserRole
from app.models.persistence import (
    AdminAuditLog,
    Assessment,
    AssessmentAnswer,
    AssessmentAssignment,
    AssessmentAttempt,
    Course,
    CourseChapter,
    CourseExample,
    CourseObjective,
    CourseProgress,
    CourseSkill,
    DiagnosticResult,
    Quiz,
    QuizQuestion,
    QuizResult,
    RemediationPlan,
    Classroom,
    ClassroomMembership,
    UserProfile,
)
from app.schemas.lesson_content import validate_structured_blocks
from app.services import course_service, regional_exam_service, student_weakness_model_service, study_path_service

DOCS_DIR = Path(get_settings().get("docs_dir") or Path(__file__).resolve().parents[2] / "docs") / "courses"
MAX_PDF_SIZE = 20 * 1024 * 1024


def validate_blocks_or_422(blocks):
    try:
        return validate_structured_blocks(blocks)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"structured_content invalide: {exc}") from exc


def is_admin(user: UserProfile) -> bool:
    return user.role == UserRole.ADMIN.value


def create_audit_log(
    db: Session,
    actor: UserProfile,
    action: str,
    target_type: str,
    target_id: str | int | None,
    before_data: dict | list | None,
    after_data: dict | list | None,
) -> None:
    db.add(
        AdminAuditLog(
            admin_user_id=actor.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            before_data=before_data,
            after_data=after_data,
        )
    )


def get_professor_owned_course(db: Session, current_user: UserProfile, course_id: int) -> Course:
    course = course_service.get_course_model(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if is_admin(current_user):
        return course
    if course.professor_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cours non autorise")
    return course


def serialize_professor_course(course: Course) -> dict:
    data = course_service.serialize_course(course, detail=True)
    data["chapter_count"] = len(data.get("chapters", []))
    data["quiz_count"] = 1 if data.get("quiz") else 0
    return data


def get_dashboard(db: Session, current_user: UserProfile) -> dict:
    courses = _owned_courses(db, current_user)
    course_ids = [course.id for course in courses]
    progress_rows = _progress_for_courses(db, course_ids)
    quiz_rows = _quiz_results_for_courses(db, course_ids)
    student_ids = {row.user_id for row in progress_rows} | {row.user_id for row in quiz_rows}
    average_quiz_score = round(sum(row.score for row in quiz_rows) / len(quiz_rows), 2) if quiz_rows else 0
    average_course_progress = round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0

    assessment_stats = _assessment_dashboard_stats(db, current_user)

    return {
        "professor_id": current_user.id,
        "name": current_user.full_name,
        "email": current_user.email,
        "role": current_user.role,
        "total_courses": len(courses),
        "published_courses": sum(1 for course in courses if course.published),
        "draft_courses": sum(1 for course in courses if not course.published and (course.status or "draft") != "archived"),
        "archived_courses": sum(1 for course in courses if (course.status or "") == "archived"),
        "total_students": len(student_ids),
        "total_quiz_attempts": len(quiz_rows),
        "average_quiz_score": average_quiz_score,
        "average_course_progress": average_course_progress,
        "recent_courses": [serialize_professor_course(course) for course in sorted(courses, key=lambda item: item.updated_at or item.created_at, reverse=True)[:5]],
        "recent_student_activity": _recent_student_activity(db, course_ids),
        "student_tracking": list_tracked_students(db, current_user)[:8],
        **assessment_stats,
        **study_path_service.professor_dashboard_stats(db, current_user),
    }


def list_tracked_students(db: Session, current_user: UserProfile) -> list[dict]:
    student_ids = professor_student_ids(db, current_user)
    users = list(db.scalars(select(UserProfile).where(UserProfile.id.in_(student_ids)).order_by(UserProfile.full_name))) if student_ids else []
    return [serialize_tracked_student(db, student) for student in users]


def get_tracked_student_detail(db: Session, current_user: UserProfile, student_id: int) -> dict:
    student = get_professor_tracked_student(db, current_user, student_id)
    prediction = student_weakness_model_service.predict_student_weaknesses(db, student)
    progress_rows = list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == student.id).order_by(CourseProgress.updated_at.desc())))
    quiz_rows = list(db.scalars(select(QuizResult).where(QuizResult.user_id == student.id).order_by(QuizResult.created_at.desc())))
    attempt_rows = list(db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.student_id == student.id)
        .options(selectinload(AssessmentAttempt.assessment))
        .order_by(AssessmentAttempt.submitted_at.desc(), AssessmentAttempt.started_at.desc())
    ))
    diagnostic_rows = list(db.scalars(select(DiagnosticResult).where(DiagnosticResult.user_id == student.id).order_by(DiagnosticResult.created_at.desc())))
    classrooms = list(db.scalars(
        select(Classroom)
        .join(ClassroomMembership, ClassroomMembership.classroom_id == Classroom.id)
        .where(ClassroomMembership.student_id == student.id, ClassroomMembership.active.is_(True))
        .order_by(Classroom.name)
    ))
    return {
        **serialize_tracked_student(db, student),
        "classrooms": [
            {"id": classroom.id, "name": classroom.name, "code": classroom.code}
            for classroom in classrooms
            if is_admin(current_user) or classroom.professor_id == current_user.id
        ],
        "diagnostics": [
            {
                "id": row.id,
                "level": row.level,
                "score": row.score,
                "total": row.total,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "results_by_topic": row.results_by_topic or [],
            }
            for row in diagnostic_rows[:5]
        ],
        "course_progress": [
            {
                "course_id": row.course_id,
                "course_title": db.get(Course, row.course_id).title if db.get(Course, row.course_id) else "Cours",
                "progress": row.progress,
                "chapters": row.chapters or [],
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in progress_rows
        ],
        "quiz_results": [
            {
                "id": row.id,
                "course_id": row.course_id,
                "course_title": db.get(Course, row.course_id).title if db.get(Course, row.course_id) else "Cours",
                "score": row.score,
                "correct": row.correct,
                "total": row.total,
                "recommendation": row.recommendation,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in quiz_rows[:10]
        ],
        "regional_attempts": [
            {
                "attempt_id": attempt.id,
                "assessment_id": attempt.assessment_id,
                "title": attempt.assessment.title if attempt.assessment else "Examen regional",
                "status": "completed" if attempt.completed else "in_progress",
                "score": attempt.score,
                "percentage": attempt.percentage,
                "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
                "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            }
            for attempt in attempt_rows
            if regional_exam_service.is_regional_assessment(attempt.assessment)
        ][:10],
        "competencies": [
            sanitize_prediction_row(row)
            for row in prediction.get("competencies", [])
        ],
        "weak_points": [sanitize_weak_point(row) for row in prediction.get("weak_points", [])],
        "recommendations": prediction.get("priority_recommendations", []),
    }


def list_courses(
    db: Session,
    current_user: UserProfile,
    search: str = "",
    subject_id: int | None = None,
    education_level_id: int | None = None,
    difficulty_level_id: int | None = None,
    status_filter: str = "",
    published: bool | None = None,
) -> list[dict]:
    query = select(Course).options(*course_service.course_load_options(include_quiz=True)).order_by(Course.updated_at.desc(), Course.id.desc())
    if not is_admin(current_user):
        query = query.where(Course.professor_id == current_user.id)
    if search.strip():
        pattern = f"%{search.strip()}%"
        query = query.where(or_(Course.title.ilike(pattern), Course.summary.ilike(pattern), Course.description.ilike(pattern)))
    if subject_id:
        query = query.where(Course.subject_id == subject_id)
    if education_level_id:
        query = query.where(Course.education_level_id == education_level_id)
    if difficulty_level_id:
        query = query.where(Course.difficulty_level_id == difficulty_level_id)
    if status_filter and status_filter != "all":
        query = query.where(Course.status == status_filter)
    if published is not None:
        query = query.where(Course.published.is_(published))
    return [_with_activity_counts(db, course_service.serialize_course(course, detail=True)) for course in db.scalars(query)]


def create_course(db: Session, current_user: UserProfile, payload: dict) -> dict:
    data = dict(payload)
    data.pop("professor_id", None)
    data["professor_id"] = current_user.id
    data["published"] = False
    data["status"] = "draft"
    data.setdefault("progress", 0)
    course = course_service.create_course(db, data)
    create_audit_log(db, current_user, "create_professor_course", "course", course["id"], None, course)
    db.commit()
    return course


def update_course(db: Session, current_user: UserProfile, course_id: int, payload: dict) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    before = course_service.serialize_course(course, detail=True)
    data = dict(payload)
    data.pop("professor_id", None)
    updated = course_service.update_course(db, course_id, data)
    create_audit_log(db, current_user, "update_professor_course", "course", course_id, before, updated)
    db.commit()
    return updated


def delete_course(db: Session, current_user: UserProfile, course_id: int) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    before = course_service.serialize_course(course, detail=True)
    has_activity = db.scalar(select(CourseProgress.id).where(CourseProgress.course_id == course_id).limit(1)) is not None
    has_quiz_result = db.scalar(select(QuizResult.id).where(QuizResult.course_id == course_id).limit(1)) is not None
    if has_activity or has_quiz_result:
        course.status = "archived"
        course.published = False
        course.updated_at = datetime.utcnow()
        result = {"archived": True, "deleted": False, "course_id": course_id}
        create_audit_log(db, current_user, "archive_professor_course", "course", course_id, before, result)
        db.commit()
        return result
    db.delete(course)
    result = {"deleted": True, "course_id": course_id}
    create_audit_log(db, current_user, "delete_professor_course", "course", course_id, before, result)
    db.commit()
    return result


def publish_course(db: Session, current_user: UserProfile, course_id: int) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    if not course.title.strip() or not course.subject_id or not (course.description.strip() or course.summary.strip()):
        raise HTTPException(status_code=400, detail="Le cours est incomplet")
    if not course.chapters:
        raise HTTPException(status_code=400, detail="Ajoutez au moins un chapitre avant publication")
    before = course_service.serialize_course(course, detail=True)
    course.published = True
    course.status = "published"
    course.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(course)
    result = course_service.get_course_detail(db, course_id, include_unpublished=True)
    create_audit_log(db, current_user, "publish_professor_course", "course", course_id, before, result)
    db.commit()
    return result


def unpublish_course(db: Session, current_user: UserProfile, course_id: int) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    before = course_service.serialize_course(course, detail=True)
    course.published = False
    course.status = "draft"
    course.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(course)
    result = course_service.get_course_detail(db, course_id, include_unpublished=True)
    create_audit_log(db, current_user, "unpublish_professor_course", "course", course_id, before, result)
    db.commit()
    return result


def archive_course(db: Session, current_user: UserProfile, course_id: int) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    before = course_service.serialize_course(course, detail=True)
    course.published = False
    course.status = "archived"
    course.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(course)
    result = course_service.get_course_detail(db, course_id, include_unpublished=True)
    create_audit_log(db, current_user, "archive_professor_course", "course", course_id, before, result)
    db.commit()
    return result


def list_chapters(db: Session, current_user: UserProfile, course_id: int) -> list[dict]:
    course = get_professor_owned_course(db, current_user, course_id)
    return [_serialize_chapter(chapter) for chapter in sorted(course.chapters, key=lambda item: item.position)]


def create_chapter(db: Session, current_user: UserProfile, course_id: int, payload: dict) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    _validate_chapter_payload(payload)
    next_position = (max([chapter.position for chapter in course.chapters] or [0]) + 1)
    chapter = CourseChapter(
        course_id=course_id,
        title=payload["title"].strip(),
        content=payload["content"].strip(),
        structured_content=validate_blocks_or_422(payload.get("structured_content")),
        duration=payload.get("duration") or payload.get("estimated_duration") or "20 min",
        estimated_duration=payload.get("estimated_duration") or payload.get("duration") or "20 min",
        status=payload.get("status", "locked"),
        openable=payload.get("openable", payload.get("status") in {"completed", "active"}) is True,
        active=payload.get("active", True) is not False,
        position=int(payload.get("position") or next_position),
    )
    db.add(chapter)
    course.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(chapter)
    create_audit_log(db, current_user, "create_chapter", "course_chapter", chapter.id, None, _serialize_chapter(chapter))
    db.commit()
    return _serialize_chapter(chapter)


def update_chapter(db: Session, current_user: UserProfile, course_id: int, chapter_id: int, payload: dict) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    chapter = _get_chapter_for_course(course, chapter_id)
    before = _serialize_chapter(chapter)
    if "title" in payload:
        if not str(payload["title"]).strip():
            raise HTTPException(status_code=422, detail="Le titre du chapitre est obligatoire")
        chapter.title = str(payload["title"]).strip()
    if "content" in payload:
        if not str(payload["content"]).strip():
            raise HTTPException(status_code=422, detail="Le contenu du chapitre est obligatoire")
        chapter.content = str(payload["content"]).strip()
    for field in ["duration", "estimated_duration", "status", "openable", "active", "position", "completed"]:
        if field in payload:
            setattr(chapter, field, payload[field])
    if "structured_content" in payload:
        chapter.structured_content = validate_blocks_or_422(payload.get("structured_content"))
    chapter.updated_at = datetime.utcnow()
    course.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(chapter)
    after = _serialize_chapter(chapter)
    create_audit_log(db, current_user, "update_chapter", "course_chapter", chapter.id, before, after)
    db.commit()
    return after


def delete_chapter(db: Session, current_user: UserProfile, course_id: int, chapter_id: int) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    chapter = _get_chapter_for_course(course, chapter_id)
    if db.scalar(select(QuizQuestion.id).where(QuizQuestion.chapter_id == chapter_id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="Ce chapitre est lie a des questions de quiz")
    before = _serialize_chapter(chapter)
    db.delete(chapter)
    course.updated_at = datetime.utcnow()
    create_audit_log(db, current_user, "delete_chapter", "course_chapter", chapter_id, before, {"deleted": True})
    db.commit()
    return {"deleted": True, "chapter_id": chapter_id}


def reorder_chapters(db: Session, current_user: UserProfile, course_id: int, payload: dict) -> list[dict]:
    course = get_professor_owned_course(db, current_user, course_id)
    chapter_ids = payload.get("chapter_ids") or []
    chapters_by_id = {chapter.id: chapter for chapter in course.chapters}
    if set(chapter_ids) != set(chapters_by_id):
        raise HTTPException(status_code=422, detail="La liste des chapitres est invalide")
    for index, chapter_id in enumerate(chapter_ids, start=1):
        chapters_by_id[chapter_id].position = index
        chapters_by_id[chapter_id].updated_at = datetime.utcnow()
    course.updated_at = datetime.utcnow()
    db.commit()
    return list_chapters(db, current_user, course_id)


def replace_items(db: Session, current_user: UserProfile, course_id: int, item_type: str, items: list) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    before = course_service.serialize_course(course, detail=True).get(item_type)
    if item_type == "objectives":
        course_service.replace_objectives(course, items)
    elif item_type == "skills":
        course_service.replace_skills(course, items)
    elif item_type == "examples":
        course_service.replace_examples(course, items)
    else:
        raise HTTPException(status_code=404, detail="Type de contenu introuvable")
    course.updated_at = datetime.utcnow()
    db.commit()
    result = course_service.get_course_detail(db, course_id, include_unpublished=True)
    create_audit_log(db, current_user, f"replace_{item_type}", "course", course_id, before, result.get(item_type))
    db.commit()
    return {"course_id": course_id, item_type: result.get(item_type)}


def get_quizzes(db: Session, current_user: UserProfile, course_id: int) -> list[dict]:
    course = get_professor_owned_course(db, current_user, course_id)
    return [course_service.serialize_quiz(course.quiz, include_answers=True)] if course.quiz else []


def create_quiz(db: Session, current_user: UserProfile, course_id: int, payload: dict) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    if course.quiz is not None:
        raise HTTPException(status_code=409, detail="Ce cours possede deja un quiz")
    _validate_quiz_payload(payload, require_questions=False)
    quiz = Quiz(
        course_id=course_id,
        title=payload.get("title", "Quiz du cours"),
        description=payload.get("description", ""),
        passing_score=int(payload.get("passing_score", 70) or 70),
        active=payload.get("active", True) is not False,
        published=payload.get("published", payload.get("active", True)) is not False,
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    if payload.get("questions"):
        for question in payload["questions"]:
            add_question(db, current_user, quiz.id, question)
        db.refresh(quiz)
    result = course_service.serialize_quiz(quiz, include_answers=True)
    create_audit_log(db, current_user, "create_quiz", "quiz", quiz.id, None, result)
    db.commit()
    return result


def get_quiz(db: Session, current_user: UserProfile, quiz_id: int) -> dict:
    quiz = _get_owned_quiz(db, current_user, quiz_id)
    return course_service.serialize_quiz(quiz, include_answers=True)


def update_quiz(db: Session, current_user: UserProfile, quiz_id: int, payload: dict) -> dict:
    quiz = _get_owned_quiz(db, current_user, quiz_id)
    before = course_service.serialize_quiz(quiz, include_answers=True)
    if "passing_score" in payload:
        score = int(payload["passing_score"])
        if score < 0 or score > 100:
            raise HTTPException(status_code=422, detail="passing_score doit etre compris entre 0 et 100")
        quiz.passing_score = score
    for field in ["title", "description", "active", "published"]:
        if field in payload:
            setattr(quiz, field, payload[field])
    quiz.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(quiz)
    result = course_service.serialize_quiz(quiz, include_answers=True)
    create_audit_log(db, current_user, "update_quiz", "quiz", quiz.id, before, result)
    db.commit()
    return result


def delete_quiz(db: Session, current_user: UserProfile, quiz_id: int) -> dict:
    quiz = _get_owned_quiz(db, current_user, quiz_id)
    before = course_service.serialize_quiz(quiz, include_answers=True)
    db.delete(quiz)
    create_audit_log(db, current_user, "delete_quiz", "quiz", quiz_id, before, {"deleted": True})
    db.commit()
    return {"deleted": True, "quiz_id": quiz_id}


def add_question(db: Session, current_user: UserProfile, quiz_id: int, payload: dict) -> dict:
    quiz = _get_owned_quiz(db, current_user, quiz_id)
    _validate_question_payload(db, quiz, payload)
    next_position = (max([question.position for question in quiz.questions] or [0]) + 1)
    question = QuizQuestion(
        quiz_id=quiz.id,
        chapter_id=payload.get("chapter_id"),
        question=payload["question"].strip(),
        choices=payload["choices"],
        answer=payload["answer"],
        explanation=payload.get("explanation", ""),
        difficulty_level_id=payload.get("difficulty_level_id"),
        active=payload.get("active", True) is not False,
        position=int(payload.get("position") or next_position),
    )
    db.add(question)
    quiz.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(question)
    result = _serialize_question(question, include_answer=True)
    create_audit_log(db, current_user, "create_quiz_question", "quiz_question", question.id, None, result)
    db.commit()
    return result


def update_question(db: Session, current_user: UserProfile, quiz_id: int, question_id: int, payload: dict) -> dict:
    quiz = _get_owned_quiz(db, current_user, quiz_id)
    question = _get_question_for_quiz(quiz, question_id)
    merged = {
        "question": payload.get("question", question.question),
        "choices": payload.get("choices", question.choices),
        "answer": payload.get("answer", question.answer),
        "chapter_id": payload.get("chapter_id", question.chapter_id),
        "difficulty_level_id": payload.get("difficulty_level_id", question.difficulty_level_id),
    }
    _validate_question_payload(db, quiz, merged)
    before = _serialize_question(question, include_answer=True)
    for field in ["question", "choices", "answer", "explanation", "chapter_id", "difficulty_level_id", "position", "active"]:
        if field in payload:
            setattr(question, field, payload[field])
    quiz.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(question)
    result = _serialize_question(question, include_answer=True)
    create_audit_log(db, current_user, "update_quiz_question", "quiz_question", question.id, before, result)
    db.commit()
    return result


def delete_question(db: Session, current_user: UserProfile, quiz_id: int, question_id: int) -> dict:
    quiz = _get_owned_quiz(db, current_user, quiz_id)
    question = _get_question_for_quiz(quiz, question_id)
    before = _serialize_question(question, include_answer=True)
    db.delete(question)
    quiz.updated_at = datetime.utcnow()
    create_audit_log(db, current_user, "delete_quiz_question", "quiz_question", question_id, before, {"deleted": True})
    db.commit()
    return {"deleted": True, "question_id": question_id}


def reorder_questions(db: Session, current_user: UserProfile, quiz_id: int, payload: dict) -> list[dict]:
    quiz = _get_owned_quiz(db, current_user, quiz_id)
    question_ids = payload.get("question_ids") or []
    questions_by_id = {question.id: question for question in quiz.questions}
    if set(question_ids) != set(questions_by_id):
        raise HTTPException(status_code=422, detail="La liste des questions est invalide")
    for index, question_id in enumerate(question_ids, start=1):
        questions_by_id[question_id].position = index
    quiz.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(quiz)
    return [_serialize_question(question, include_answer=True) for question in quiz.questions]


def upload_document(db: Session, current_user: UserProfile, course_id: int, file: UploadFile) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptes")
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Le type MIME du support doit etre PDF")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    safe_original = _safe_pdf_name(file.filename)
    unique_name = f"professor_{current_user.id}_course_{course.id}_{uuid4().hex}_{safe_original}"
    target = DOCS_DIR / unique_name
    temp = DOCS_DIR / f"{unique_name}.uploading"
    size = 0
    with temp.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_PDF_SIZE:
                temp.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="PDF trop volumineux")
            output.write(chunk)

    old_url = course.pdf_url
    before = course_service.serialize_course(course, detail=True)
    if old_url:
        from app.services.rag_document_service import mark_course_document_outdated

        mark_course_document_outdated(db, course)
    shutil.move(str(temp), str(target))
    course.pdf_url = f"/docs/courses/{unique_name}"
    course.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        target.unlink(missing_ok=True)
        db.rollback()
        raise
    if old_url:
        old_target = DOCS_DIR / Path(old_url).name
        if _is_safe_doc_path(old_target):
            old_target.unlink(missing_ok=True)
    result = {"pdf_url": course.pdf_url, "file_name": unique_name, "size": size, "indexing_status": "pending"}
    create_audit_log(db, current_user, "replace_professor_pdf" if old_url else "upload_professor_pdf", "course_pdf", course_id, before, result)
    db.commit()
    return result


def delete_document(db: Session, current_user: UserProfile, course_id: int) -> dict:
    course = get_professor_owned_course(db, current_user, course_id)
    before = course_service.serialize_course(course, detail=True)
    if course.pdf_url:
        from app.services.rag_document_service import mark_course_document_outdated

        mark_course_document_outdated(db, course)
        target = DOCS_DIR / Path(course.pdf_url).name
        if _is_safe_doc_path(target):
            target.unlink(missing_ok=True)
    course.pdf_url = None
    course.updated_at = datetime.utcnow()
    result = {"deleted": True, "course_id": course_id}
    create_audit_log(db, current_user, "delete_professor_pdf", "course_pdf", course_id, before, result)
    db.commit()
    return result


def get_students(db: Session, current_user: UserProfile, course_id: int) -> list[dict]:
    get_professor_owned_course(db, current_user, course_id)
    progress_rows = db.scalars(select(CourseProgress).where(CourseProgress.course_id == course_id)).all()
    quiz_rows = db.scalars(select(QuizResult).where(QuizResult.course_id == course_id)).all()
    student_ids = sorted({row.user_id for row in progress_rows} | {row.user_id for row in quiz_rows})
    users = {user.id: user for user in db.scalars(select(UserProfile).where(UserProfile.id.in_(student_ids))).all()} if student_ids else {}
    by_user_progress = {row.user_id: row for row in progress_rows}
    by_user_quizzes: dict[int, list[QuizResult]] = {}
    for row in quiz_rows:
        by_user_quizzes.setdefault(row.user_id, []).append(row)
    students = []
    for student_id in student_ids:
        user = users.get(student_id)
        user_quizzes = by_user_quizzes.get(student_id, [])
        average_score = round(sum(row.score for row in user_quizzes) / len(user_quizzes), 2) if user_quizzes else 0
        last_dates = [row.updated_at for row in [by_user_progress.get(student_id)] if row] + [row.created_at for row in user_quizzes]
        students.append({
            "student_id": student_id,
            "full_name": user.full_name if user else "Etudiant",
            "email": user.email if user else "",
            "progression": by_user_progress.get(student_id).progress if by_user_progress.get(student_id) else 0,
            "last_activity": max(last_dates).isoformat() if last_dates else None,
            "average_score": average_score,
            "quiz_attempts": len(user_quizzes),
        })
    return students


def get_analytics(db: Session, current_user: UserProfile, course_id: int | None = None) -> dict:
    courses = [get_professor_owned_course(db, current_user, course_id)] if course_id else _owned_courses(db, current_user)
    course_ids = [course.id for course in courses]
    progress_rows = _progress_for_courses(db, course_ids)
    quiz_rows = _quiz_results_for_courses(db, course_ids)
    student_ids = {row.user_id for row in progress_rows} | {row.user_id for row in quiz_rows}
    completed = [row for row in progress_rows if row.progress >= 100]
    score_distribution = {
        "0-49": sum(1 for row in quiz_rows if row.score < 50),
        "50-69": sum(1 for row in quiz_rows if 50 <= row.score < 70),
        "70-89": sum(1 for row in quiz_rows if 70 <= row.score < 90),
        "90-100": sum(1 for row in quiz_rows if row.score >= 90),
    }
    chapter_completion = _chapter_completion(progress_rows)
    return {
        "course_id": course_id,
        "total_courses": len(courses),
        "published_courses": sum(1 for course in courses if course.published),
        "active_students": len(student_ids),
        "average_progress": round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0,
        "completion_rate": round((len(completed) / len(progress_rows)) * 100, 2) if progress_rows else 0,
        "quiz_attempts": len(quiz_rows),
        "average_score": round(sum(row.score for row in quiz_rows) / len(quiz_rows), 2) if quiz_rows else 0,
        "score_distribution": score_distribution,
        "least_completed_chapters": chapter_completion[:5],
        "recent_activity": _recent_student_activity(db, course_ids),
    }


def _owned_courses(db: Session, current_user: UserProfile) -> list[Course]:
    query = select(Course).options(*course_service.course_load_options(include_quiz=True)).order_by(Course.updated_at.desc(), Course.id.desc())
    if not is_admin(current_user):
        query = query.where(Course.professor_id == current_user.id)
    return list(db.scalars(query))


def professor_student_ids(db: Session, current_user: UserProfile) -> list[int]:
    query = (
        select(ClassroomMembership.student_id)
        .join(Classroom, Classroom.id == ClassroomMembership.classroom_id)
        .where(ClassroomMembership.active.is_(True), Classroom.active.is_(True))
    )
    if not is_admin(current_user):
        query = query.where(Classroom.professor_id == current_user.id)
    return sorted({int(row) for row in db.scalars(query).all()})


def get_professor_tracked_student(db: Session, current_user: UserProfile, student_id: int) -> UserProfile:
    if student_id not in professor_student_ids(db, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Etudiant non autorise")
    student = db.get(UserProfile, student_id)
    if student is None or student.role != UserRole.STUDENT.value:
        raise HTTPException(status_code=404, detail="Etudiant introuvable")
    return student


def serialize_tracked_student(db: Session, student: UserProfile) -> dict:
    progress_rows = list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == student.id)))
    quiz_rows = list(db.scalars(select(QuizResult).where(QuizResult.user_id == student.id)))
    attempts = list(db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.student_id == student.id)
        .options(selectinload(AssessmentAttempt.assessment))
        .order_by(AssessmentAttempt.submitted_at.desc(), AssessmentAttempt.started_at.desc())
    ))
    diagnostic = db.scalars(select(DiagnosticResult).where(DiagnosticResult.user_id == student.id).order_by(DiagnosticResult.created_at.desc())).first()
    prediction = student_weakness_model_service.predict_student_weaknesses(db, student)
    weak_points = [sanitize_weak_point(row) for row in prediction.get("weak_points", [])]
    completed_attempts = [attempt for attempt in attempts if attempt.completed]
    latest_attempt = completed_attempts[0] if completed_attempts else None
    last_dates = [row.updated_at for row in progress_rows if row.updated_at]
    last_dates.extend(row.created_at for row in quiz_rows if row.created_at)
    last_dates.extend(attempt.submitted_at or attempt.started_at for attempt in attempts if attempt.submitted_at or attempt.started_at)
    average_progress = round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0
    average_quiz = round(sum(row.score for row in quiz_rows) / len(quiz_rows), 2) if quiz_rows else 0
    return {
        "student_id": student.id,
        "full_name": student.full_name,
        "email": student.email,
        "level": diagnostic.level if diagnostic else student.level,
        "global_progress": average_progress,
        "started_courses": sum(1 for row in progress_rows if row.progress > 0),
        "completed_courses": sum(1 for row in progress_rows if row.progress >= 100),
        "quiz_attempts": len(quiz_rows),
        "average_quiz_score": average_quiz,
        "regional_attempts": len([attempt for attempt in attempts if regional_exam_service.is_regional_assessment(attempt.assessment)]),
        "latest_score": latest_attempt.percentage if latest_attempt else None,
        "main_weak_point": weak_points[0] if weak_points else None,
        "general_status": build_student_general_status(average_progress, latest_attempt, weak_points),
        "last_activity": max(last_dates).isoformat() if last_dates else None,
    }


def sanitize_weak_point(row: dict) -> dict:
    return {
        "competence": row.get("competence"),
        "status": row.get("status"),
        "score": row.get("score"),
        "message": row.get("message"),
        "confidence": row.get("confidence"),
    }


def sanitize_prediction_row(row: dict) -> dict:
    return {
        "competence": row.get("competence"),
        "status": row.get("status"),
        "score_percentage": row.get("score_percentage"),
        "recommendation": row.get("recommendation"),
        "confidence": row.get("confidence"),
    }


def build_student_general_status(progress: float, latest_attempt: AssessmentAttempt | None, weak_points: list[dict]) -> str:
    if latest_attempt and latest_attempt.percentage >= 85 and progress >= 75 and not weak_points:
        return "maitrise"
    if weak_points:
        return "a_renforcer"
    if progress <= 20 and latest_attempt is None:
        return "donnees_insuffisantes"
    return "en_progression"


def _with_activity_counts(db: Session, course: dict) -> dict:
    course_id = course["id"]
    course["student_count"] = db.scalar(
        select(func.count(func.distinct(CourseProgress.user_id))).where(CourseProgress.course_id == course_id)
    ) or 0
    if db.scalar(select(Quiz.id).where(Quiz.course_id == course_id).limit(1)) is not None:
        course["quiz_count"] = 1
    else:
        course["quiz_count"] = 0
    return course


def _progress_for_courses(db: Session, course_ids: list[int]) -> list[CourseProgress]:
    if not course_ids:
        return []
    return list(db.scalars(select(CourseProgress).where(CourseProgress.course_id.in_(course_ids))))


def _quiz_results_for_courses(db: Session, course_ids: list[int]) -> list[QuizResult]:
    if not course_ids:
        return []
    return list(db.scalars(select(QuizResult).where(QuizResult.course_id.in_(course_ids))))


def _recent_student_activity(db: Session, course_ids: list[int]) -> list[dict]:
    if not course_ids:
        return []
    rows = db.execute(
        select(CourseProgress, UserProfile, Course)
        .join(UserProfile, UserProfile.id == CourseProgress.user_id)
        .join(Course, Course.id == CourseProgress.course_id)
        .where(CourseProgress.course_id.in_(course_ids))
        .order_by(CourseProgress.updated_at.desc())
        .limit(10)
    ).all()
    return [
        {
            "student_id": user.id,
            "student_name": user.full_name,
            "course_id": course.id,
            "course_title": course.title,
            "progression": progress.progress,
            "date": progress.updated_at.isoformat() if progress.updated_at else None,
        }
        for progress, user, course in rows
    ]


def _assessment_dashboard_stats(db: Session, current_user: UserProfile) -> dict:
    assessment_query = select(Assessment)
    classroom_query = select(Classroom)
    if not is_admin(current_user):
        assessment_query = assessment_query.where(Assessment.professor_id == current_user.id)
        classroom_query = classroom_query.where(Classroom.professor_id == current_user.id)

    assessments = list(db.scalars(assessment_query))
    assessment_ids = [assessment.id for assessment in assessments]
    classrooms = list(db.scalars(classroom_query))
    classroom_ids = [classroom.id for classroom in classrooms]
    memberships = list(db.scalars(select(ClassroomMembership).where(ClassroomMembership.classroom_id.in_(classroom_ids), ClassroomMembership.active.is_(True)))) if classroom_ids else []
    assignments = list(db.scalars(select(AssessmentAssignment).where(AssessmentAssignment.assessment_id.in_(assessment_ids)))) if assessment_ids else []
    attempts = list(db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.assessment_id.in_(assessment_ids)))) if assessment_ids else []
    completed_attempts = [attempt for attempt in attempts if attempt.completed]
    student_ids = {membership.student_id for membership in memberships} | {assignment.student_id for assignment in assignments} | {attempt.student_id for attempt in attempts}
    assigned_pairs = {(assignment.assessment_id, assignment.student_id) for assignment in assignments}
    completed_pairs = {(attempt.assessment_id, attempt.student_id) for attempt in completed_attempts}
    weak_student_ids = {attempt.student_id for attempt in completed_attempts if attempt.percentage < 70}
    remediation_rows = list(db.scalars(select(RemediationPlan).where(RemediationPlan.source_attempt_id.in_([attempt.id for attempt in completed_attempts])))) if completed_attempts else []
    personalized_attempts = [attempt for attempt in completed_attempts if next((assessment for assessment in assessments if assessment.id == attempt.assessment_id and assessment.assessment_type == "personalized"), None)]
    improvement_values = _average_personalized_improvements(remediation_rows, personalized_attempts)
    upcoming_deadlines = sorted(
        [
            {
                "id": assessment.id,
                "title": assessment.title,
                "expires_at": assessment.expires_at.isoformat() if assessment.expires_at else None,
                "status": assessment.status,
            }
            for assessment in assessments
            if assessment.expires_at and assessment.expires_at >= datetime.utcnow() and assessment.status in {"published", "scheduled"}
        ],
        key=lambda item: item["expires_at"] or "",
    )[:5]

    return {
        "classroom_count": len(classrooms),
        "classroom_student_count": len(student_ids),
        "assessment_draft_count": sum(1 for assessment in assessments if assessment.status == "draft"),
        "assessment_published_count": sum(1 for assessment in assessments if assessment.status == "published"),
        "assessment_completed_count": sum(1 for assessment in assessments if assessment.status == "closed" or any(attempt.assessment_id == assessment.id for attempt in completed_attempts)),
        "assessment_participation_rate": round((len(completed_pairs) / len(assigned_pairs)) * 100, 2) if assigned_pairs else 0,
        "assessment_average_score": round(sum(attempt.percentage for attempt in completed_attempts) / len(completed_attempts), 2) if completed_attempts else 0,
        "students_in_difficulty": len(weak_student_ids),
        "active_remediations": sum(1 for plan in remediation_rows if plan.status == "active"),
        "average_remediation_improvement": round(sum(improvement_values) / len(improvement_values), 2) if improvement_values else 0,
        "upcoming_assessment_deadlines": upcoming_deadlines,
        "recent_assessments": [
            {
                "id": assessment.id,
                "title": assessment.title,
                "status": assessment.status,
                "assessment_type": assessment.assessment_type,
                "course_id": assessment.course_id,
                "updated_at": assessment.updated_at.isoformat() if assessment.updated_at else None,
            }
            for assessment in sorted(assessments, key=lambda item: item.updated_at or item.created_at, reverse=True)[:5]
        ],
    }


def _average_personalized_improvements(remediation_rows: list[RemediationPlan], personalized_attempts: list[AssessmentAttempt]) -> list[float]:
    values = []
    for plan in remediation_rows:
        matching_attempts = [
            attempt
            for attempt in personalized_attempts
            if attempt.student_id == plan.student_id and attempt.submitted_at and attempt.submitted_at >= plan.created_at
        ]
        if matching_attempts:
            latest = sorted(matching_attempts, key=lambda item: item.submitted_at, reverse=True)[0]
            values.append(latest.percentage - plan.initial_score)
    return values


def _chapter_completion(progress_rows: list[CourseProgress]) -> list[dict]:
    totals: dict[str, dict[str, int | str]] = {}
    for progress in progress_rows:
        chapters = progress.chapters if isinstance(progress.chapters, list) else []
        for index, chapter in enumerate(chapters, start=1):
            title = str(chapter.get("title") or f"Chapitre {index}")
            item = totals.setdefault(title, {"title": title, "completed": 0, "total": 0})
            item["total"] += 1
            if chapter.get("completed") or chapter.get("status") == "completed":
                item["completed"] += 1
    results = []
    for item in totals.values():
        total = int(item["total"])
        completed = int(item["completed"])
        results.append({"title": item["title"], "completion_rate": round((completed / total) * 100, 2) if total else 0})
    return sorted(results, key=lambda item: item["completion_rate"])


def _get_chapter_for_course(course: Course, chapter_id: int) -> CourseChapter:
    chapter = next((item for item in course.chapters if item.id == chapter_id), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable")
    return chapter


def _get_owned_quiz(db: Session, current_user: UserProfile, quiz_id: int) -> Quiz:
    quiz = db.scalars(select(Quiz).where(Quiz.id == quiz_id)).first()
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz introuvable")
    get_professor_owned_course(db, current_user, quiz.course_id)
    return quiz


def _get_question_for_quiz(quiz: Quiz, question_id: int) -> QuizQuestion:
    question = next((item for item in quiz.questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable")
    return question


def _validate_chapter_payload(payload: dict) -> None:
    if not str(payload.get("title", "")).strip():
        raise HTTPException(status_code=422, detail="Le titre du chapitre est obligatoire")
    if not str(payload.get("content", "")).strip():
        raise HTTPException(status_code=422, detail="Le contenu du chapitre est obligatoire")


def _validate_quiz_payload(payload: dict, require_questions: bool = True) -> None:
    passing_score = int(payload.get("passing_score", 70) or 70)
    if passing_score < 0 or passing_score > 100:
        raise HTTPException(status_code=422, detail="passing_score doit etre compris entre 0 et 100")
    questions = payload.get("questions") or []
    if require_questions and len(questions) < 10:
        raise HTTPException(status_code=422, detail="Un quiz complet doit contenir au moins 10 questions")


def _validate_question_payload(db: Session, quiz: Quiz, payload: dict) -> None:
    question = str(payload.get("question", "")).strip()
    choices = payload.get("choices") or []
    answer = payload.get("answer")
    if not question:
        raise HTTPException(status_code=422, detail="La question est obligatoire")
    if not isinstance(choices, list) or len(choices) < 2:
        raise HTTPException(status_code=422, detail="Une question doit avoir au moins deux choix")
    if answer not in choices:
        raise HTTPException(status_code=422, detail="La bonne reponse doit etre presente dans les choix")
    chapter_id = payload.get("chapter_id")
    if chapter_id is not None:
        chapter = db.get(CourseChapter, int(chapter_id))
        if chapter is None or chapter.course_id != quiz.course_id:
            raise HTTPException(status_code=422, detail="Le chapitre doit appartenir au meme cours")


def _serialize_chapter(chapter: CourseChapter) -> dict:
    return {
        "id": chapter.id,
        "course_id": chapter.course_id,
        "title": chapter.title,
        "duration": chapter.duration,
        "estimated_duration": chapter.estimated_duration or chapter.duration,
        "completed": chapter.completed,
        "status": chapter.status,
        "openable": chapter.openable,
        "content": chapter.content,
        "structured_content": chapter.structured_content or [],
        "position": chapter.position,
        "active": chapter.active,
    }


def _serialize_question(question: QuizQuestion, include_answer: bool = False) -> dict:
    data = {
        "id": question.id,
        "quiz_id": question.quiz_id,
        "chapter_id": question.chapter_id,
        "question": question.question,
        "choices": question.choices,
        "explanation": question.explanation,
        "difficulty_level_id": question.difficulty_level_id,
        "position": question.position,
        "active": question.active,
    }
    if include_answer:
        data["answer"] = question.answer
    return data


def _safe_pdf_name(file_name: str) -> str:
    name = Path(file_name).name
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(name).stem).strip("._") or "support"
    return f"{stem}.pdf"


def _is_safe_doc_path(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(DOCS_DIR.resolve())
    except FileNotFoundError:
        return path.parent.resolve().is_relative_to(DOCS_DIR.resolve())
