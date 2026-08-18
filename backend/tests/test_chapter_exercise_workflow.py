from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import auth_dependencies, regional_routes
from app.core.database import Base
from app.models import persistence as persistence_models  # noqa: F401
from app.models.persistence import (
    Course,
    CourseChapter,
    CourseLevelVariant,
    DiagnosticResult,
    QuizResult,
    UserProfile,
)


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chapter_exercises.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def build_client(db_session, current_user: UserProfile | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(regional_routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[regional_routes.get_db] = override_db
    if current_user is not None:
        app.dependency_overrides[auth_dependencies.get_current_authenticated_user] = lambda: current_user
        app.dependency_overrides[auth_dependencies.get_optional_current_user] = lambda: current_user
        app.dependency_overrides[regional_routes.get_current_student] = lambda: current_user
    return TestClient(app)


@pytest.fixture()
def exercise_fixture(db_session):
    student = UserProfile(email="student-exercises@example.com", full_name="Student", role="student", status="active", level="Avance")
    other_student = UserProfile(email="other-exercises@example.com", full_name="Other", role="student", status="active")
    course = Course(
        title="Cours interactif Antigone",
        level="Adaptatif",
        summary="Cours",
        description="Cours",
        published=True,
        status="published",
    )
    chapter = CourseChapter(
        course=course,
        title="Antigone",
        duration="30 min",
        status="active",
        openable=True,
        active=True,
        position=1,
        structured_content=[
            {
                "id": "original-exercise",
                "type": "exercise",
                "content": "Question originale non prioritaire",
                "answer": "Original",
                "correction": "Correction originale",
            }
        ],
    )
    db_session.add_all([student, other_student, course])
    db_session.flush()
    variant_blocks = [
        {
            "id": "qcm-creon",
            "type": "exercise",
            "section": "training_exams",
            "content": {
                "question": "Qui s'oppose à Antigone ?",
                "choices": ["Créon", "Sidi Mohammed", "Le condamné"],
                "answer": "Créon",
                "explanation": "Créon représente l'autorité politique face à Antigone.",
                "competence": "Compréhension",
                "points": 2,
            },
        },
        {
            "id": "short-conflict",
            "type": "exercise",
            "section": "training_exams",
            "content": {
                "question": "Expliquez le conflit central.",
                "expected_elements": ["loi", "famille", "autorité"],
                "answer": "loi; famille; autorité",
                "correction": "La réponse doit évoquer la loi de Créon, le devoir familial et l'autorité.",
                "competence": "Interprétation",
                "points": 3,
            },
        },
        {
            "id": "justification-antigone",
            "type": "exercise",
            "section": "training_exams",
            "content": {
                "question": "Justifiez pourquoi Antigone refuse d'obéir.",
                "type": "justification",
                "expected_elements": ["refus", "loi", "argument"],
                "answer": "refus; loi; argument",
                "correction": "Une justification complète répond, cite un indice et explique l'argument.",
                "competence": "Justification",
                "points": 3,
            },
        },
        {
            "id": "figure-accumulation",
            "type": "exercise",
            "section": "training_exams",
            "content": {
                "question": "Identifiez la figure : Des cris, des pas, des chaînes et des prières...",
                "type": "figure_style",
                "answer": "accumulation",
                "correction": "La phrase accumule plusieurs éléments.",
                "explanation": "L'effet produit insiste sur la multiplicité et la tension.",
                "competence": "Figures de style",
                "points": 1,
            },
        },
        {
            "id": "long-analysis",
            "type": "exercise",
            "section": "training_exams",
            "content": {
                "question": "Rédigez un paragraphe d'analyse.",
                "type": "response_long",
                "answer": "Réponse ouverte",
                "correction": "Validation enseignante nécessaire.",
                "competence": "Production écrite",
                "points": 5,
            },
        },
    ]
    db_session.add(CourseLevelVariant(
        course_id=course.id,
        level="intermediaire",
        title="Antigone intermédiaire",
        structured_content=[{
            "course_chapter_id": chapter.id,
            "chapter_source_id": "chapter_1",
            "source_chapter_id": "chapter_1",
            "generation_method": "ai_generated",
            "blocks": variant_blocks,
        }],
        generation_method="ai_generated",
        source_hash="chapter-exercise-test",
    ))
    db_session.add(DiagnosticResult(user_id=student.id, score=70, level="Intermédiaire", total=10, correct_count=7))
    db_session.commit()
    return {"course": course, "chapter": chapter, "student": student, "other_student": other_student}


def test_get_chapter_exercises_hides_corrections_and_uses_diagnostic_level(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    response = client.get(f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises")
    assert response.status_code == 200
    body = response.json()
    assert body["learner_level"] == "intermediaire"
    assert body["total"] == 5
    first = body["exercises"][0]
    assert first["id"] == "qcm-creon"
    assert "correct_answer" not in first
    assert "correction" not in first
    assert first["choices"] == ["Créon", "Sidi Mohammed", "Le condamné"]


def test_submit_correct_qcm_persists_score(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    response = client.post(
        f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/qcm-creon/submit",
        json={"answer": "Créon"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is True
    assert body["points_awarded"] == 2
    assert body["correct_answer"] == "Créon"
    assert db_session.query(QuizResult).count() == 1


def test_submit_incorrect_qcm_scores_zero(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    response = client.post(
        f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/qcm-creon/submit",
        json={"answer": "Sidi Mohammed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is False
    assert body["points_awarded"] == 0


def test_short_answer_accepts_equivalent_elements(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    response = client.post(
        f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/short-conflict/submit",
        json={"answer": "Le conflit oppose la loi à la famille et à l'autorité de Créon."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is True
    assert body["points_awarded"] == 3


def test_incomplete_justification_is_not_fully_correct(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    response = client.post(
        f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/justification-antigone/submit",
        json={"answer": "Antigone refuse."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is False
    assert body["points_awarded"] < 3


def test_figure_style_correction(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    response = client.post(
        f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/figure-accumulation/submit",
        json={"answer": "accumulation"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["correct"] is True
    assert "multiplicité" in body["explanation"]


def test_long_answer_is_pending_teacher_review(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    response = client.post(
        f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/long-analysis/submit",
        json={"answer": "Je propose une analyse argumentée du passage."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_teacher_review"
    assert body["correct"] is None
    assert "vérification enseignante" in body["explanation"]


def test_chapter_progress_and_history(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    url = f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/qcm-creon/submit"
    assert client.post(url, json={"answer": "Créon"}).status_code == 200
    assert client.post(url, json={"answer": "Créon"}).status_code == 200
    response = client.get(f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercise-progress")
    assert response.status_code == 200
    body = response.json()
    assert body["validated_questions"] == 1
    assert body["successful_questions"] == 1
    assert body["attempts_count"] == 2
    assert body["best_score"] == 100


def test_other_student_has_separate_progress(db_session, exercise_fixture):
    client = build_client(db_session, exercise_fixture["student"])
    client.post(
        f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercises/qcm-creon/submit",
        json={"answer": "Créon"},
    )
    other_client = build_client(db_session, exercise_fixture["other_student"])
    response = other_client.get(f"/api/courses/{exercise_fixture['course'].id}/chapters/{exercise_fixture['chapter'].id}/exercise-progress")
    assert response.status_code == 200
    assert response.json()["attempts_count"] == 0
