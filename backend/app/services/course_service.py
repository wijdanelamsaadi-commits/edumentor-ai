from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import (
    Classroom,
    ClassroomCourseAssignment,
    ClassroomMembership,
    Course,
    CourseChapter,
    CourseExample,
    CourseLevelVariant,
    CourseObjective,
    CourseSkill,
    DiagnosticResult,
    DifficultyLevel,
    EducationLevel,
    Quiz,
    QuizQuestion,
    Subject,
    StudyPath,
    StudyPathItem,
    UserProfile,
)
from app.schemas.lesson_content import validate_structured_blocks
from app.services.mock_data import COURSES as FALLBACK_COURSES, QUIZZES as FALLBACK_QUIZZES

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "courses"
MAX_PDF_SIZE = 20 * 1024 * 1024


def seed_courses_from_mock(db: Session) -> None:
    if db.scalar(select(Course.id).limit(1)) is not None:
        return

    for index, course_data in enumerate(FALLBACK_COURSES, start=1):
        course = build_course_model(course_data, display_order=index)
        quiz_data = FALLBACK_QUIZZES.get(course.id)
        if quiz_data:
            course.quiz = build_quiz_model(course.id, quiz_data)
        db.add(course)
    db.commit()
    attach_default_catalog_metadata(db)


def attach_default_catalog_metadata(db: Session) -> None:
    subject = db.scalars(select(Subject).where(Subject.slug == "intelligence-artificielle")).first()
    difficulty_by_slug = {
        item.slug: item
        for item in db.scalars(select(DifficultyLevel).where(DifficultyLevel.slug.in_(["debutant", "intermediaire", "avance"])))
    }
    if subject is None:
        return

    for course in db.scalars(select(Course)):
        if course.subject_id is None:
            course.subject_id = subject.id
        if course.difficulty_level_id is None:
            difficulty_slug = normalize_course_level_slug(course.level)
            if difficulty_slug in difficulty_by_slug:
                course.difficulty_level_id = difficulty_by_slug[difficulty_slug].id
        if not course.estimated_duration:
            course.estimated_duration = course.duration
    db.commit()


def normalize_course_level_slug(level: str | None) -> str:
    clean_level = str(level or "").lower()
    if "debut" in clean_level or "début" in clean_level:
        return "debutant"
    if "inter" in clean_level:
        return "intermediaire"
    if "avanc" in clean_level:
        return "avance"
    return ""


def get_courses(
    db: Session,
    include_unpublished: bool = False,
    subject_id: int | None = None,
    subject_slug: str | None = None,
    education_level_id: int | None = None,
    difficulty_level_id: int | None = None,
    professor_id: int | None = None,
    published: bool | None = None,
    search: str = "",
    current_user: UserProfile | None = None,
    filter_for_user: bool = False,
) -> list[dict]:
    query = select(Course).options(*course_load_options()).order_by(Course.display_order, Course.id)
    if subject_id:
        query = query.where(Course.subject_id == subject_id)
    if subject_slug:
        query = query.join(Course.subject).where(Subject.slug == subject_slug)
    if education_level_id:
        query = query.where(Course.education_level_id == education_level_id)
    if difficulty_level_id:
        query = query.where(Course.difficulty_level_id == difficulty_level_id)
    if professor_id:
        query = query.where(Course.professor_id == professor_id)
    if published is not None:
        query = query.where(Course.published.is_(published))
    elif not include_unpublished:
        query = query.where(Course.published.is_(True))
    if search.strip():
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Course.title.ilike(pattern),
                Course.summary.ilike(pattern),
                Course.description.ilike(pattern),
                Course.level.ilike(pattern),
            )
        )

    has_courses = db.scalar(select(Course.id).limit(1)) is not None
    courses = list(db.scalars(query))
    if filter_for_user:
        courses = [course for course in courses if can_access_course(db, course, current_user)]
    if not has_courses:
        return FALLBACK_COURSES
    return [serialize_course(course, detail=True, db=db, current_user=current_user) for course in courses]


