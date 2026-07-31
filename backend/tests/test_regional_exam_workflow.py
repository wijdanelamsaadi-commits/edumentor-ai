from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import auth_dependencies, regional_routes
from app.core.database import Base
from app.models import persistence as persistence_models  # noqa: F401
from app.models.persistence import (
    Assessment,
    AssessmentAssignment,
    AssessmentQuestion,
    Course,
    Subject,
    UserProfile,
)


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'regional_test.db'}",
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
        app.dependency_overrides[regional_routes.get_current_student] = lambda: current_user
    return TestClient(app)


@pytest.fixture()
def regional_fixture(db_session):
    subject = Subject(name="Français", slug="francais", active=True)
    course = Course(title="Préparation régional français", level="Adaptatif", summary="Cours", description="Cours", subject=subject, published=True, status="published")
    student = UserProfile(email="student@example.com", full_name="Student", role="student", status="active")
    other_student = UserProfile(email="other@example.com", full_name="Other", role="student", status="active")
    professor = UserProfile(email="prof@example.com", full_name="Professor", role="professor", status="active")
    db_session.add_all([subject, course, student, other_student, professor])
    db_session.flush()
    metadata = {
        "is_regional_exam": True,
        "exam_kind": "regional",
        "type": "training",
        "source_status": "teacher_proposal",
        "year": "2026",
        "region": "Casablanca-Settat",
        "session": "Normale",
        "work_id": "ANT",
        "work_title": "Antigone",
        "duration_minutes": 120,
        "support_text": "Court texte support fourni pour l'entraînement.",
    }
    assessment = Assessment(
        professor_id=professor.id,
        course_id=course.id,
        subject_id=subject.id,
        title="Entraînement régional Antigone",
        description=json.dumps({"regional_exam": metadata}),
        instructions="Répondez aux questions.",
        assessment_type="practice",
        status="published",
        max_attempts=3,
        time_limit_minutes=120,
    )
    db_session.add(assessment)
    db_session.flush()
    db_session.add_all([
        AssessmentQuestion(
            assessment_id=assessment.id,
            question="Qui s'oppose à Antigone ?",
            choices=["Créon", "Sidi Mohammed", "Le condamné"],
            correct_answer="Créon",
            explanation="Créon représente l'autorité politique opposée au choix d'Antigone.",
            points=2,
            order_index=1,
            active=True,
            adaptation_reason=json.dumps({"section": "Compréhension", "competence": "compréhension", "question_type": "qcm"}),
        ),
        AssessmentQuestion(
            assessment_id=assessment.id,
            question="Expliquez brièvement le conflit central.",
            choices=[],
            correct_answer="loi|famille|autorité",
            explanation="La réponse doit évoquer l'opposition entre la loi de Créon et le devoir familial d'Antigone.",
            points=3,
            order_index=2,
            active=True,
            adaptation_reason=json.dumps({"section": "Interprétation", "competence": "interprétation", "question_type": "response_short", "expected_elements": ["loi", "famille", "autorité"]}),
        ),
    ])
    db_session.add(AssessmentAssignment(assessment_id=assessment.id, student_id=student.id, status="assigned"))
    db_session.commit()
    return {
        "assessment": assessment,
        "student": student,
        "other_student": other_student,
    }


def test_regional_exam_list_requires_authentication(db_session):
    response = build_client(db_session).get("/api/regional-exams")

    assert response.status_code == 401


def test_student_lists_regional_exams_and_filters(db_session, regional_fixture):
    client = build_client(db_session, regional_fixture["student"])

    response = client.get("/api/regional-exams?region=Casablanca-Settat&work_id=ANT&session=Normale")
    data = response.json()

    assert response.status_code == 200
    assert data["total"] == 1
    assert data["exams"][0]["type_label"] == "Entraînement inspiré des examens régionaux"
    assert data["exams"][0]["status"] == "non commencé"


def test_regional_exam_detail_hides_correct_answers_before_submission(db_session, regional_fixture):
    client = build_client(db_session, regional_fixture["student"])
    exam_id = regional_fixture["assessment"].id

    response = client.get(f"/api/regional-exams/{exam_id}")
    body = response.json()

    assert response.status_code == 200
    assert body["correction_available"] is False
    assert "correct_answer" not in body["questions"][0]
    assert "holdout" not in json.dumps(body).lower()


def test_regional_attempt_start_and_submit_qcm_score(db_session, regional_fixture):
    client = build_client(db_session, regional_fixture["student"])
    exam_id = regional_fixture["assessment"].id

    started = client.post(f"/api/regional-exams/{exam_id}/start").json()
    result_response = client.post(
        f"/api/regional-exams/{exam_id}/submit",
        json={
            "attempt_id": started["attempt_id"],
            "answers": {
                "1": "Créon",
                "2": "La loi s'oppose à la famille et à l'autorité morale.",
            },
        },
    )
    result = result_response.json()

    assert result_response.status_code == 200
    assert result["correction_available"] is True
    assert result["score"] == 5
    assert result["percentage"] == 100
    assert result["questions"][0]["correct_answer"] == "Créon"


def test_regional_attempt_history_and_best_score(db_session, regional_fixture):
    client = build_client(db_session, regional_fixture["student"])
    exam_id = regional_fixture["assessment"].id

    client.post(f"/api/regional-exams/{exam_id}/submit", json={"answers": {"1": "Créon", "2": "loi famille autorité"}})
    attempts = client.get(f"/api/regional-exams/{exam_id}/attempts").json()
    exams = client.get("/api/regional-exams").json()

    assert attempts["total"] == 1
    assert exams["exams"][0]["best_score"] == 100
    assert exams["stats"]["best_score"] == 100


def test_student_cannot_access_another_students_regional_attempt(db_session, regional_fixture):
    student_client = build_client(db_session, regional_fixture["student"])
    other_client = build_client(db_session, regional_fixture["other_student"])
    exam_id = regional_fixture["assessment"].id
    result = student_client.post(f"/api/regional-exams/{exam_id}/submit", json={"answers": {"1": "Créon"}}).json()

    response = other_client.get(f"/api/regional-exam-attempts/{result['attempt_id']}")

    assert response.status_code == 403


def test_unassigned_student_does_not_see_regional_exam(db_session, regional_fixture):
    client = build_client(db_session, regional_fixture["other_student"])
    exam_id = regional_fixture["assessment"].id

    assert client.get("/api/regional-exams").json()["total"] == 0
    assert client.get(f"/api/regional-exams/{exam_id}").status_code == 404
