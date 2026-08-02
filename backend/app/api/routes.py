from pathlib import Path
import json
import random

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_user, get_optional_current_user
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.schemas.requests import ChatRequest, DiagnosticSubmission, QuizSubmission
from app.rag.document_store import get_chunks_summary, get_documents_summary, get_search_summary
from app.rag.vector_store import get_vector_store_status
from app.services import catalog_service, diagnostic_service, learning_service
from app.services import course_service
from app.services import rag_document_service

router = APIRouter(tags=["EduMentor"])

QUESTIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "edumentor_questions.json"


def load_questions() -> dict:
    if not QUESTIONS_PATH.exists():
        raise HTTPException(status_code=500, detail="Questions file not found")
    with open(QUESTIONS_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


@router.post("/auth/login")
def login() -> dict:
    return learning_service.login_demo_user()


@router.get("/dashboard")
def dashboard() -> dict:
    return learning_service.get_dashboard()


@router.get("/subjects")
def subjects(db: Session = Depends(get_db)) -> list[dict]:
    return catalog_service.list_subjects(db, active_only=True)


@router.get("/education-levels")
def education_levels(db: Session = Depends(get_db)) -> list[dict]:
    return catalog_service.list_education_levels(db, active_only=True)


@router.get("/difficulty-levels")
def difficulty_levels(db: Session = Depends(get_db)) -> list[dict]:
    return catalog_service.list_difficulty_levels(db, active_only=True)


@router.get("/courses")
def courses(
    subject_id: int | None = None,
    subject_slug: str | None = None,
    education_level_id: int | None = None,
    difficulty_level_id: int | None = None,
    professor_id: int | None = None,
    published: bool | None = None,
    search: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: UserProfile | None = Depends(get_optional_current_user),
) -> list[dict]:
    return course_service.get_courses(
        db,
        subject_id=subject_id,
        subject_slug=subject_slug,
        education_level_id=education_level_id,
        difficulty_level_id=difficulty_level_id,
        professor_id=professor_id,
        published=True if published is not False else True,
        search=search,
        current_user=current_user,
        filter_for_user=True,
    )


@router.get("/courses/{course_id}")
def course_detail(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile | None = Depends(get_optional_current_user),
) -> dict:
    return course_service.get_course_detail(db, course_id, current_user=current_user, filter_for_user=True)


@router.post("/diagnostic")
def submit_diagnostic(payload: DiagnosticSubmission) -> dict:
    return learning_service.evaluate_diagnostic(payload.answers)


@router.get("/diagnostic/questions")
def get_diagnostic_questions(
    subject_id: int,
    education_level_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: UserProfile | None = Depends(get_optional_current_user),
) -> dict:
    return diagnostic_service.get_question_set(db, subject_id, education_level_id, limit, current_user)


@router.get("/diagnostic/availability")
def get_diagnostic_availability(
    subject_id: int,
    education_level_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: UserProfile | None = Depends(get_optional_current_user),
) -> dict:
    return diagnostic_service.get_question_availability(db, subject_id, education_level_id, limit, current_user)


@router.post("/diagnostic/submit")
def submit_diagnostic_test(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
) -> dict:
    return diagnostic_service.submit_positioning_test(db, current_user, payload)


@router.get("/quiz/{course_id}")
def get_quiz(course_id: int, db: Session = Depends(get_db)) -> dict:
    return course_service.get_quiz(db, course_id)


@router.post("/quiz/{course_id}/submit")
def submit_quiz(course_id: int, payload: QuizSubmission, db: Session = Depends(get_db)) -> dict:
    return course_service.grade_quiz(db, course_id, payload.answers)


@router.post("/chat")
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
) -> dict:
    return learning_service.rag_chat(
        payload.message,
        payload.level,
        payload.context,
        db=db,
        course_id=payload.course_id,
        subject_id=payload.subject_id,
        preferred_language=payload.preferred_language,
        current_user=current_user,
    )


@router.get("/rag/status")
def rag_status(db: Session = Depends(get_db)) -> dict:
    return rag_document_service.get_public_status(db)


@router.get("/rag/courses/{course_id}/status")
def rag_course_status(course_id: int, db: Session = Depends(get_db)) -> dict:
    return rag_document_service.get_course_rag_status(db, course_id)


@router.get("/rag/documents")
def rag_documents() -> dict:
    return get_documents_summary()


@router.get("/rag/chunks")
def rag_chunks() -> dict:
    return get_chunks_summary()


@router.get("/rag/search")
def rag_search(query: str, limit: int = 5) -> dict:
    return get_search_summary(query, limit)


@router.get("/rag/semantic-search")
def rag_semantic_search(
    query: str,
    limit: int = 3,
    subject_id: int | None = None,
    course_id: int | None = None,
    document_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict:
    results = rag_document_service.filtered_semantic_search(
        db,
        query,
        subject_id=subject_id,
        course_id=course_id,
        document_id=document_id,
        top_k=limit,
        published_only=True,
    )
    return {"query": query, "total_results": len(results), "results": results, "mode": "rag_semantic"}


@router.get("/rag/vector-store/status")
def rag_vector_store_status() -> dict:
    return get_vector_store_status()