def get_course_detail(
    db: Session,
    course_id: int,
    include_unpublished: bool = False,
    current_user: UserProfile | None = None,
    filter_for_user: bool = False,
) -> dict:
    course = get_course_model(db, course_id)
    if course is None:
        has_courses = db.scalar(select(Course.id).limit(1)) is not None
        fallback = next((item for item in FALLBACK_COURSES if item["id"] == course_id), None)
        if not has_courses and fallback:
            return fallback
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if not include_unpublished and not course.published:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if filter_for_user and not can_access_course(db, course, current_user):
        raise HTTPException(status_code=404, detail="Cours introuvable")
    return serialize_course(course, detail=True, db=db, current_user=current_user)


def get_quiz(db: Session, course_id: int) -> dict:
    course = get_course_model(db, course_id)
    if course and course.quiz and course.quiz.published:
        return {
            "course_id": course.id,
            "course_title": course.title,
            "questions": [
                {"question": item.question, "choices": item.choices}
                for item in course.quiz.questions
            ],
        }

    has_courses = db.scalar(select(Course.id).limit(1)) is not None
    quiz = FALLBACK_QUIZZES.get(course_id) if not has_courses else None
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz introuvable")
    course_title = next((item["title"] for item in FALLBACK_COURSES if item["id"] == course_id), f"Cours {course_id}")
    return {
        "course_id": course_id,
        "course_title": course_title,
        "questions": [{"question": item["question"], "choices": item["choices"]} for item in quiz["questions"]],
    }


def grade_quiz(db: Session, course_id: int, answers: list[str]) -> dict:
    questions = get_quiz_questions_for_grading(db, course_id)
    if not questions:
        raise HTTPException(status_code=404, detail="Quiz introuvable")

    corrections = []
    correct = 0
    for index, question in enumerate(questions):
        user_answer = answers[index] if index < len(answers) else ""
        is_correct = user_answer == question["answer"]
        if is_correct:
            correct += 1
        corrections.append({
            "question": question["question"],
            "user_answer": user_answer,
            "correct_answer": question["answer"],
            "is_correct": is_correct,
            "explanation": question.get("explanation", ""),
        })

    score = round((correct / len(questions)) * 100)
    return {
        "score": score,
        "correct_answers": correct,
        "total_questions": len(questions),
        "corrections": corrections,
        "recommendation": "Continuer le module suivant" if score >= 70 else "Revoir le resume et refaire les exercices",
    }


def create_course(db: Session, payload: dict) -> dict:
    if not payload.get("subject_id"):
        raise HTTPException(status_code=400, detail="La matiere du cours est obligatoire")
    next_id = payload.get("id") or ((db.scalar(select(Course.id).order_by(Course.id.desc()).limit(1)) or 0) + 1)
    if db.get(Course, next_id):
        raise HTTPException(status_code=409, detail="Un cours avec cet id existe deja")
    course = build_course_model({**payload, "id": next_id}, payload.get("display_order", next_id))
    quiz_payload = payload.get("quiz")
    if quiz_payload:
        course.quiz = build_quiz_model(next_id, quiz_payload)
    db.add(course)
    db.commit()
    db.refresh(course)
    return get_course_detail(db, course.id, include_unpublished=True)


