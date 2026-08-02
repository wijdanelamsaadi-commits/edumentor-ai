from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.core.catalog_migration import apply_catalog_migration
from app.core.database import Base
from app.core.diagnostic_migration import apply_diagnostic_migration
from app.core.professor_migration import apply_professor_migration
from app.models import persistence as persistence_models  # noqa: F401
from app.models.persistence import Course, Subject, UserProfile
from app.services import learning_service, rag_document_service


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'edumentor_chat_test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    apply_catalog_migration(engine)
    apply_diagnostic_migration(engine)
    apply_professor_migration(engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def build_chat_client(db_session, current_user: UserProfile | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[routes.get_db] = override_db
    if current_user is not None:
        if current_user.id is not None and db_session.get(UserProfile, current_user.id) is None:
            db_session.add(current_user)
            db_session.commit()
            db_session.refresh(current_user)
        app.dependency_overrides[routes.get_current_user] = lambda: current_user
        app.dependency_overrides[routes.get_optional_current_user] = lambda: current_user
    return TestClient(app)


def test_chat_requires_authenticated_user(db_session):
    client = build_chat_client(db_session)

    response = client.post("/api/chat", json={"message": "Bonjour", "level": "Intermediaire"})

    assert response.status_code == 401


def test_chat_authenticated_user_gets_social_response(db_session):
    student = UserProfile(id=7100, firebase_uid="chat-api", email="chat-api@example.com", full_name="Student", role="student")
    client = build_chat_client(db_session, student)

    response = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer test"},
        json={"message": "Bonjour", "level": "Intermediaire"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "social"


def test_chat_uses_french_semantic_rag_and_filters_old_ai_documents(monkeypatch, db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    student = UserProfile(id=7101, firebase_uid="chat-student", email="chat-student@example.com", full_name="Student", role="student")
    course = Course(id=7102, title="Français 1ère Bac - Préparation complète au régional", subject=subject, published=True, status="published")
    db_session.add_all([student, course])
    db_session.commit()
    captured = {}

    def fake_filtered_semantic_search(db, query, **kwargs):
        captured.update(kwargs)
        return [
            {
                "file_name": "antigone.pdf",
                "course_title": course.title,
                "course_id": course.id,
                "subject_id": subject.id,
                "subject_name": "Français",
                "page_start": 2,
                "score": 0.92,
                "excerpt": "Créon représente l'autorité politique et défend l'ordre de la cité.",
                "text_preview": "Créon représente l'autorité politique et défend l'ordre de la cité.",
            }
        ]

    monkeypatch.setattr(rag_document_service, "filtered_semantic_search", fake_filtered_semantic_search)
    monkeypatch.setattr(learning_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: {"competencies": []})

    response = learning_service.rag_chat(
        "Résume le rôle de Créon dans Antigone.",
        "Intermédiaire",
        db=db_session,
        current_user=student,
    )

    assert response["mode"] == "rag_course"
    assert response["intent"] == "work_explanation"
    assert response["sources"][0]["file_name"] == "antigone.pdf"
    assert captured["course_id"] == course.id
    assert captured["subject_id"] == subject.id


def test_chat_routes_french_question_to_french_fallback(monkeypatch, db_session):
    student = UserProfile(id=7103, firebase_uid="chat-general", email="chat-general@example.com", full_name="Student", role="student")
    db_session.add(student)
    db_session.commit()
    monkeypatch.setattr(rag_document_service, "filtered_semantic_search", lambda db, query, **kwargs: [])
    monkeypatch.setattr(
        learning_service,
        "generate_general_answer",
        lambda message, language, level, **kwargs: "### Reponse\n\nCreon defend l'ordre de la cite.",
    )
    monkeypatch.setattr(learning_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: {"competencies": []})

    response = learning_service.rag_chat("Résume le rôle de Créon dans Antigone.", "Avancé", db=db_session, current_user=student)

    assert response["mode"] == "general_french"
    assert response["sources"] == []


def test_chat_rejects_python_as_out_of_scope(db_session):
    student = UserProfile(id=7104, firebase_uid="chat-scope", email="chat-scope@example.com", full_name="Student", role="student")
    db_session.add(student)
    db_session.commit()

    response = learning_service.rag_chat("Explique-moi Python.", "Intermédiaire", db=db_session, current_user=student)

    assert response["mode"] == "out_of_scope"
    assert "regional de francais" in response["answer"]


def test_targeted_practice_uses_public_weakness_profile(monkeypatch, db_session):
    student = UserProfile(id=7105, firebase_uid="chat-weakness", email="chat-weakness@example.com", full_name="Student", role="student")
    db_session.add(student)
    db_session.commit()
    monkeypatch.setattr(
        learning_service.student_weakness_model_service,
        "predict_student_weaknesses",
        lambda db, user: {
            "model": {"version": "secret"},
            "competencies": [
                {
                    "competence": "Langue",
                    "status": "faible",
                    "score_percentage": 35,
                    "confidence": 0.99,
                    "recommendation": "Reviser la regle concernee.",
                }
            ],
        },
    )

    response = learning_service.rag_chat("Fais-moi travailler ma competence la plus faible.", "Intermédiaire", db=db_session, current_user=student)

    assert response["mode"] == "targeted_practice"
    assert "Langue" in response["answer"]
    assert "secret" not in response["answer"]
    assert "confidence" not in response["answer"]
