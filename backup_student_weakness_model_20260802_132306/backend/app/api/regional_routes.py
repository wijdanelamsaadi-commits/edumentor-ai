from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_student
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.services import chapter_exercise_service, regional_exam_service

router = APIRouter(tags=["Regional exam"])


@router.get("/regional-exam-preparation")
def get_regional_exam_preparation(
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return regional_exam_service.get_student_preparation(db, current_student)


@router.get("/regional-exams")
def list_regional_exams(
    year: str | None = None,
    region: str | None = None,
    work_id: str | None = None,
    session: str | None = None,
    status: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return regional_exam_service.list_regional_exams(
        db,
        current_student,
        {
            "year": year,
            "region": region,
            "work_id": work_id,
            "session": session,
            "status": status,
            "search": search,
        },
    )


@router.get("/regional-exams/{exam_id}")
def get_regional_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return regional_exam_service.get_regional_exam(db, current_student, exam_id)


@router.post("/regional-exams/{exam_id}/start")
def start_regional_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return regional_exam_service.start_regional_exam(db, current_student, exam_id)


@router.post("/regional-exams/{exam_id}/submit")
def submit_regional_exam(
    exam_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return regional_exam_service.submit_regional_exam(db, current_student, exam_id, payload)


@router.get("/regional-exams/{exam_id}/attempts")
def list_regional_attempts(
    exam_id: int,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return regional_exam_service.list_regional_attempts(db, current_student, exam_id)


@router.get("/regional-exam-attempts/{attempt_id}")
def get_regional_attempt(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return regional_exam_service.get_regional_attempt(db, current_student, attempt_id)


@router.get("/debug/exercise-evaluator")
def debug_exercise_evaluator() -> dict:
    return chapter_exercise_service.get_evaluator_debug()


@router.get("/courses/{course_id}/chapters/{chapter_id}/exercises")
def chapter_exercises(
    course_id: int,
    chapter_id: int,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return chapter_exercise_service.list_chapter_exercises(db, current_student, course_id, chapter_id)


@router.post("/courses/{course_id}/chapters/{chapter_id}/exercises/{question_id}/submit")
def submit_chapter_exercise(
    course_id: int,
    chapter_id: int,
    question_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return chapter_exercise_service.submit_chapter_exercise(db, current_student, course_id, chapter_id, question_id, payload)


@router.get("/courses/{course_id}/chapters/{chapter_id}/exercise-progress")
def chapter_exercise_progress(
    course_id: int,
    chapter_id: int,
    db: Session = Depends(get_db),
    current_student: UserProfile = Depends(get_current_student),
) -> dict:
    return chapter_exercise_service.get_chapter_exercise_progress(db, current_student, course_id, chapter_id)