def update_course(db: Session, course_id: int, payload: dict) -> dict:
    course = get_course_model(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")

    scalar_fields = [
        "title", "level", "duration", "progress", "tag", "summary", "description",
        "exercises", "information", "pdf_url", "display_order", "published", "status",
        "subject_id", "education_level_id", "difficulty_level_id", "professor_id",
        "estimated_duration", "prerequisites",
    ]
    for field in scalar_fields:
        if field in payload:
            setattr(course, field, payload[field])

    if "objectives" in payload:
        replace_objectives(course, payload["objectives"])
    if "chapters" in payload:
        replace_chapters(course, payload["chapters"])
    if "examples" in payload:
        replace_examples(course, payload["examples"])
    if "skills" in payload:
        replace_skills(course, payload["skills"])
    if "quiz" in payload:
        replace_quiz(course, payload["quiz"])

    db.commit()
    db.refresh(course)
    return get_course_detail(db, course.id, include_unpublished=True)


def delete_course(db: Session, course_id: int) -> dict:
    course = get_course_model(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    db.delete(course)
    db.commit()
    return {"deleted": True, "course_id": course_id}


def save_course_pdf(db: Session, course_id: int, file: UploadFile, replace: bool) -> dict:
    course = get_course_model(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptes")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_pdf_name(file.filename)
    target = DOCS_DIR / safe_name
    if target.exists() and not replace:
        raise HTTPException(status_code=409, detail="Un PDF avec ce nom existe deja")

    size = 0
    temp = target.with_suffix(".uploading")
    with temp.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_PDF_SIZE:
                temp.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="PDF trop volumineux")
            output.write(chunk)
    if course.pdf_url:
        from app.services.rag_document_service import mark_course_document_outdated

        mark_course_document_outdated(db, course)
    shutil.move(str(temp), str(target))
    course.pdf_url = f"/docs/courses/{safe_name}"
    db.commit()
    return {"pdf_url": course.pdf_url, "file_name": safe_name, "size": size}


def delete_course_pdf(db: Session, course_id: int) -> dict:
    course = get_course_model(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if course.pdf_url:
        from app.services.rag_document_service import mark_course_document_outdated

        mark_course_document_outdated(db, course)
        file_name = Path(course.pdf_url).name
        target = DOCS_DIR / file_name
        if target.exists() and target.resolve().is_relative_to(DOCS_DIR.resolve()):
            target.unlink()
    course.pdf_url = None
    db.commit()
    return {"deleted": True, "course_id": course_id}


def get_course_model(db: Session, course_id: int) -> Course | None:
    return db.scalars(
        select(Course)
        .where(Course.id == course_id)
        .options(*course_load_options(include_quiz=True))
    ).first()


def can_access_course(db: Session, course: Course, user: UserProfile | None) -> bool:
    if not course.published or course.status not in {"published", "active"}:
        return False

    if (
        user is not None
        and user.role == "student"
        and has_active_study_path_course_access(db, user.id, course.id)
    ):
        return True

    assignments = active_classroom_course_assignments(db, course.id)
    if not assignments:
        return True

    if user is None:
        return False
    if user.role == "admin":
        return True
    if user.role == "professor":
        return any(assignment.classroom and assignment.classroom.professor_id == user.id for assignment in assignments)
    if user.role == "student":
        classroom_ids = [assignment.classroom_id for assignment in assignments]
        return db.scalar(
            select(ClassroomMembership.id)
            .join(Classroom, Classroom.id == ClassroomMembership.classroom_id)
            .where(
                ClassroomMembership.student_id == user.id,
                ClassroomMembership.classroom_id.in_(classroom_ids),
                ClassroomMembership.active.is_(True),
                Classroom.active.is_(True),
            )
            .limit(1)
        ) is not None
    return False


def has_active_study_path_course_access(
    db: Session,
    student_id: int,
    course_id: int,
) -> bool:
    direct_path = db.scalar(
        select(StudyPath.id)
        .where(
            StudyPath.student_id == student_id,
            StudyPath.course_id == course_id,
            StudyPath.active.is_(True),
            StudyPath.status.in_(["active", "completed"]),
        )
        .limit(1)
    )
    if direct_path is not None:
        return True

    recommended_item = db.scalar(
        select(StudyPathItem.id)
        .join(StudyPath, StudyPath.id == StudyPathItem.study_path_id)
        .where(
            StudyPath.student_id == student_id,
            StudyPath.active.is_(True),
            StudyPath.status.in_(["active", "completed"]),
            StudyPathItem.item_type == "start_recommended_course",
            StudyPathItem.entity_id == course_id,
            StudyPathItem.status.in_(["available", "in_progress", "completed"]),
        )
        .limit(1)
    )
    return recommended_item is not None


def study_path_openable_chapter_ids(
    db: Session,
    student_id: int,
    course_id: int,
) -> set[int]:
    rows = db.scalars(
        select(StudyPathItem)
        .join(StudyPath, StudyPath.id == StudyPathItem.study_path_id)
        .where(
            StudyPath.student_id == student_id,
            StudyPath.course_id == course_id,
            StudyPath.active.is_(True),
            StudyPath.status.in_(["active", "completed"]),
            StudyPathItem.item_type.in_(["review_chapter", "exercise"]),
            StudyPathItem.status.in_(["available", "in_progress", "completed"]),
        )
    ).all()

    return {
        int(item.entity_id)
        for item in rows
        if item.entity_id is not None
    }


def active_classroom_course_assignments(db: Session, course_id: int) -> list[ClassroomCourseAssignment]:
    return list(
        db.scalars(
            select(ClassroomCourseAssignment)
            .join(Classroom, Classroom.id == ClassroomCourseAssignment.classroom_id)
            .where(
                ClassroomCourseAssignment.course_id == course_id,
                ClassroomCourseAssignment.active.is_(True),
                Classroom.active.is_(True),
            )
            .options(selectinload(ClassroomCourseAssignment.classroom))
        )
    )


def course_load_options(include_quiz: bool = False):
    options = [
        selectinload(Course.chapters),
        selectinload(Course.objectives),
        selectinload(Course.examples),
        selectinload(Course.skills),
        selectinload(Course.subject),
        selectinload(Course.education_level),
        selectinload(Course.difficulty_level),
        selectinload(Course.professor),
    ]
    if include_quiz:
        options.append(selectinload(Course.quiz).selectinload(Quiz.questions))
    return options


def build_course_model(data: dict, display_order: int) -> Course:
    course = Course(
        id=data["id"],
        title=data.get("title", "Nouveau cours"),
        level=data.get("level", "Debutant"),
        duration=data.get("duration", "2h"),
        progress=int(data.get("progress", 0) or 0),
        tag=data.get("tag"),
        summary=data.get("summary", ""),
        description=data.get("description", ""),
        exercises=data.get("exercises", []),
        information=data.get("information") or {},
        pdf_url=data.get("pdf_url"),
        display_order=int(data.get("display_order", display_order) or display_order),
        published=data.get("published", True) is not False,
        status=data.get("status") or ("published" if data.get("published", True) is not False else "draft"),
        subject_id=data.get("subject_id"),
        education_level_id=data.get("education_level_id"),
        difficulty_level_id=data.get("difficulty_level_id"),
        professor_id=data.get("professor_id"),
        estimated_duration=data.get("estimated_duration") or data.get("duration"),
        prerequisites=data.get("prerequisites"),
    )
    replace_objectives(course, data.get("objectives", []))
    replace_chapters(course, data.get("chapters", []))
    replace_examples(course, data.get("examples", []))
    replace_skills(course, data.get("skills", []))
    return course


def build_quiz_model(course_id: int, data: dict) -> Quiz:
    quiz = Quiz(
        course_id=course_id,
        title=data.get("title", "Quiz du cours"),
        description=data.get("description", ""),
        passing_score=int(data.get("passing_score", 70) or 70),
        active=data.get("active", data.get("published", True)) is not False,
        published=data.get("published", data.get("active", True)) is not False,
    )
    questions = data.get("questions", [])
    if len(questions) < 10:
        raise HTTPException(status_code=400, detail="Un quiz doit contenir au moins 10 questions")
    quiz.questions = [
        QuizQuestion(
            question=item["question"],
            choices=item.get("choices", []),
            answer=item["answer"],
            explanation=item.get("explanation", ""),
            chapter_id=item.get("chapter_id"),
            difficulty_level_id=item.get("difficulty_level_id"),
            active=item.get("active", True) is not False,
            position=index,
        )
        for index, item in enumerate(questions, start=1)
    ]
    return quiz


def replace_quiz(course: Course, data: dict) -> None:
    if course.quiz is None:
        course.quiz = build_quiz_model(course.id, data)
        return

    questions = data.get("questions", [])
    if len(questions) < 10:
        raise HTTPException(status_code=400, detail="Un quiz doit contenir au moins 10 questions")
    course.quiz.title = data.get("title", course.quiz.title)
    course.quiz.description = data.get("description", course.quiz.description)
    course.quiz.passing_score = int(data.get("passing_score", course.quiz.passing_score or 70) or 70)
    course.quiz.active = data.get("active", data.get("published", course.quiz.active)) is not False
    course.quiz.published = data.get("published", data.get("active", course.quiz.published)) is not False
    course.quiz.questions = [
        QuizQuestion(
            question=item["question"],
            choices=item.get("choices", []),
            answer=item["answer"],
            explanation=item.get("explanation", ""),
            chapter_id=item.get("chapter_id"),
            difficulty_level_id=item.get("difficulty_level_id"),
            active=item.get("active", True) is not False,
            position=index,
        )
        for index, item in enumerate(questions, start=1)
    ]


def replace_objectives(course: Course, items: list[Any]) -> None:
    course.objectives = [CourseObjective(text=str(item.get("text", item) if isinstance(item, dict) else item), position=index) for index, item in enumerate(items, start=1)]


def replace_chapters(course: Course, items: list[dict]) -> None:
    course.chapters = [
        CourseChapter(
            title=item.get("title", f"Chapitre {index}"),
            duration=item.get("duration", "20 min"),
            completed=item.get("completed", False) is True,
            status=item.get("status", "locked"),
            openable=item.get("openable", item.get("status") in {"completed", "active"}) is True,
            content=item.get("content"),
            structured_content=validate_structured_blocks(item.get("structured_content")),
            estimated_duration=item.get("estimated_duration") or item.get("duration"),
            active=item.get("active", True) is not False,
            position=index,
        )
        for index, item in enumerate(items, start=1)
    ]


def replace_examples(course: Course, items: list[dict]) -> None:
    course.examples = [
        CourseExample(title=item.get("title", f"Exemple {index}"), description=item.get("description", ""), position=index)
        for index, item in enumerate(items, start=1)
    ]


def replace_skills(course: Course, items: list[Any]) -> None:
    course.skills = [CourseSkill(text=str(item.get("text", item) if isinstance(item, dict) else item), position=index) for index, item in enumerate(items, start=1)]


def serialize_course(course: Course, detail: bool = False, db: Session | None = None, current_user: UserProfile | None = None) -> dict:
    data = {
        "id": course.id,
        "title": course.title,
        "level": course.level,
        "duration": course.duration,
        "progress": course.progress,
        "tag": course.tag,
        "summary": course.summary,
        "description": course.description,
        "objectives": [item.text for item in course.objectives],
        "chapters": [
            {
                "id": item.id,
                "title": item.title,
                "duration": item.duration,
                "completed": item.completed,
                "status": item.status,
                "openable": item.openable,
                "content": item.content,
                "structured_content": item.structured_content or [],
                "position": item.position,
                "estimated_duration": item.estimated_duration or item.duration,
                "active": item.active,
            }
            for item in course.chapters
        ],
        "examples": [{"title": item.title, "description": item.description} for item in course.examples],
        "exercises": course.exercises or [],
        "skills": [item.text for item in course.skills],
        "information": course.information or {},
        "pdf_url": course.pdf_url,
        "display_order": course.display_order,
        "published": course.published,
        "status": course.status or ("published" if course.published else "draft"),
        "subject_id": course.subject_id,
        "education_level_id": course.education_level_id,
        "difficulty_level_id": course.difficulty_level_id,
        "professor_id": course.professor_id,
        "subject": serialize_subject_ref(course.subject),
        "education_level": serialize_education_level_ref(course.education_level),
        "difficulty_level": serialize_difficulty_level_ref(course.difficulty_level),
        "professor": serialize_professor_ref(course.professor),
        "estimated_duration": course.estimated_duration or course.duration,
        "prerequisites": course.prerequisites,
        "content_import_status": course.content_import_status,
        "content_import_error": course.content_import_error,
        "content_imported_at": course.content_imported_at.isoformat() if course.content_imported_at else None,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }
    if (
        db is not None
        and current_user is not None
        and current_user.role == "student"
    ):
        openable_chapter_ids = study_path_openable_chapter_ids(
            db,
            current_user.id,
            course.id,
        )
        for chapter in data["chapters"]:
            if int(chapter["id"]) in openable_chapter_ids:
                chapter["openable"] = True
                if chapter["status"] == "locked":
                    chapter["status"] = "active"

    data["information"] = {
        "level": data["information"].get("level", course.level),
        "duration": data["information"].get("duration", course.duration),
        "language": data["information"].get("language", "Francais"),
        "last_update": data["information"].get("last_update", "2026"),
        "chapter_count": data["information"].get("chapter_count", len(data["chapters"])),
    }
    if course.quiz:
        data["quiz"] = serialize_quiz(course.quiz, include_answers=True)
    if detail:
        data["original_chapters"] = list(data["chapters"])
        if db is not None:
            learner_level = resolve_learner_level(db, current_user, course)
            data["learner_level"] = learner_level
            data["selected_variant"] = serialize_selected_course_variant(db, course, learner_level)
    return data


def resolve_learner_level(db: Session, user: UserProfile | None, course: Course | None = None) -> str:
    if user is not None:
        diagnostic = db.scalars(
            select(DiagnosticResult)
            .where(DiagnosticResult.user_id == user.id)
            .order_by(DiagnosticResult.created_at.desc(), DiagnosticResult.id.desc())
            .limit(1)
        ).first()
        diagnostic_level = normalize_learner_level(diagnostic.level if diagnostic else None)
        if diagnostic_level:
            return diagnostic_level

        profile_level = normalize_learner_level(user.level)
        if profile_level:
            return profile_level

    course_level = normalize_learner_level(course.level if course else None)
    if course_level:
        return course_level
    return "intermediaire"


def normalize_learner_level(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    normalized = normalized.replace("ã©", "e").replace("ã¨", "e").replace("ã", "a")
    if "beginner" in normalized or "debut" in normalized:
        return "debutant"
    if "advanced" in normalized or "avance" in normalized or "avanc" in normalized:
        return "avance"
    if "intermediate" in normalized or "inter" in normalized:
        return "intermediaire"
    if "adapt" in normalized:
        return ""
    return ""


def serialize_selected_course_variant(db: Session, course: Course, learner_level: str) -> dict | None:
    variants = list(db.scalars(
        select(CourseLevelVariant)
        .where(CourseLevelVariant.course_id == course.id, CourseLevelVariant.level == learner_level)
        .order_by(CourseLevelVariant.generated_at.desc(), CourseLevelVariant.id.desc())
    ))
    if not variants:
        return None
    content = select_best_variant_chapters(course, variants)
    return {
        "level": learner_level,
        "generation_method": generation_method_for_selected_chapters(content),
        "chapters": content,
    }


def select_best_variant_chapters(course: Course, variants: list[CourseLevelVariant]) -> list[dict]:
    ai_by_source: dict[str, dict] = {}
    fallback_by_source: dict[str, dict] = {}

    for variant in variants:
        raw_content = variant.structured_content if isinstance(variant.structured_content, list) else []
        normalized_content = normalize_variant_chapter_sources(course, raw_content)
        for item in normalized_content:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("chapter_source_id") or item.get("source_chapter_id") or "")
            if not source_id:
                continue
            if is_ai_generated_variant_chapter(item):
                ai_by_source.setdefault(source_id, item)
            else:
                fallback_by_source.setdefault(source_id, item)

    selected: list[dict] = []
    for chapter in sorted(course.chapters, key=lambda item: (item.position or 0, item.id or 0)):
        source_id = stable_chapter_source_id(chapter)
        item = ai_by_source.get(source_id) or fallback_by_source.get(source_id)
        if item is not None:
            selected.append(item)
    return selected


def is_ai_generated_variant_chapter(item: dict) -> bool:
    if item.get("generation_method") == "ai_generated":
        return True
    blocks = item.get("blocks")
    return isinstance(blocks, list) and any(
        isinstance(block, dict) and block.get("generation_method") == "ai_generated"
        for block in blocks
    )


def generation_method_for_selected_chapters(content: list[dict]) -> str:
    if not content:
        return "deterministic_fallback"
    ai_count = sum(1 for item in content if isinstance(item, dict) and is_ai_generated_variant_chapter(item))
    if ai_count == len(content):
        return "ai_generated"
    if ai_count:
        return "mixed"
    return "deterministic_fallback"


def normalize_variant_chapter_sources(course: Course, variant_chapters: list[Any]) -> list[Any]:
    if not isinstance(variant_chapters, list):
        return []
    chapter_by_database_id = {str(chapter.id): chapter for chapter in course.chapters}
    source_by_database_id = {str(chapter.id): stable_chapter_source_id(chapter) for chapter in course.chapters}
    source_by_position = {index: stable_chapter_source_id(chapter) for index, chapter in enumerate(course.chapters)}

    normalized_chapters = []
    for index, item in enumerate(variant_chapters):
        if not isinstance(item, dict):
            normalized_chapters.append(item)
            continue
        chapter_payload = dict(item)
        original_source = str(
            chapter_payload.get("chapter_source_id")
            or chapter_payload.get("source_chapter_id")
            or ""
        )
        stable_source = source_by_database_id.get(original_source)
        if stable_source is None and original_source.startswith("chapter_"):
            stable_source = original_source
        if stable_source is None and index in source_by_position:
            stable_source = source_by_position[index]
        if stable_source:
            chapter_payload["chapter_source_id"] = stable_source
            chapter_payload["source_chapter_id"] = stable_source
        matched_chapter = chapter_by_database_id.get(original_source) if original_source else None
        if matched_chapter is None and index < len(course.chapters):
            matched_chapter = course.chapters[index]
        if matched_chapter is not None:
            chapter_payload["course_chapter_id"] = matched_chapter.id
            chapter_payload.setdefault("position", matched_chapter.position)
        blocks = chapter_payload.get("blocks")
        if isinstance(blocks, list) and stable_source:
            chapter_payload["blocks"] = [
                normalize_variant_block_source(block, stable_source)
                for block in blocks
            ]
        normalized_chapters.append(chapter_payload)
    return normalized_chapters


def normalize_variant_block_source(block: Any, stable_source: str) -> Any:
    if not isinstance(block, dict):
        return block
    payload = dict(block)
    payload["source_chapter_id"] = stable_source
    return payload


def stable_chapter_source_id(chapter: CourseChapter) -> str:
    structured_content = chapter.structured_content or []
    if isinstance(structured_content, dict):
        candidates = structured_content.get("blocks") or structured_content.get("source_blocks") or []
    elif isinstance(structured_content, list):
        candidates = structured_content
    else:
        candidates = []
    for block in candidates:
        if not isinstance(block, dict):
            continue
        for key in ("source_chapter_id", "chapter_source_id"):
            value = block.get(key)
            if isinstance(value, str) and value.startswith("chapter_"):
                return value
        metadata = block.get("metadata") or {}
        if isinstance(metadata, dict):
            for key in ("source_chapter_id", "chapter_source_id"):
                value = metadata.get(key)
                if isinstance(value, str) and value.startswith("chapter_"):
                    return value
    return f"chapter_{chapter.position or chapter.id}"


def serialize_subject_ref(subject: Subject | None) -> dict | None:
    if subject is None:
        return None
    return {"id": subject.id, "name": subject.name, "slug": subject.slug, "description": subject.description, "icon": subject.icon}


def serialize_education_level_ref(level: EducationLevel | None) -> dict | None:
    if level is None:
        return None
    return {"id": level.id, "name": level.name, "slug": level.slug, "description": level.description}


def serialize_difficulty_level_ref(level: DifficultyLevel | None) -> dict | None:
    if level is None:
        return None
    return {"id": level.id, "name": level.name, "slug": level.slug}


def serialize_professor_ref(professor: UserProfile | None) -> dict | None:
    if professor is None:
        return None
    return {"id": professor.id, "full_name": professor.full_name, "email": professor.email}


def serialize_quiz(quiz: Quiz, include_answers: bool = False) -> dict:
    questions = []
    for item in quiz.questions:
        question = {
            "id": item.id,
            "question": item.question,
            "choices": item.choices,
            "explanation": item.explanation,
            "chapter_id": item.chapter_id,
            "difficulty_level_id": item.difficulty_level_id,
            "position": item.position,
            "active": item.active,
        }
        if include_answers:
            question["answer"] = item.answer
        questions.append(question)
    return {
        "id": quiz.id,
        "course_id": quiz.course_id,
        "title": quiz.title,
        "description": quiz.description,
        "passing_score": quiz.passing_score,
        "active": quiz.active,
        "published": quiz.published,
        "questions": questions,
    }


def get_quiz_questions_for_grading(db: Session, course_id: int) -> list[dict]:
    course = get_course_model(db, course_id)
    if course and course.quiz and course.quiz.published:
        return [
            {"question": item.question, "choices": item.choices, "answer": item.answer, "explanation": item.explanation}
            for item in course.quiz.questions
        ]
    has_courses = db.scalar(select(Course.id).limit(1)) is not None
    return [] if has_courses else FALLBACK_QUIZZES.get(course_id, {}).get("questions", [])


def sanitize_pdf_name(file_name: str) -> str:
    name = Path(file_name).name
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(name).stem).strip("._")
    if not stem:
        stem = "support"
    return f"{stem}.pdf"
