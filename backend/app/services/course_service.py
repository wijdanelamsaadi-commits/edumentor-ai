from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import Course, CourseChapter, CourseExample, CourseObjective, CourseSkill, Quiz, QuizQuestion
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


def get_courses(db: Session, include_unpublished: bool = False) -> list[dict]:
    courses = list(
        db.scalars(
            select(Course)
            .options(
                selectinload(Course.chapters),
                selectinload(Course.objectives),
                selectinload(Course.examples),
                selectinload(Course.skills),
            )
            .order_by(Course.display_order, Course.id)
        )
    )
    if not courses:
        return FALLBACK_COURSES
    if not include_unpublished:
        courses = [course for course in courses if course.published]
    return [serialize_course(course, detail=True) for course in courses]


def get_course_detail(db: Session, course_id: int, include_unpublished: bool = False) -> dict:
    course = get_course_model(db, course_id)
    if course is None:
        fallback = next((item for item in FALLBACK_COURSES if item["id"] == course_id), None)
        if fallback:
            return fallback
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if not include_unpublished and not course.published:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    return serialize_course(course, detail=True)


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

    quiz = FALLBACK_QUIZZES.get(course_id)
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
        "exercises", "information", "pdf_url", "display_order", "published",
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
    shutil.move(str(temp), str(target))
    course.pdf_url = f"/docs/courses/{safe_name}"
    db.commit()
    return {"pdf_url": course.pdf_url, "file_name": safe_name, "size": size}


def delete_course_pdf(db: Session, course_id: int) -> dict:
    course = get_course_model(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")
    if course.pdf_url:
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
        .options(
            selectinload(Course.chapters),
            selectinload(Course.objectives),
            selectinload(Course.examples),
            selectinload(Course.skills),
            selectinload(Course.quiz).selectinload(Quiz.questions),
        )
    ).first()


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
    )
    replace_objectives(course, data.get("objectives", []))
    replace_chapters(course, data.get("chapters", []))
    replace_examples(course, data.get("examples", []))
    replace_skills(course, data.get("skills", []))
    return course


def build_quiz_model(course_id: int, data: dict) -> Quiz:
    quiz = Quiz(course_id=course_id, title=data.get("title", "Quiz du cours"), published=data.get("published", True) is not False)
    questions = data.get("questions", [])
    if len(questions) < 10:
        raise HTTPException(status_code=400, detail="Un quiz doit contenir au moins 10 questions")
    quiz.questions = [
        QuizQuestion(
            question=item["question"],
            choices=item.get("choices", []),
            answer=item["answer"],
            explanation=item.get("explanation", ""),
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
    course.quiz.published = data.get("published", True) is not False
    course.quiz.questions = [
        QuizQuestion(
            question=item["question"],
            choices=item.get("choices", []),
            answer=item["answer"],
            explanation=item.get("explanation", ""),
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


def serialize_course(course: Course, detail: bool = False) -> dict:
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
                "title": item.title,
                "duration": item.duration,
                "completed": item.completed,
                "status": item.status,
                "openable": item.openable,
                "content": item.content,
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
    }
    data["information"] = {
        "level": data["information"].get("level", course.level),
        "duration": data["information"].get("duration", course.duration),
        "language": data["information"].get("language", "Francais"),
        "last_update": data["information"].get("last_update", "2026"),
        "chapter_count": data["information"].get("chapter_count", len(data["chapters"])),
    }
    if course.quiz:
        data["quiz"] = serialize_quiz(course.quiz, include_answers=True)
    return data


def serialize_quiz(quiz: Quiz, include_answers: bool = False) -> dict:
    questions = []
    for item in quiz.questions:
        question = {"question": item.question, "choices": item.choices, "explanation": item.explanation}
        if include_answers:
            question["answer"] = item.answer
        questions.append(question)
    return {"course_id": quiz.course_id, "title": quiz.title, "published": quiz.published, "questions": questions}


def get_quiz_questions_for_grading(db: Session, course_id: int) -> list[dict]:
    course = get_course_model(db, course_id)
    if course and course.quiz and course.quiz.published:
        return [
            {"question": item.question, "choices": item.choices, "answer": item.answer, "explanation": item.explanation}
            for item in course.quiz.questions
        ]
    return FALLBACK_QUIZZES.get(course_id, {}).get("questions", [])


def sanitize_pdf_name(file_name: str) -> str:
    name = Path(file_name).name
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(name).stem).strip("._")
    if not stem:
        stem = "support"
    return f"{stem}.pdf"
