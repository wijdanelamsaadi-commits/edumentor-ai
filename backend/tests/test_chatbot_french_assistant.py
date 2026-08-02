from __future__ import annotations

import unicodedata

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


def strip_accents(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


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
    assert "regional de francais" in strip_accents(response["answer"])


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


def test_chat_sequential_conversation_uses_current_message_for_intent_and_rag(monkeypatch, db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    student = UserProfile(id=7106, firebase_uid="chat-sequential", email="chat-sequential@example.com", full_name="Student", role="student")
    course = Course(id=7107, title="Francais 1ere Bac - Preparation au regional", subject=subject, published=True, status="published")
    db_session.add_all([student, course])
    db_session.commit()
    queries = []

    def fake_filtered_semantic_search(db, query, **kwargs):
        queries.append(query)
        normalized = learning_service._normalize_text(query)
        if "djellaba" in normalized:
            return [{
                "file_name": "figures.md",
                "display_source": "Figures de style - Personnification",
                "course_title": course.title,
                "course_id": course.id,
                "subject_id": subject.id,
                "score": 0.92,
                "excerpt": "Dans l'expression la djellaba dormait, l'objet recoit une action humaine: c'est une personnification.",
                "text_preview": "Dans l'expression la djellaba dormait, l'objet recoit une action humaine: c'est une personnification.",
            }]
        if "narrateur externe" in normalized:
            return [{
                "file_name": "boite.md",
                "display_source": "La Boite a merveilles - Fiche de revision",
                "course_title": course.title,
                "course_id": course.id,
                "subject_id": subject.id,
                "score": 0.91,
                "excerpt": "Sidi Mohamed est narrateur-personnage et raconte a la premiere personne.",
                "text_preview": "Sidi Mohamed est narrateur-personnage et raconte a la premiere personne.",
            }]
        if "situer un passage" in normalized:
            return [{
                "file_name": "methodologie.md",
                "display_source": "Methodologie - Situer un passage",
                "course_title": course.title,
                "course_id": course.id,
                "subject_id": subject.id,
                "score": 0.9,
                "excerpt": "Situer un passage consiste a presenter l'evenement precedent, le contexte et la situation du passage.",
                "text_preview": "Situer un passage consiste a presenter l'evenement precedent, le contexte et la situation du passage.",
            }]
        if "solidarite" in normalized:
            return [{
                "file_name": "production.md",
                "display_source": "Production ecrite - Introduction",
                "course_title": course.title,
                "course_id": course.id,
                "subject_id": subject.id,
                "score": 0.9,
                "excerpt": "Une introduction presente le sujet, pose une problematique et annonce une opinion.",
                "text_preview": "Une introduction presente le sujet, pose une problematique et annonce une opinion.",
            }]
        return []

    monkeypatch.setattr(rag_document_service, "filtered_semantic_search", fake_filtered_semantic_search)
    monkeypatch.setattr(learning_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: {"competencies": []})

    messages = [
        "Quelle figure de style trouve-t-on dans la djellaba dormait ?",
        "Corrige ma reponse : Sidi Mohamed est un narrateur externe.",
        "Comment situer un passage dans une oeuvre lors de l'examen regional ?",
        "Aide-moi a preparer une introduction sur la solidarite.",
        "Explique-moi le Deep Learning.",
    ]
    context = []
    responses = []
    for index, message in enumerate(messages, start=1):
        response = learning_service.rag_chat(
            message,
            "Intermediaire",
            context=context,
            db=db_session,
            current_user=student,
            client_message_id=f"msg-{index}",
        )
        responses.append(response)
        context.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": response["answer"]},
        ])

    assert responses[0]["intent"] == "figure_of_style"
    assert "personnification" in learning_service._normalize_text(responses[0]["answer"])
    assert responses[1]["intent"] == "answer_correction"
    assert "narrateur-personnage" in responses[1]["answer"] or "premiere personne" in learning_service._normalize_text(responses[1]["answer"])
    assert "personnification" not in learning_service._normalize_text(responses[1]["answer"])
    assert responses[2]["intent"] == "methodology_help"
    normalized_method = learning_service._normalize_text(responses[2]["answer"])
    assert "evenement" in normalized_method or "contexte" in normalized_method or "situation" in normalized_method
    assert "djellaba dormait" not in normalized_method
    assert "narrateur externe" not in normalized_method
    assert responses[3]["intent"] == "writing_assistance"
    normalized_writing = learning_service._normalize_text(responses[3]["answer"])
    assert "sujet" in normalized_writing
    assert "problematique" in normalized_writing or "opinion" in normalized_writing or "introduction" in normalized_writing
    assert "sidi mohamed" not in normalized_writing
    assert responses[4]["intent"] == "out_of_scope"
    assert responses[4]["mode"] == "out_of_scope"
    assert all(message in query for message, query in zip(messages[:4], queries[:4]))


def test_chat_returns_client_message_id_for_fast_requests(monkeypatch, db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    student = UserProfile(id=7108, firebase_uid="chat-fast", email="chat-fast@example.com", full_name="Student", role="student")
    course = Course(id=7109, title="Francais 1ere Bac - Preparation au regional", subject=subject, published=True, status="published")
    db_session.add_all([student, course])
    db_session.commit()
    monkeypatch.setattr(learning_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: {"competencies": []})
    monkeypatch.setattr(
        rag_document_service,
        "filtered_semantic_search",
        lambda db, query, **kwargs: [{
            "file_name": "methodologie.md",
            "display_source": "Methodologie - Situer un passage",
            "course_title": course.title,
            "course_id": course.id,
            "subject_id": subject.id,
            "score": 0.9,
            "excerpt": "Situer un passage demande de rappeler le contexte.",
            "text_preview": "Situer un passage demande de rappeler le contexte.",
        }],
    )

    first = learning_service.rag_chat("Comment situer un passage ?", "Intermediaire", db=db_session, current_user=student, client_message_id="fast-1")
    second = learning_service.rag_chat("Aide-moi a preparer une introduction sur la solidarite.", "Intermediaire", db=db_session, current_user=student, client_message_id="fast-2")

    assert first["client_message_id"] == "fast-1"
    assert second["client_message_id"] == "fast-2"
    assert first["intent"] == "methodology_help"
    assert second["intent"] == "writing_assistance"

