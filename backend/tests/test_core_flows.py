from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import persistence as persistence_models  # noqa: F401
from app.models.persistence import CourseProgress, UserProfile
from app.schemas.persistence import CourseProgressCreate, CourseProgressUpdate, UserProfileUpdate
from app.services import course_service, learning_service, persistence_service


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'edumentor_test.db'}",
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


def test_firebase_user_is_created_by_real_uid(db_session):
    user = persistence_service.get_or_create_user_from_firebase(
        db_session,
        {"uid": "real-firebase-uid-a", "email": "learner@example.com", "name": "Learner One"},
    )

    assert user.id is not None
    assert user.firebase_uid == "real-firebase-uid-a"
    assert user.email == "learner@example.com"
    assert user.role == "user"

    same_user = persistence_service.get_or_create_user_from_firebase(
        db_session,
        {"uid": "real-firebase-uid-a", "email": "learner@example.com", "name": "Learner One"},
    )

    assert same_user.id == user.id


def test_firebase_email_collision_with_real_uid_returns_409(db_session):
    persistence_service.get_or_create_user_from_firebase(
        db_session,
        {"uid": "real-firebase-uid-a", "email": "learner@example.com", "name": "Learner One"},
    )

    with pytest.raises(HTTPException) as exc_info:
        persistence_service.get_or_create_user_from_firebase(
            db_session,
            {"uid": "real-firebase-uid-b", "email": "learner@example.com", "name": "Learner Two"},
        )

    assert exc_info.value.status_code == 409


def test_profile_update_does_not_change_role(db_session):
    user = UserProfile(
        firebase_uid="admin-uid",
        email="admin@example.com",
        full_name="Admin",
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    updated = persistence_service.update_profile(
        db_session,
        user,
        UserProfileUpdate(full_name="New Name", email="new-admin@example.com"),
    )

    assert updated.full_name == "New Name"
    assert updated.email == "new-admin@example.com"
    assert updated.role == "admin"


def test_progress_create_and_update_are_idempotent(db_session):
    user = UserProfile(firebase_uid="learner-uid", email="learner@example.com", full_name="Learner")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    first = persistence_service.create_progress(
        db_session,
        user,
        CourseProgressCreate(course_id=1, progress=25, chapters=[{"status": "active"}]),
    )
    second = persistence_service.update_progress(
        db_session,
        user,
        1,
        CourseProgressUpdate(progress=50, chapters=[{"status": "completed"}]),
    )

    assert first.id == second.id
    assert second.progress == 50
    assert db_session.query(CourseProgress).filter_by(user_id=user.id, course_id=1).count() == 1


def test_seeded_courses_and_quiz_are_available(db_session):
    course_service.seed_courses_from_mock(db_session)

    courses = course_service.get_courses(db_session)
    quiz = course_service.get_quiz(db_session, 1)
    answer_key = [question["answer"] for question in course_service.get_quiz_questions_for_grading(db_session, 1)]
    result = course_service.grade_quiz(db_session, 1, answer_key)

    assert len(courses) == 8
    assert len(quiz["questions"]) >= 10
    assert result["score"] == 100
    assert result["correct_answers"] == result["total_questions"]


def test_chat_uses_semantic_rag_when_relevant(monkeypatch):
    monkeypatch.setattr(
        learning_service,
        "semantic_search",
        lambda query, limit=3: [
            {
                "file_name": "06_RAG.pdf",
                "course_name": "RAG",
                "page_number": 2,
                "score": 0.92,
                "text": "Le RAG combine recherche documentaire et generation.",
            }
        ],
    )

    response = learning_service.rag_chat("C'est quoi le RAG ?", "Débutant")

    assert response["mode"] == "rag_semantic"
    assert response["answer"].startswith("# Définition simple")
    assert response["sources"][0]["file_name"] == "06_RAG.pdf"


def test_chat_routes_ai_question_to_general_when_rag_is_not_relevant(monkeypatch):
    monkeypatch.setattr(learning_service, "semantic_search", lambda query, limit=3: [])
    monkeypatch.setattr(
        learning_service,
        "generate_general_answer",
        lambda message, language, level: "General answer\n\nBackpropagation is an AI training concept.",
    )

    response = learning_service.rag_chat("What is backpropagation?", "Avancé")

    assert response["mode"] == "general"
    assert response["sources"] == []


def test_chat_rejects_out_of_scope_question(monkeypatch):
    monkeypatch.setattr(learning_service, "semantic_search", lambda query, limit=3: [])

    response = learning_service.rag_chat("Quelle est la météo ?", "Intermédiaire")

    assert response["mode"] == "out_of_scope"
    assert "EduMentor AI" in response["answer"]


def test_social_message_does_not_call_rag(monkeypatch):
    def fail_search(query, limit=3):
        raise AssertionError("semantic_search should not be called for social messages")

    monkeypatch.setattr(learning_service, "semantic_search", fail_search)

    response = learning_service.rag_chat("Bonjour", "Débutant")

    assert response["mode"] == "social"
    assert "Bonjour" in response["answer"]
