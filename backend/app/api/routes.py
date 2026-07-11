from pathlib import Path
import json
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.requests import ChatRequest, DiagnosticSubmission, QuizSubmission
from app.rag.document_store import get_chunks_summary, get_documents_summary, get_search_summary
from app.rag.vector_store import get_semantic_search_summary, get_vector_store_status
from app.services import learning_service
from app.services import course_service

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


@router.get("/courses")
def courses(db: Session = Depends(get_db)) -> list[dict]:
    return course_service.get_courses(db)


@router.get("/courses/{course_id}")
def course_detail(course_id: int, db: Session = Depends(get_db)) -> dict:
    return course_service.get_course_detail(db, course_id)


@router.post("/diagnostic")
def submit_diagnostic(payload: DiagnosticSubmission) -> dict:
    return learning_service.evaluate_diagnostic(payload.answers)


@router.get("/diagnostic/questions")
def get_diagnostic_questions() -> dict:
    data = load_questions()
    questions = random.sample(data["questions"], 20)

    public_questions = [
        {
            "id": q["id"],
            "theme": q.get("theme"),
            "question": q["question"],
            "options": q["options"],
        }
        for q in questions
    ]

    return {"total": 20, "questions": public_questions}


@router.post("/diagnostic/submit")
def submit_diagnostic_test(payload: dict) -> dict:
    data = load_questions()
    questions_by_id = {int(q["id"]): q for q in data["questions"]}

    answers = payload.get("answers", {})
    corrections = []
    correct_count = 0

    for question_id, user_answer in answers.items():
        question = questions_by_id.get(int(question_id))
        if not question:
            continue

        is_correct = int(user_answer) == int(question["correct_index"])
        if is_correct:
            correct_count += 1

        corrections.append({
            "id": question["id"],
            "theme": question.get("theme"),
            "question": question["question"],
            "options": question["options"],
            "user_answer": int(user_answer),
            "correct_index": int(question["correct_index"]),
            "is_correct": is_correct,
            "explanation": question["explanation"],
        })

    total = len(corrections)
    score = round((correct_count / total) * 100) if total else 0

    if score <= 40:
        level = "Débutant"
    elif score <= 75:
        level = "Intermédiaire"
    else:
        level = "Avancé"

    return {
        "score": score,
        "level": level,
        "correct_count": correct_count,
        "total": total,
        "corrections": corrections,
    }


@router.get("/quiz/{course_id}")
def get_quiz(course_id: int, db: Session = Depends(get_db)) -> dict:
    return course_service.get_quiz(db, course_id)


@router.post("/quiz/{course_id}/submit")
def submit_quiz(course_id: int, payload: QuizSubmission, db: Session = Depends(get_db)) -> dict:
    return course_service.grade_quiz(db, course_id, payload.answers)


@router.post("/chat")
def chat(payload: ChatRequest) -> dict:
    return learning_service.rag_chat(payload.message, payload.level, payload.context)


@router.get("/rag/status")
def rag_status() -> dict:
    return learning_service.get_rag_status()


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
def rag_semantic_search(query: str, limit: int = 3) -> dict:
    return get_semantic_search_summary(query, limit)


@router.get("/rag/vector-store/status")
def rag_vector_store_status() -> dict:
    return get_vector_store_status()
