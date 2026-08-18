from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials
from fastapi import FastAPI
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import admin_routes, assessment_routes, auth_dependencies, parent_routes, professor_routes, regional_routes, routes
from app.api.professor_routes import router as professor_router
from app.core.catalog_migration import apply_catalog_migration
from app.core.assessment_migration import apply_assessment_migration
from app.core.diagnostic_migration import apply_diagnostic_migration
from app.core.database import Base
from app.core.professor_migration import apply_professor_migration
from app.core.rag_migration import apply_rag_migration
from app.core.role_migration import apply_role_migration
from app.core.roles import UserRole
from app.models import persistence as persistence_models  # noqa: F401
from app.models.persistence import AdminAuditLog, Assessment, AssessmentAssignment, AssessmentAttempt, AssessmentQuestion, Classroom, ClassroomCourseAssignment, ClassroomMembership, Course, CourseChapter, CourseLevelVariant, CourseProgress, DiagnosticAnswer, DiagnosticQuestion, DiagnosticResult, DiagnosticSession, LiteraryWork, Notification, ParentNotification, ParentStudentLink, PedagogicalPackageImportJob, PersonalizedLesson, Quiz, QuizQuestion, QuizResult, RagDocument, RegionalExamProfile, RemediationPlan, StudyPath, StudyPathItem, Subject, UserProfile
from app.schemas.persistence import CourseProgressCreate, CourseProgressUpdate, UserProfileUpdate
from app.services import admin_service, assessment_service, automatic_course_generation_service, catalog_service, content_import_service, course_service, learning_service, parent_service, persistence_service, personalized_lesson_service, rag_document_service, regional_exam_service, study_path_service


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'edumentor_test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    apply_catalog_migration(engine)
    apply_diagnostic_migration(engine)
    apply_professor_migration(engine)
    apply_assessment_migration(engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def build_test_client(db_session, current_user: UserProfile | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.include_router(admin_routes.router, prefix="/api")
    app.include_router(professor_router, prefix="/api")
    app.include_router(assessment_routes.router, prefix="/api")
    app.include_router(parent_routes.router, prefix="/api")
    app.include_router(regional_routes.router, prefix="/api")

    def override_db():
        yield db_session

    app.dependency_overrides[routes.get_db] = override_db
    app.dependency_overrides[admin_routes.get_db] = override_db
    app.dependency_overrides[professor_routes.get_db] = override_db
    app.dependency_overrides[assessment_routes.get_db] = override_db
    app.dependency_overrides[parent_routes.get_db] = override_db
    app.dependency_overrides[regional_routes.get_db] = override_db

    if current_user is not None:
        if current_user.id is not None and db_session.get(UserProfile, current_user.id) is None:
            db_session.add(current_user)
            db_session.commit()
            db_session.refresh(current_user)

        app.dependency_overrides[auth_dependencies.get_current_authenticated_user] = lambda: current_user
        app.dependency_overrides[auth_dependencies.get_optional_current_user] = lambda: current_user

    return TestClient(app)


def test_firebase_user_is_created_by_real_uid(db_session):
    user = persistence_service.get_or_create_user_from_firebase(
        db_session,
        {"uid": "real-firebase-uid-a", "email": "learner@example.com", "name": "Learner One"},
    )

    assert user.id is not None
    assert user.firebase_uid == "real-firebase-uid-a"
    assert user.email == "learner@example.com"
    assert user.role == "student"

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


def test_role_migration_moves_user_to_student_and_keeps_admin(db_session):
    db_session.add_all([
        UserProfile(firebase_uid="old-user", email="old@example.com", full_name="Old User", role="user"),
        UserProfile(firebase_uid="admin-user", email="admin-role@example.com", full_name="Admin", role="admin"),
    ])
    db_session.commit()

    counts = apply_role_migration(db_session.get_bind())
    users = {user.email: user.role for user in db_session.query(UserProfile).all()}

    assert users["old@example.com"] == "student"
    assert users["admin-role@example.com"] == "admin"
    assert counts["student"] >= 1
    assert counts["admin"] >= 1


def test_student_can_use_common_role_dependency():
    student = UserProfile(email="student@example.com", full_name="Student", role="student")
    dependency = auth_dependencies.require_roles(UserRole.STUDENT, UserRole.PROFESSOR, UserRole.ADMIN)

    assert dependency(student) is student


def test_student_is_forbidden_from_admin_dependency():
    student = UserProfile(email="student-admin@example.com", full_name="Student", role="student")

    with pytest.raises(HTTPException) as exc_info:
        auth_dependencies.get_current_admin(student)

    assert exc_info.value.status_code == 403


def test_course_detail_selects_latest_diagnostic_variant(db_session):
    user = UserProfile(email="level-user@example.com", full_name="Learner", role="student", level="Debutant")
    course = Course(id=901, title="Cours adaptatif", level="Adaptatif", summary="Source", description="Source")
    chapter = CourseChapter(course=course, title="Chapitre 1", status="active", openable=True, position=1)
    db_session.add_all([user, course, chapter])
    db_session.flush()
    db_session.add_all([
        DiagnosticResult(user_id=user.id, level="Debutant", score=20),
        DiagnosticResult(user_id=user.id, level="Avance", score=95),
        CourseLevelVariant(
            course_id=course.id,
            level="avance",
            title="Cours adaptatif - avance",
            structured_content=[{"chapter_source_id": str(chapter.id), "title": "Version avancee"}],
            generation_method="ai_generated",
            source_hash="hash-avance",
        ),
    ])
    db_session.commit()

    detail = course_service.get_course_detail(db_session, course.id, current_user=user)

    assert detail["learner_level"] == "avance"
    assert detail["selected_variant"]["level"] == "avance"
    assert detail["selected_variant"]["chapters"][0]["title"] == "Version avancee"
    assert detail["original_chapters"][0]["title"] == "Chapitre 1"


def test_normalize_learner_level_aliases():
    assert course_service.normalize_learner_level("Débutant") == "debutant"
    assert course_service.normalize_learner_level("Intermédiaire") == "intermediaire"
    assert course_service.normalize_learner_level("advanced") == "avance"
    assert course_service.normalize_learner_level("Adaptatif") == ""


def test_assigned_course_denies_non_member(db_session):
    professor = UserProfile(email="prof-course@example.com", full_name="Prof", role="professor")
    member = UserProfile(email="member-course@example.com", full_name="Member", role="student")
    outsider = UserProfile(email="outsider-course@example.com", full_name="Outsider", role="student")
    course = Course(id=902, title="Cours classe", level="Adaptatif", summary="Source", description="Source")
    classroom = Classroom(name="Classe A", code="classe-a", professor=professor, active=True)
    db_session.add_all([professor, member, outsider, course, classroom])
    db_session.flush()
    db_session.add(ClassroomMembership(classroom_id=classroom.id, student_id=member.id, active=True))
    db_session.add(ClassroomCourseAssignment(classroom_id=classroom.id, course_id=course.id, assigned_by=professor.id, active=True))
    db_session.commit()

    assert course_service.can_access_course(db_session, course, member) is True
    assert course_service.can_access_course(db_session, course, outsider) is False


def test_new_diagnostic_changes_selected_variant_blocks(db_session):
    user = UserProfile(email="variant-switch@example.com", full_name="Learner", role="student", level="Debutant")
    course = Course(id=903, title="Cours switch", level="Adaptatif", summary="Source", description="Source")
    chapter = CourseChapter(course=course, title="Chapitre 1", status="active", openable=True, position=1)
    db_session.add_all([user, course, chapter])
    db_session.flush()
    db_session.add_all([
        CourseLevelVariant(
            course_id=course.id,
            level="debutant",
            title="Cours switch - debutant",
            structured_content=[{"chapter_source_id": str(chapter.id), "title": "Debutant", "blocks": [{"type": "summary", "content": "Bloc debutant simple"}]}],
            generation_method="deterministic_fallback",
            source_hash="hash-debutant",
        ),
        CourseLevelVariant(
            course_id=course.id,
            level="avance",
            title="Cours switch - avance",
            structured_content=[{"chapter_source_id": str(chapter.id), "title": "Avance", "blocks": [{"type": "summary", "content": "Bloc avance analytique"}]}],
            generation_method="deterministic_fallback",
            source_hash="hash-avance",
        ),
        DiagnosticResult(user_id=user.id, level="Debutant", score=40, created_at=datetime.utcnow() - timedelta(days=1)),
    ])
    db_session.commit()

    first_detail = course_service.get_course_detail(db_session, course.id, current_user=user)
    db_session.add(DiagnosticResult(user_id=user.id, level="Avance", score=95, created_at=datetime.utcnow()))
    db_session.commit()
    second_detail = course_service.get_course_detail(db_session, course.id, current_user=user)

    assert first_detail["learner_level"] == "debutant"
    assert second_detail["learner_level"] == "avance"
    assert first_detail["selected_variant"]["chapters"][0]["blocks"][0]["content"] == "Bloc debutant simple"
    assert second_detail["selected_variant"]["chapters"][0]["blocks"][0]["content"] == "Bloc avance analytique"


def test_student_is_forbidden_from_professor_dependency():
    student = UserProfile(email="student-professor@example.com", full_name="Student", role="student")

    with pytest.raises(HTTPException) as exc_info:
        auth_dependencies.get_current_professor(student)

    assert exc_info.value.status_code == 403


def test_professor_can_access_professor_dashboard(db_session):
    professor = UserProfile(id=10, email="professor@example.com", full_name="Professor", role="professor", status="active")
    client = build_test_client(db_session, professor)

    response = client.get("/api/professor/dashboard", headers={"Authorization": "Bearer test"})

    assert response.status_code == 200
    assert response.json()["role"] == "professor"


def test_professor_is_forbidden_from_admin_dependency():
    professor = UserProfile(email="professor-admin@example.com", full_name="Professor", role="professor")

    with pytest.raises(HTTPException) as exc_info:
        auth_dependencies.get_current_admin(professor)

    assert exc_info.value.status_code == 403


def test_admin_can_use_admin_dependency():
    admin = UserProfile(email="admin-access@example.com", full_name="Admin", role="admin")

    assert auth_dependencies.get_current_admin(admin) is admin


def test_non_admin_cannot_change_another_user_role(db_session):
    actor = UserProfile(firebase_uid="student-actor", email="actor@example.com", full_name="Actor", role="student")
    target = UserProfile(firebase_uid="target-user", email="target@example.com", full_name="Target", role="student")
    db_session.add_all([actor, target])
    db_session.commit()
    db_session.refresh(actor)
    db_session.refresh(target)

    with pytest.raises(HTTPException) as exc_info:
        admin_service.update_user_role(db_session, actor, target.id, "admin")

    assert exc_info.value.status_code == 403


def test_last_active_admin_cannot_be_demoted(db_session):
    admin = UserProfile(firebase_uid="solo-admin", email="solo-admin@example.com", full_name="Admin", role="admin", status="active")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    with pytest.raises(HTTPException) as exc_info:
        admin_service.update_user_role(db_session, admin, admin.id, "student")

    assert exc_info.value.status_code == 400


def test_last_active_admin_cannot_be_disabled(db_session):
    admin = UserProfile(firebase_uid="solo-admin-status", email="solo-admin-status@example.com", full_name="Admin", role="admin", status="active")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    with pytest.raises(HTTPException) as exc_info:
        admin_service.update_user_status(db_session, admin, admin.id, "disabled")

    assert exc_info.value.status_code == 400


def test_role_change_creates_audit_log(db_session):
    admin = UserProfile(firebase_uid="audit-admin", email="audit-admin@example.com", full_name="Admin", role="admin", status="active")
    target = UserProfile(firebase_uid="audit-target", email="audit-target@example.com", full_name="Target", role="student", status="active")
    db_session.add_all([admin, target])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(target)

    admin_service.update_user_role(db_session, admin, target.id, "professor")
    audit_log = db_session.query(AdminAuditLog).filter_by(action="update_role", target_id=str(target.id)).one()

    assert audit_log.before_data["role"] == "student"
    assert audit_log.after_data["role"] == "professor"


def test_admin_can_change_user_role_to_and_from_parent_without_auto_link(db_session):
    admin = UserProfile(firebase_uid="parent-role-admin", email="parent-role-admin@example.com", full_name="Admin", role="admin", status="active")
    target = UserProfile(firebase_uid="parent-role-target", email="parent-role-target@example.com", full_name="Target", role="student", status="active")
    db_session.add_all([admin, target])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(target)

    parent_result = admin_service.update_user_role(db_session, admin, target.id, "parent")
    assert parent_result.role == "parent"
    assert db_session.query(ParentStudentLink).filter_by(parent_id=target.id).count() == 0

    student_result = admin_service.update_user_role(db_session, admin, target.id, "student")
    assert student_result.role == "student"


def test_disabled_account_receives_403(monkeypatch, db_session):
    user = UserProfile(firebase_uid="disabled-uid", email="disabled@example.com", full_name="Disabled", role="student", status="disabled")
    db_session.add(user)
    db_session.commit()

    monkeypatch.setattr(auth_dependencies, "verify_firebase_id_token", lambda token: {"uid": "disabled-uid", "email": "disabled@example.com"})

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    with pytest.raises(HTTPException) as exc_info:
        auth_dependencies.get_current_authenticated_user(credentials, db_session)

    assert exc_info.value.status_code == 403


def test_missing_token_receives_401(db_session):
    with pytest.raises(HTTPException) as exc_info:
        auth_dependencies.get_current_authenticated_user(None, db_session)

    assert exc_info.value.status_code == 401


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


def test_catalog_migration_creates_initial_subject_and_is_idempotent(db_session):
    first = apply_catalog_migration(db_session.get_bind())
    second = apply_catalog_migration(db_session.get_bind())

    assert first["subjects"] >= 1
    assert second["subjects"] == first["subjects"]
    assert db_session.query(Subject).filter_by(slug="francais").count() == 1
    assert db_session.query(Subject).filter_by(slug="francais", active=True).count() == 1
    assert db_session.query(persistence_models.EducationLevel).filter_by(slug="1ere_bac", active=True).count() == 1


def test_existing_courses_keep_ids_and_receive_subject(db_session):
    course_service.seed_courses_from_mock(db_session)
    apply_catalog_migration(db_session.get_bind())

    courses = course_service.get_courses(db_session)
    assert [course["id"] for course in courses] == list(range(1, 9))
    assert all(course["subject_id"] is not None for course in courses)
    assert all(course["subject"]["slug"] == "francais" for course in courses)


def test_public_subjects_endpoint_returns_active_subjects(db_session):
    client = build_test_client(db_session)

    response = client.get("/api/subjects")

    assert response.status_code == 200
    assert any(item["slug"] == "francais" for item in response.json())
    assert any(item["slug"] == "francais" and item["name"] == "Français" for item in response.json())


def test_public_education_levels_endpoint_contains_first_bac(db_session):
    client = build_test_client(db_session)

    response = client.get("/api/education-levels")

    assert response.status_code == 200
    assert any(item["slug"] == "1ere_bac" and item["name"] == "1ère année Baccalauréat" for item in response.json())


def test_non_admin_receives_403_on_admin_subject_create(db_session):
    client = build_test_client(db_session, current_user=UserProfile(id=50, email="student-route@example.com", role="student", status="active"))

    response = client.post("/api/admin/subjects", json={"name": "Biologie", "slug": "biologie"})

    assert response.status_code == 403


def test_admin_can_create_subject_and_duplicate_slug_is_rejected(db_session):
    client = build_test_client(db_session, current_user=UserProfile(id=51, email="admin-route@example.com", role="admin", status="active"))

    created = client.post("/api/admin/subjects", json={"name": "Biologie", "slug": "biologie"})
    duplicate = client.post("/api/admin/subjects", json={"name": "Biologie 2", "slug": "biologie"})

    assert created.status_code == 200
    assert created.json()["slug"] == "biologie"
    assert duplicate.status_code == 409


def test_subject_with_courses_cannot_be_deleted_and_can_be_deactivated(db_session):
    course_service.seed_courses_from_mock(db_session)
    apply_catalog_migration(db_session.get_bind())
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    client = build_test_client(db_session, current_user=UserProfile(id=52, email="admin-delete@example.com", role="admin", status="active"))

    delete_response = client.delete(f"/api/admin/subjects/{subject.id}")
    update_response = client.put(
        f"/api/admin/subjects/{subject.id}",
        json={
            "name": subject.name,
            "slug": subject.slug,
            "description": subject.description,
            "icon": subject.icon,
            "active": False,
            "display_order": subject.display_order,
        },
    )

    assert delete_response.status_code == 409
    assert update_response.status_code == 200
    assert update_response.json()["active"] is False


def test_diagnostic_questions_are_attached_to_ai_subject(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()

    assert db_session.query(DiagnosticQuestion).filter_by(subject_id=subject.id).count() >= 20


def test_diagnostic_questions_filter_by_french_subject_without_answer_key(db_session):
    client = build_test_client(db_session)
    subject = db_session.query(Subject).filter_by(slug="francais").one()

    response = client.get(f"/api/diagnostic/questions?subject_id={subject.id}&limit=8")

    assert response.status_code == 200
    questions = response.json()["questions"]
    assert len(questions) == 8
    assert all(question["subject_id"] == subject.id for question in questions)
    assert all("correct_answer" not in question for question in questions)


def test_diagnostic_submit_saves_french_subject_and_level(db_session):
    student = UserProfile(id=530, email="diag-student@example.com", full_name="Diag Student", role="student", status="active")
    db_session.add(student)
    db_session.commit()
    client = build_test_client(db_session, student)
    subject = db_session.query(Subject).filter_by(slug="francais").one()

    questions = client.get(f"/api/diagnostic/questions?subject_id={subject.id}&limit=5").json()["questions"]
    answers = {str(question["id"]): question["options"][0] for question in questions}

    result = client.post("/api/diagnostic/submit", json={"subject_id": subject.id, "answers": answers}).json()

    assert result["subject_id"] == subject.id
    assert result["level"] in {"Débutant", "Intermédiaire", "Avancé"}
    assert db_session.query(DiagnosticResult).filter_by(user_id=student.id, subject_id=subject.id).count() == 1


def test_diagnostic_recommendations_are_subject_limited_and_published_only(db_session):
    info = db_session.query(Subject).filter_by(slug="francais").one()
    ai = db_session.query(Subject).filter_by(slug="francais").one()
    beginner = db_session.query(persistence_models.DifficultyLevel).filter_by(slug="debutant").one()
    published = course_service.create_course(db_session, {
        "title": "Les figures de style",
        "summary": "Bases des figures de style",
        "description": "Cours d'analyse littéraire",
        "subject_id": info.id,
        "difficulty_level_id": beginner.id,
        "published": True,
    })
    unpublished = course_service.create_course(db_session, {
        "title": "Brouillon IA",
        "summary": "Brouillon",
        "description": "Non publie",
        "subject_id": ai.id,
        "difficulty_level_id": beginner.id,
        "published": False,
    })
    student = UserProfile(id=531, email="diag-rec@example.com", full_name="Diag Rec", role="student", status="active")
    db_session.add(student)
    db_session.commit()
    client = build_test_client(db_session, student)
    questions = client.get(f"/api/diagnostic/questions?subject_id={info.id}&limit=3").json()["questions"]
    answers = {str(question["id"]): "__wrong__" for question in questions}

    result = client.post("/api/diagnostic/submit", json={"subject_id": info.id, "answers": answers}).json()

    assert result["recommendations"][0]["course_id"] == published["id"]
    assert unpublished["id"] not in [item["course_id"] for item in result["recommendations"]]


def test_legacy_ai_diagnostic_result_is_preserved(db_session):
    student = UserProfile(id=534, email="legacy-diag@example.com", full_name="Legacy", role="student", status="active")
    legacy = DiagnosticResult(user_id=534, score=75, level="Intermediaire", total=20, correct_count=15, subject_id=None)
    db_session.add_all([student, legacy])
    db_session.commit()

    apply_diagnostic_migration(db_session.get_bind())
    db_session.refresh(legacy)
    ai = db_session.query(Subject).filter_by(slug="francais").one()

    assert legacy.subject_id == ai.id
    assert legacy.score == 75


def test_student_cannot_manage_diagnostic_bank_and_admin_can(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    difficulty = db_session.query(persistence_models.DifficultyLevel).filter_by(slug="debutant").one()
    payload = {
        "subject_id": subject.id,
        "difficulty_level_id": difficulty.id,
        "topic": "français",
        "question": "Quel élément permet de justifier une réponse ",
        "choices": ["un indice du texte", "une impression vague", "un hors-sujet"],
        "correct_answer": "un indice du texte",
        "explanation": "un indice du texte affiche un message.",
        "active": True,
    }
    student_client = build_test_client(db_session, UserProfile(id=532, email="diag-user@example.com", role="student", status="active"))
    admin_client = build_test_client(db_session, UserProfile(id=533, email="diag-admin@example.com", role="admin", status="active"))

    forbidden = student_client.post("/api/admin/diagnostic/questions", json=payload)
    created = admin_client.post("/api/admin/diagnostic/questions", json=payload)

    assert forbidden.status_code == 403
    assert created.status_code == 200
    assert created.json()["correct_answer"] == "un indice du texte"


def test_diagnostic_level_rules():
    from app.services.diagnostic_service import detect_level

    assert detect_level(30, [])[0] == "Débutant"
    assert detect_level(55, [])[0] == "Intermédiaire"
    assert detect_level(85, [{"name": "avance", "percentage": 25}])[0] == "Intermédiaire"
    assert detect_level(85, [{"name": "avance", "percentage": 70}])[0] == "Avancé"


def test_course_filters_by_subject_difficulty_and_search(db_session):
    course_service.seed_courses_from_mock(db_session)
    apply_catalog_migration(db_session.get_bind())
    difficulties = catalog_service.list_difficulty_levels(db_session)
    beginner = next(item for item in difficulties if item["slug"] == "debutant")

    by_subject = course_service.get_courses(db_session, subject_slug="francais")
    by_difficulty = course_service.get_courses(db_session, difficulty_level_id=beginner["id"])
    by_search = course_service.get_courses(db_session, search="Antigone")

    assert len(by_subject) == 8
    assert all(course["difficulty_level"]["slug"] == "debutant" for course in by_difficulty)
    assert [course["title"] for course in by_search] == ["Antigone"]


def test_course_detail_returns_catalog_metadata_and_keeps_quiz(db_session):
    course_service.seed_courses_from_mock(db_session)
    apply_catalog_migration(db_session.get_bind())

    detail = course_service.get_course_detail(db_session, 3)
    quiz = course_service.get_quiz(db_session, 3)

    assert detail["subject"]["slug"] == "francais"
    assert detail["difficulty_level"]["slug"] == "intermediaire"
    assert "education_level" in detail
    assert len(detail["chapters"]) >= 1
    assert len(quiz["questions"]) >= 10


def test_progress_survives_catalog_migration(db_session):
    user = UserProfile(firebase_uid="progress-catalog", email="progress-catalog@example.com", full_name="Learner", role="student")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    course_service.seed_courses_from_mock(db_session)
    progress = persistence_service.create_progress(db_session, user, CourseProgressCreate(course_id=1, progress=40, chapters=[]))

    apply_catalog_migration(db_session.get_bind())
    db_session.refresh(progress)

    assert db_session.query(CourseProgress).filter_by(user_id=user.id, course_id=1).one().progress == 40


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

    response = learning_service.rag_chat("C'est quoi le RAG ", "Débutant")

    assert response["mode"] == "out_of_scope"
    assert "fran" in response["answer"].lower()
    assert "1" in response["answer"]


def test_rag_migration_is_idempotent(db_session):
    first = apply_rag_migration(db_session.get_bind())
    second = apply_rag_migration(db_session.get_bind())

    assert "rag_documents" in first
    assert second["rag_documents"] == first["rag_documents"]


def test_rag_document_sync_creates_document_and_avoids_duplicate(monkeypatch, tmp_path, db_session):
    course_service.seed_courses_from_mock(db_session)
    pdf_dir = tmp_path / "courses"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as output:
        writer.write(output)

    course = course_service.get_course_model(db_session, 1)
    for seeded_course in [course_service.get_course_model(db_session, course_id) for course_id in range(2, 9)]:
        seeded_course.pdf_url = None
    course.pdf_url = "/docs/courses/sample.pdf"
    db_session.commit()
    monkeypatch.setattr(rag_document_service, "DOCS_DIR", pdf_dir)

    first = rag_document_service.sync_rag_documents(db_session)
    second = rag_document_service.sync_rag_documents(db_session)

    assert first["created"] == 1
    assert second["created"] == 0
    assert db_session.query(RagDocument).filter_by(course_id=1, active=True).count() == 1
    document = db_session.query(RagDocument).filter_by(course_id=1, active=True).one()
    assert document.page_count == 1
    assert document.checksum_sha256


def test_filtered_semantic_search_passes_course_and_subject_filters(monkeypatch, db_session):
    captured = {}

    def fake_semantic_search(query, limit=3, **kwargs):
        captured.update(kwargs)
        return [{"chunk_id": "x", "course_id": 9, "subject_id": 2, "score": 0.9}]

    monkeypatch.setattr(rag_document_service, "semantic_search", fake_semantic_search)

    results = rag_document_service.filtered_semantic_search(db_session, "français", course_id=9, subject_id=2, top_k=5)

    assert results[0]["course_id"] == 9
    assert captured["course_id"] == 9
    assert captured["subject_id"] == 2
    assert captured["published_only"] is True


def test_professor_cannot_read_other_course_rag_status(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor_a = UserProfile(id=301, email="rag-prof-a@example.com", full_name="Prof A", role="professor", status="active")
    professor_b = UserProfile(id=302, email="rag-prof-b@example.com", full_name="Prof B", role="professor", status="active")
    db_session.add_all([professor_a, professor_b])
    db_session.commit()
    other_course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Cours RAG autre"), "professor_id": professor_b.id})
    client = build_test_client(db_session, professor_a)

    response = client.get(f"/api/professor/courses/{other_course['id']}/rag/status", headers={"Authorization": "Bearer test"})

    assert response.status_code == 403


def test_pdf_text_quality_detects_broken_python_words():
    good = content_import_service.score_text_quality("Les figures de style. Une figure de style consiste à écrire un texte.")
    broken = content_import_service.score_text_quality("In roduc ion à Py hon. La programma ion consis e à écrire un texte.")

    assert good["score"] > broken["score"]
    assert broken["broken_words"] >= 2


def test_public_pdf_name_hides_internal_professor_filename():
    assert content_import_service.public_pdf_name("professor_7_course_9_f2dca30cf7964d0db86e059174d90208_python.pdf") == "python.pdf"
    assert content_import_service.public_pdf_name("06_RAG.pdf") == "06_RAG.pdf"


def test_french_import_structure_is_segmented_and_uses_public_sources(db_session):
    pages = [
        {"page_number": 1, "text": "1. Comprendre l'extrait\nLa lecture commence par identifier le narrateur, les personnages et le cadre de l'action."},
        {"page_number": 2, "text": "2. Identifier les figures de style\nUne comparaison rapproche deux éléments avec un outil comparatif. Une métaphore rapproche deux réalités sans outil."},
        {"page_number": 3, "text": "3. Justifier la réponse\nLa justification doit citer un indice du texte et expliquer son effet sur le sens."},
    ]
    course = course_service.build_course_model({"id": 90, "title": "Préparation au régional"}, 1)

    draft = content_import_service.build_generic_structure(
        course,
        pages,
        "support_francais.pdf",
    )

    assert len(draft["chapters"]) == 3
    assert draft["chapters"][0]["status"] == "active"
    assert draft["chapters"][1]["status"] == "locked"
    assert all(block["source_document_id"] == "support_francais.pdf" for chapter in draft["chapters"] for block in chapter["structured_content"])
    assert draft["chapters"][0]["structured_content"][0]["source_page_start"] == 1
    assert "figures de style" in draft["chapters"][1]["title"].lower()
    assert "indice du texte" in str(draft["chapters"][2]["structured_content"]).lower()


def test_normalize_text_keeps_internal_letters():
    text = content_import_service.normalize_text("français Introduction analyse littéraire titre utiliser")

    assert "français" in text
    assert "Introduction" in text
    assert "analyse littéraire" in text
    assert "titre" in text
    assert "utiliser" in text


def test_chat_routes_ai_question_to_general_when_rag_is_not_relevant(monkeypatch):
    monkeypatch.setattr(learning_service, "semantic_search", lambda query, limit=3: [])
    monkeypatch.setattr(
        learning_service,
        "generate_general_answer",
        lambda message, language, level: "General answer\n\nBackpropagation is an AI training concept.",
    )

    response = learning_service.rag_chat("What is backpropagation", "Avancé")

    assert response["mode"] == "out_of_scope"
    assert response["sources"] == []


def test_chat_rejects_out_of_scope_question(monkeypatch):
    monkeypatch.setattr(learning_service, "semantic_search", lambda query, limit=3: [])

    response = learning_service.rag_chat("Quelle est la météo ", "Intermédiaire")

    assert response["mode"] == "out_of_scope"
    assert "fran" in response["answer"].lower()
    assert "1" in response["answer"]


def test_social_message_does_not_call_rag(monkeypatch):
    def fail_search(query, limit=3):
        raise AssertionError("semantic_search should not be called for social messages")

    monkeypatch.setattr(learning_service, "semantic_search", fail_search)

    response = learning_service.rag_chat("Bonjour", "Débutant")

    assert response["mode"] == "social"
    assert "Bonjour" in response["answer"]


def make_professor_payload(subject_id: int, title: str = "Cours professeur") -> dict:
    return {
        "title": title,
        "summary": "Resume du cours professeur",
        "description": "Description complete du cours professeur.",
        "subject_id": subject_id,
        "estimated_duration": "2h",
        "professor_id": 999,
    }


def test_professor_creates_course_and_backend_sets_owner(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=201, firebase_uid="prof-a", email="prof-a@example.com", full_name="Prof A", role="professor", status="active")
    client = build_test_client(db_session, professor)

    response = client.post("/api/professor/courses", json=make_professor_payload(subject.id))

    assert response.status_code == 200
    assert response.json()["professor_id"] == professor.id
    assert response.json()["published"] is False
    assert response.json()["status"] == "draft"


def test_professor_sees_only_owned_courses(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor_a = UserProfile(id=202, email="prof-a-list@example.com", full_name="Prof A", role="professor", status="active")
    professor_b = UserProfile(id=203, email="prof-b-list@example.com", full_name="Prof B", role="professor", status="active")
    db_session.add_all([professor_a, professor_b])
    db_session.commit()
    course_service.create_course(db_session, {**make_professor_payload(subject.id, "Cours A"), "professor_id": professor_a.id})
    course_service.create_course(db_session, {**make_professor_payload(subject.id, "Cours B"), "professor_id": professor_b.id})
    client = build_test_client(db_session, professor_a)

    response = client.get("/api/professor/courses")

    assert response.status_code == 200
    assert [course["title"] for course in response.json()] == ["Cours A"]


def test_professor_can_modify_own_course_and_gets_403_on_other_course(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor_a = UserProfile(id=204, email="prof-a-own@example.com", full_name="Prof A", role="professor", status="active")
    professor_b = UserProfile(id=205, email="prof-b-own@example.com", full_name="Prof B", role="professor", status="active")
    db_session.add_all([professor_a, professor_b])
    db_session.commit()
    own_course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Cours perso"), "professor_id": professor_a.id})
    other_course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Cours autre"), "professor_id": professor_b.id})
    client = build_test_client(db_session, professor_a)

    own_response = client.put(f"/api/professor/courses/{own_course['id']}", json={"title": "Cours modifie"})
    forbidden_response = client.put(f"/api/professor/courses/{other_course['id']}", json={"title": "Hack"})

    assert own_response.status_code == 200
    assert own_response.json()["title"] == "Cours modifie"
    assert forbidden_response.status_code == 403


def test_student_receives_403_on_professor_routes(db_session):
    student = UserProfile(id=206, email="student-prof-routes@example.com", full_name="Student", role="student", status="active")
    client = build_test_client(db_session, student)

    response = client.get("/api/professor/courses")

    assert response.status_code == 403


def test_professor_receives_403_on_admin_routes(db_session):
    professor = UserProfile(id=207, email="prof-admin-route@example.com", full_name="Professor", role="professor", status="active")
    client = build_test_client(db_session, professor)

    response = client.get("/api/admin/courses")

    assert response.status_code == 403


def test_admin_can_assign_professor_and_cannot_assign_student(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    admin = UserProfile(id=208, email="admin-assign@example.com", full_name="Admin", role="admin", status="active")
    professor = UserProfile(id=209, email="prof-assign@example.com", full_name="Professor", role="professor", status="active")
    student = UserProfile(id=210, email="student-assign@example.com", full_name="Student", role="student", status="active")
    db_session.add_all([admin, professor, student])
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Cours admin"), "professor_id": None})
    client = build_test_client(db_session, admin)

    assigned = client.put(f"/api/admin/courses/{course['id']}/professor", json={"professor_id": professor.id})
    rejected = client.put(f"/api/admin/courses/{course['id']}/professor", json={"professor_id": student.id})
    audit = db_session.query(AdminAuditLog).filter_by(action="assign_course_professor", target_id=str(course["id"])).one()

    assert assigned.status_code == 200
    assert assigned.json()["professor_id"] == professor.id
    assert rejected.status_code == 422
    assert audit.after_data["professor_id"] == professor.id


def test_professor_creates_chapter_and_cannot_modify_other_course_chapter(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor_a = UserProfile(id=211, email="prof-chapter-a@example.com", full_name="Prof A", role="professor", status="active")
    professor_b = UserProfile(id=212, email="prof-chapter-b@example.com", full_name="Prof B", role="professor", status="active")
    db_session.add_all([professor_a, professor_b])
    db_session.commit()
    course_a = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Chapitre A"), "professor_id": professor_a.id})
    course_b = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Chapitre B"), "professor_id": professor_b.id})
    client = build_test_client(db_session, professor_a)

    created = client.post(f"/api/professor/courses/{course_a['id']}/chapters", json={"title": "Intro", "content": "Contenu"})
    forbidden = client.put(f"/api/professor/courses/{course_b['id']}/chapters/999", json={"title": "Nope", "content": "Nope"})

    assert created.status_code == 200
    assert created.json()["title"] == "Intro"
    assert forbidden.status_code == 403


def test_professor_reorders_chapters(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=213, email="prof-reorder@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Reorder"), "professor_id": professor.id})
    client = build_test_client(db_session, professor)
    first = client.post(f"/api/professor/courses/{course['id']}/chapters", json={"title": "A", "content": "A"}).json()
    second = client.post(f"/api/professor/courses/{course['id']}/chapters", json={"title": "B", "content": "B"}).json()

    response = client.post(f"/api/professor/courses/{course['id']}/chapters/reorder", json={"chapter_ids": [second["id"], first["id"]]})

    assert response.status_code == 200
    assert [chapter["id"] for chapter in response.json()] == [second["id"], first["id"]]


def test_professor_quiz_question_validation(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=214, email="prof-quiz@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Quiz validation"), "professor_id": professor.id})
    client = build_test_client(db_session, professor)
    quiz = client.post(f"/api/professor/courses/{course['id']}/quizzes", json={"title": "Quiz", "passing_score": 70}).json()

    one_choice = client.post(f"/api/professor/quizzes/{quiz['id']}/questions", json={"question": "Q", "choices": ["A"], "answer": "A"})
    bad_answer = client.post(f"/api/professor/quizzes/{quiz['id']}/questions", json={"question": "Q", "choices": ["A", "B"], "answer": "C"})

    assert one_choice.status_code == 422
    assert bad_answer.status_code == 422


def test_question_chapter_must_belong_to_same_course(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=215, email="prof-question-chapter@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course_a = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Course A"), "professor_id": professor.id})
    course_b = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Course B"), "professor_id": professor.id})
    client = build_test_client(db_session, professor)
    chapter_b = client.post(f"/api/professor/courses/{course_b['id']}/chapters", json={"title": "B", "content": "B"}).json()
    quiz = client.post(f"/api/professor/courses/{course_a['id']}/quizzes", json={"title": "Quiz"}).json()

    response = client.post(
        f"/api/professor/quizzes/{quiz['id']}/questions",
        json={"question": "Q", "choices": ["A", "B"], "answer": "A", "chapter_id": chapter_b["id"]},
    )

    assert response.status_code == 422


def test_professor_cannot_modify_other_professor_quiz(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor_a = UserProfile(id=216, email="prof-quiz-a@example.com", full_name="Prof A", role="professor", status="active")
    professor_b = UserProfile(id=217, email="prof-quiz-b@example.com", full_name="Prof B", role="professor", status="active")
    db_session.add_all([professor_a, professor_b])
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Quiz other"), "professor_id": professor_b.id})
    quiz = Quiz(course_id=course["id"], title="Quiz")
    db_session.add(quiz)
    db_session.commit()
    db_session.refresh(quiz)
    client = build_test_client(db_session, professor_a)

    response = client.put(f"/api/professor/quizzes/{quiz.id}", json={"title": "Hack"})

    assert response.status_code == 403


def test_professor_publishes_complete_course_and_incomplete_is_refused(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=218, email="prof-publish@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    complete = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Complete"), "professor_id": professor.id})
    incomplete = course_service.create_course(db_session, {"title": "Incomplete", "subject_id": subject.id, "professor_id": professor.id, "published": False})
    client = build_test_client(db_session, professor)
    client.post(f"/api/professor/courses/{complete['id']}/chapters", json={"title": "Intro", "content": "Contenu"})

    published = client.post(f"/api/professor/courses/{complete['id']}/publish")
    refused = client.post(f"/api/professor/courses/{incomplete['id']}/publish")

    assert published.status_code == 200
    assert published.json()["published"] is True
    assert refused.status_code == 400


def test_student_public_courses_hide_unpublished_professor_course(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=219, email="prof-public@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Invisible draft"), "professor_id": professor.id, "published": False})

    public_courses = course_service.get_courses(db_session)

    assert course["id"] not in [item["id"] for item in public_courses]


def test_professor_non_pdf_upload_is_rejected(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=220, email="prof-upload@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Upload"), "professor_id": professor.id})
    client = build_test_client(db_session, professor)

    response = client.post(
        f"/api/professor/courses/{course['id']}/document",
        files={"file": ("bad.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 400


def test_professor_pdf_upload_requires_course_ownership(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor_a = UserProfile(id=221, email="prof-upload-a@example.com", full_name="Prof A", role="professor", status="active")
    professor_b = UserProfile(id=222, email="prof-upload-b@example.com", full_name="Prof B", role="professor", status="active")
    db_session.add_all([professor_a, professor_b])
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Upload other"), "professor_id": professor_b.id})
    client = build_test_client(db_session, professor_a)

    response = client.post(
        f"/api/professor/courses/{course['id']}/document",
        files={"file": ("support.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 403


def test_professor_analytics_and_students_are_course_scoped(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=223, email="prof-analytics@example.com", full_name="Professor", role="professor", status="active")
    student = UserProfile(id=224, email="student-analytics@example.com", full_name="Student", role="student", status="active")
    db_session.add_all([professor, student])
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Analytics"), "professor_id": professor.id})
    db_session.add_all([
        CourseProgress(user_id=student.id, course_id=course["id"], progress=80, chapters=[]),
        QuizResult(user_id=student.id, course_id=course["id"], score=90, correct=9, total=10),
    ])
    db_session.commit()
    client = build_test_client(db_session, professor)

    students = client.get(f"/api/professor/courses/{course['id']}/students")
    analytics = client.get(f"/api/professor/courses/{course['id']}/analytics")

    assert students.status_code == 200
    assert students.json()[0]["student_id"] == student.id
    assert analytics.status_code == 200
    assert analytics.json()["active_students"] == 1
    assert analytics.json()["average_score"] == 90


def test_eight_existing_ai_courses_keep_ids_and_professor_null(db_session):
    course_service.seed_courses_from_mock(db_session)
    courses = course_service.get_courses(db_session, include_unpublished=True)

    assert [course["id"] for course in courses if course["id"] <= 8] == list(range(1, 9))
    assert all(course["professor_id"] is None for course in courses if course["id"] <= 8)


def test_non_ai_course_does_not_receive_ai_default_content(db_session):
    subject = catalog_service.create_subject(db_session, {"name": "Informatique Test", "slug": "francais-test", "active": True})
    professor = UserProfile(id=230, email="prof-non-ai@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course = course_service.create_course(db_session, {
        "title": "Les figures de style",
        "summary": "",
        "description": "",
        "subject_id": subject["id"],
        "professor_id": professor.id,
        "published": False,
        "chapters": [{"title": "Analyse littéraire", "content": "", "status": "active", "openable": True}],
    })

    payload = str(course_service.get_course_detail(db_session, course["id"], include_unpublished=True)).lower()

    assert "introduction ia" not in payload
    assert "prediction" not in payload
    assert "automatisation" not in payload


def test_structured_content_valid_is_saved_and_invalid_is_rejected(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=231, email="prof-structured@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Structured"), "professor_id": professor.id})
    client = build_test_client(db_session, professor)
    chapter = client.post(f"/api/professor/courses/{course['id']}/chapters", json={"title": "Bloc", "content": "Texte"}).json()

    valid = client.put(
        f"/api/professor/courses/{course['id']}/chapters/{chapter['id']}",
        json={"structured_content": [{"type": "definition", "title": "Terme", "content": "Definition courte"}]},
    )
    invalid = client.put(
        f"/api/professor/courses/{course['id']}/chapters/{chapter['id']}",
        json={"structured_content": [{"type": "bullet_list", "content": "pas une liste"}]},
    )

    assert valid.status_code == 200
    assert valid.json()["structured_content"][0]["type"] == "definition"
    assert invalid.status_code == 422


def test_student_cannot_modify_structured_content(db_session):
    student = UserProfile(id=232, email="student-structured@example.com", full_name="Student", role="student", status="active")
    client = build_test_client(db_session, student)

    response = client.put("/api/professor/courses/1/chapters/1", json={"structured_content": []})

    assert response.status_code == 403


def test_pdf_import_preserves_pages_and_stays_draft(monkeypatch, tmp_path, db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=233, email="prof-import@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course_data = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Les figures de style"), "professor_id": professor.id, "published": True})
    course = course_service.get_course_model(db_session, course_data["id"])
    docs_dir = tmp_path / "courses"
    docs_dir.mkdir()
    pdf_path = docs_dir / "python.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    course.pdf_url = "/docs/courses/python.pdf"
    db_session.commit()

    monkeypatch.setattr(content_import_service, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(
        content_import_service,
        "extract_pdf_pages",
        lambda path: [
            {"page_number": 1, "text": "La analyse littéraire permet de transformer une idee en texte."},
            {"page_number": 2, "text": "Les erreurs de syntaxe, semantique et execution doivent etre distinguees."},
            {"page_number": 3, "text": "français est portable, gratuit, lisible, oriente objet et extensible."},
        ],
    )
    client = build_test_client(db_session, professor)

    response = client.post(f"/api/professor/courses/{course.id}/content/import-from-pdf")
    detail = course_service.get_course_detail(db_session, course.id, include_unpublished=True)

    assert response.status_code == 200
    assert response.json()["status"] == "ready_for_review"
    assert detail["published"] is False
    assert detail["status"] == "draft"
    assert detail["chapters"][0]["structured_content"][0]["source_page_start"] == 1


def test_pdf_import_fallback_works_when_groq_is_unavailable(monkeypatch, tmp_path, db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=234, email="prof-fallback@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course_data = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Support simple"), "professor_id": professor.id})
    course = course_service.get_course_model(db_session, course_data["id"])
    docs_dir = tmp_path / "courses"
    docs_dir.mkdir()
    (docs_dir / "support.pdf").write_bytes(b"%PDF-1.4\n")
    course.pdf_url = "/docs/courses/support.pdf"
    db_session.commit()
    monkeypatch.setattr(content_import_service, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(content_import_service, "extract_pdf_pages", lambda path: [{"page_number": 1, "text": "Chapitre 1 Introduction. Contenu simple du document."}])

    response = build_test_client(db_session, professor).post(f"/api/professor/courses/{course.id}/content/import-from-pdf")

    assert response.status_code == 200
    assert response.json()["generated_from_pdf"] is True


def test_mermaid_block_invalid_is_accepted_as_display_fallback(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=235, email="prof-mermaid@example.com", full_name="Professor", role="professor", status="active")
    db_session.add(professor)
    db_session.commit()
    course = course_service.create_course(db_session, {**make_professor_payload(subject.id, "Mermaid"), "professor_id": professor.id})
    client = build_test_client(db_session, professor)
    chapter = client.post(f"/api/professor/courses/{course['id']}/chapters", json={"title": "Diagramme", "content": "Texte"}).json()

    response = client.put(
        f"/api/professor/courses/{course['id']}/chapters/{chapter['id']}",
        json={"structured_content": [{"type": "diagram", "diagram_type": "mermaid", "title": "Schema", "content": "not mermaid"}]},
    )

    assert response.status_code == 200
    assert response.json()["structured_content"][0]["content"] == "not mermaid"


def test_old_text_chapters_remain_compatible(db_session):
    course_service.seed_courses_from_mock(db_session)
    detail = course_service.get_course_detail(db_session, 1)

    assert detail["chapters"][0]["title"]
    assert "structured_content" in detail["chapters"][0]


def make_phase6_users(db_session):
    professor = UserProfile(id=701, email="phase6-prof@example.com", full_name="Prof Phase6", role="professor", status="active")
    other_professor = UserProfile(id=702, email="phase6-other-prof@example.com", full_name="Other Prof", role="professor", status="active")
    student = UserProfile(id=703, email="phase6-student@example.com", full_name="Student Phase6", role="student", status="active")
    db_session.add_all([professor, other_professor, student])
    db_session.commit()
    return professor, other_professor, student


def make_phase6_course(db_session, professor: UserProfile) -> dict:
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    return course_service.create_course(db_session, {
        **make_professor_payload(subject.id, "Les figures de style Phase6"),
        "professor_id": professor.id,
        "published": True,
        "chapters": [
            {
                "title": "Analyse littéraire",
                "content": "Comprendre la analyse littéraire comme une traduction d'une idee en instructions executables.",
                "status": "active",
                "openable": True,
                "structured_content": [{"type": "definition", "title": "Analyse littéraire", "content": "Une figure de style consiste a decrire precisement a un ordinateur ce qu'il doit faire."}],
            },
            {
                "title": "Erreurs de syntaxe",
                "content": "Identifier les erreurs de syntaxe qui empechent souvent l'execution d'un texte.",
                "status": "locked",
                "openable": False,
                "structured_content": [{"type": "definition", "title": "Erreur de compréhension", "content": "Une erreur de compréhension apparait lorsque le code ne respecte pas les regles d'ecriture du langage."}],
            },
        ],
    })


def make_phase6_assessment_payload(course: dict, classroom_id: int | None = None) -> dict:
    return {
        "title": "Evaluation initiale francais",
        "classroom_id": classroom_id,
        "course_id": course["id"],
        "subject_id": course["subject_id"],
        "assessment_type": "initial",
        "status": "draft",
        "max_attempts": 1,
        "questions": [
            {
                "chapter_id": course["chapters"][0]["id"],
                "question": "Quel est l'objectif principal d'une figure de style ",
                "choices": ["Renforcer le sens", "Ignorer les erreurs", "Dessiner uniquement", "Changer de sujet"],
                "correct_answer": "Renforcer le sens",
                "explanation": "Analyser une figure consiste à écrire des instructions exécutables.",
                "points": 1,
                "active": True,
            },
            {
                "chapter_id": course["chapters"][1]["id"],
                "question": "Une erreur de compréhension indique quoi ",
                "choices": ["Une idée mal justifiée", "Une réponse parfaite", "Un fichier image", "Une notification"],
                "correct_answer": "Une idée mal justifiée",
                "explanation": "La justification doit s'appuyer sur des indices du texte.",
                "points": 1,
                "active": True,
            },
        ],
    }


def test_phase6_professor_creates_classroom_and_adds_student(db_session):
    professor, _, student = make_phase6_users(db_session)
    client = build_test_client(db_session, professor)

    classroom_response = client.post("/api/professor/classrooms", json={"name": "Francais 2026", "academic_year": "2026"})
    add_response = client.post(
        f"/api/professor/classrooms/{classroom_response.json()['id']}/students",
        json={"email": student.email},
    )

    assert classroom_response.status_code == 200
    assert add_response.status_code == 200
    assert add_response.json()["student_id"] == student.id


def test_phase6_professor_cannot_manage_other_classroom(db_session):
    professor, other_professor, _ = make_phase6_users(db_session)
    classroom = assessment_service.create_classroom(db_session, other_professor, {"name": "Autre classe"})
    client = build_test_client(db_session, professor)

    response = client.get(f"/api/professor/classrooms/{classroom['id']}")

    assert response.status_code == 403


def test_phase6_professor_creates_and_publishes_assessment(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe assessment"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    client = build_test_client(db_session, professor)

    create_response = client.post("/api/professor/assessments", json=make_phase6_assessment_payload(course, classroom["id"]))
    publish_response = client.post(f"/api/professor/assessments/{create_response.json()['id']}/publish")

    assert create_response.status_code == 200
    assert create_response.json()["status"] == "draft"
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    assert publish_response.json()["assigned_student_count"] == 1
    assert db_session.query(Assessment).filter_by(id=create_response.json()["id"]).one().status == "published"
    assert db_session.query(Notification).filter_by(user_id=student.id, type="assessment").count() == 1


def test_phase6_draft_save_does_not_publish_or_assign(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe draft"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    client = build_test_client(db_session, professor)

    response = client.post("/api/professor/assessments", json=make_phase6_assessment_payload(course, classroom["id"]))

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert db_session.query(Assessment).filter_by(id=response.json()["id"]).one().status == "draft"
    assert db_session.query(Notification).filter_by(user_id=student.id, type="assessment").count() == 0


def test_phase6_repeated_publish_is_idempotent(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe idempotente"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    client = build_test_client(db_session, professor)

    first = client.post(f"/api/professor/assessments/{assessment['id']}/publish")
    second = client.post(f"/api/professor/assessments/{assessment['id']}/publish")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["assigned_student_count"] == 1
    assert db_session.query(AssessmentAssignment).filter_by(assessment_id=assessment["id"], student_id=student.id).count() == 1
    assert db_session.query(Notification).filter_by(user_id=student.id, title="Nouveau test publie").count() == 1


def test_phase6_publish_requires_non_empty_classroom(db_session):
    professor, _, _ = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe vide"})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))

    response = build_test_client(db_session, professor).post(f"/api/professor/assessments/{assessment['id']}/publish")

    assert response.status_code == 422
    assert "aucun etudiant actif" in response.json()["detail"]
    assert db_session.query(Assessment).filter_by(id=assessment["id"]).one().status == "draft"


def test_phase6_student_visibility_depends_on_assignment(db_session):
    professor, _, student = make_phase6_users(db_session)
    other_student = UserProfile(id=704, email="phase6-not-assigned@example.com", full_name="Not Assigned", role="student", status="active")
    db_session.add(other_student)
    db_session.commit()
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe visible assigned"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])

    assigned_response = build_test_client(db_session, student).get("/api/assessments")
    other_response = build_test_client(db_session, other_student).get("/api/assessments")

    assert assigned_response.status_code == 200
    assert [item["id"] for item in assigned_response.json()] == [assessment["id"]]
    assert other_response.status_code == 200
    assert other_response.json() == []


def test_phase6_future_publication_stays_scheduled_on_save(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe scheduled"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    future_payload = {
        **make_phase6_assessment_payload(course, classroom["id"]),
        "status": "scheduled",
        "publication_at": "2099-01-01T10:00:00",
    }

    response = build_test_client(db_session, professor).post("/api/professor/assessments", json=future_payload)

    assert response.status_code == 200
    assert response.json()["status"] == "scheduled"
    assert db_session.query(Assessment).filter_by(id=response.json()["id"]).one().status == "scheduled"
    assert db_session.query(AssessmentAssignment).filter_by(assessment_id=response.json()["id"]).count() == 0


def test_phase6_professor_can_propose_questions_for_saved_draft(db_session):
    professor, _, _ = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    client = build_test_client(db_session, professor)

    create_response = client.post("/api/professor/assessments", json=make_phase6_assessment_payload(course))
    assessment_id = create_response.json()["id"]
    propose_response = client.post(
        f"/api/professor/assessments/{assessment_id}/propose-questions",
        json={"count": 5},
    )
    body = propose_response.json()

    assert create_response.status_code == 200
    assert assessment_id
    assert propose_response.status_code == 200
    assert body["assessment_id"] == assessment_id
    assert body["requires_professor_validation"] is True
    assert len(body["questions"]) >= 1
    assert body["questions"][0]["chapter_id"] == course["chapters"][0]["id"]
    assert "definition" in body["questions"][0]["question"].lower() or "figure de style" in body["questions"][0]["question"].lower()
    assert len(body["questions"][0]["choices"]) == 4
    assert body["questions"][0]["correct_answer"] in body["questions"][0]["choices"]
    assert "Quel est le point essentiel" not in body["questions"][0]["question"]


def test_phase6_professor_cannot_propose_questions_for_other_assessment(db_session):
    professor, other_professor, _ = make_phase6_users(db_session)
    course = make_phase6_course(db_session, other_professor)
    assessment = assessment_service.create_assessment(db_session, other_professor, make_phase6_assessment_payload(course))
    client = build_test_client(db_session, professor)

    response = client.post(f"/api/professor/assessments/{assessment['id']}/propose-questions", json={"count": 5})

    assert response.status_code == 403


def test_phase6_french_structured_content_generates_quality_questions(db_session):
    professor, _, _ = make_phase6_users(db_session)
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    course = course_service.create_course(db_session, {
        **make_professor_payload(subject.id, "Les figures de style qualite"),
        "professor_id": professor.id,
        "published": True,
        "chapters": [
            {
                "title": "Antigone et le conflit",
                "content": "Antigone s'oppose a Creon autour de la loi, du devoir familial et de la responsabilite.",
                "structured_content": [{"type": "definition", "title": "Conflit tragique", "content": "Le conflit oppose Antigone et Creon autour de la loi et du devoir."}],
            },
            {
                "title": "La Boite a merveilles",
                "content": "Sidi Mohammed raconte ses souvenirs d'enfance a la premiere personne dans un quartier de Fes.",
                "structured_content": [{"type": "definition", "title": "Narrateur", "content": "Sidi Mohammed raconte ses souvenirs d'enfance a la premiere personne."}],
            },
            {
                "title": "Le Dernier Jour d'un condamne",
                "content": "Victor Hugo donne la parole au condamne pour denoncer la peine de mort.",
                "structured_content": [{"type": "definition", "title": "Denonciation", "content": "L'oeuvre denonce la peine de mort a travers la voix du condamne."}],
            },
            {
                "title": "Découvrir les figures",
                "content": "La comparaison rapproche deux idées.",
                "structured_content": [{"type": "bullet_list", "title": "Points cles", "content": ["La comparaison rapproche deux éléments avec un outil comparatif.", "La métaphore associe deux réalités sans outil comparatif.", "La personnification attribue une action humaine à une chose."]}],
            },
            {
                "title": "Méthodologie du régional",
                "content": "La methode consiste a lire la consigne, reperer les mots-cles et justifier la reponse par le texte.",
                "structured_content": [{"type": "bullet_list", "title": "Demarche", "content": ["Lire attentivement la consigne.", "Reperer les mots-cles.", "Repondre de facon precise.", "Justifier avec un indice du texte."]}],
            },
        ],
    })
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course))

    response = build_test_client(db_session, professor).post(
        f"/api/professor/assessments/{assessment['id']}/propose-questions",
        json={"count": 5},
    )
    questions = response.json()["questions"]
    joined_text = " ".join([question["question"] + " " + " ".join(question["choices"]) for question in questions])

    assert response.status_code == 200
    assert len(questions) == 5
    assert len({question["question"] for question in questions}) == 5
    assert len({question["chapter_id"] for question in questions}) == 5
    assert all(len(question["choices"]) == 4 for question in questions)
    assert all(question["correct_answer"] in question["choices"] for question in questions)
    assert all(question["explanation"] for question in questions)
    assert "Quel est le point essentiel du chapitre" not in joined_text
    assert "Ignorer les objectifs" not in joined_text
    assert "Comprendre le chapitre" not in joined_text


def test_phase6_student_sees_only_assigned_published_assessments(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe visible"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    draft = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, draft["id"])
    assessment_service.create_assessment(db_session, professor, {**make_phase6_assessment_payload(course), "title": "Brouillon non visible"})
    client = build_test_client(db_session, student)

    response = client.get("/api/assessments")

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Evaluation initiale francais"]


def test_phase6_student_payload_hides_correct_answers_before_submission(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe hide answers"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    client = build_test_client(db_session, student)

    response = client.get(f"/api/assessments/{assessment['id']}")

    assert response.status_code == 200
    assert "correct_answer" not in response.json()["questions"][0]
    assert response.json()["questions"][0]["explanation"] == ""


def test_phase6_backend_scores_attempt_and_blocks_second_submission(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe score"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    client = build_test_client(db_session, student)
    question_ids = [question["id"] for question in assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]]

    response = client.post(
        f"/api/assessments/{assessment['id']}/submit",
        json={"answers": {str(question_ids[0]): "Renforcer le sens", str(question_ids[1]): "Mauvaise réponse"}},
    )
    second_response = client.post(
        f"/api/assessments/{assessment['id']}/submit",
        json={"answers": {str(question_ids[0]): "Renforcer le sens", str(question_ids[1]): "Une idée mal justifiée"}},
    )

    assert response.status_code == 200
    assert response.json()["percentage"] == 50
    assert second_response.status_code == 409


def weakness_prediction(status: str, competence: str = "Figures de style", events_used: int = 3) -> dict:
    return {
        "overall": {"status": "analyse_disponible" if status != "non_evalue" else "donnees_insuffisantes"},
        "events_used": events_used,
        "competencies": [
            {
                "competence": competence,
                "status": status,
                "score_percentage": 25 if status == "faible" else 55 if status == "a_renforcer" else 92 if status == "maitrise" else None,
                "method": "test_student_weakness_model",
            }
        ],
    }


def test_phase6_remediation_plan_is_limited_to_course(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))

    report = assessment_service.submit_assessment(
        db_session,
        student,
        assessment["id"],
        {"answers": {str(question["id"]): "Mauvaise réponse" for question in questions}},
    )
    plan = assessment_service.get_remediation_plan(db_session, student, report["remediation_plan_id"])

    assert plan["course_id"] == course["id"]
    assert all(item["chapter_id"] in {chapter["id"] for chapter in course["chapters"]} for item in plan["items"])


def test_automatic_remediation_uses_weakness_model_service(db_session, monkeypatch):
    calls = {"count": 0}
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation model"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]

    def fake_predict(db, user):
        calls["count"] += 1
        return weakness_prediction("faible")

    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", fake_predict)

    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise reponse" for question in questions}})

    assert calls["count"] == 1
    assert report["remediation_plan_id"]


def test_automatic_remediation_generates_lessons_without_professor_approval(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation auto"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))

    report = assessment_service.submit_assessment(
        db_session,
        student,
        assessment["id"],
        {"answers": {str(question["id"]): "Mauvaise reponse" for question in questions}},
    )
    lessons = personalized_lesson_service.list_lessons_for_plan(db_session, student, report["remediation_plan_id"])
    professor_lessons = personalized_lesson_service.list_professor_lessons(db_session, professor, {})

    assert lessons
    assert all(lesson.status == "ready" for lesson in lessons)
    assert {lesson.id for lesson in lessons}.issubset({row["id"] for row in professor_lessons})


def test_automatic_remediation_reinforce_status_triggers_plan(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation reinforce"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("a_renforcer"))

    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise reponse" for question in questions}})

    assert report["remediation_plan_id"]


def test_automatic_remediation_does_not_duplicate_active_skill_plan(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation dedupe"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    first_payload = make_phase6_assessment_payload(course, classroom["id"])
    second_payload = make_phase6_assessment_payload(course, classroom["id"])
    first_payload["title"] = "Premier test"
    second_payload["title"] = "Deuxieme test"
    first = assessment_service.create_assessment(db_session, professor, first_payload)
    second = assessment_service.create_assessment(db_session, professor, second_payload)
    assessment_service.publish_assessment(db_session, professor, first["id"])
    assessment_service.publish_assessment(db_session, professor, second["id"])
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))

    for assessment in [first, second]:
        questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
        assessment_service.submit_assessment(
            db_session,
            student,
            assessment["id"],
            {"answers": {str(question["id"]): "Mauvaise reponse" for question in questions}},
        )

    assert db_session.query(RemediationPlan).filter_by(student_id=student.id, course_id=course["id"]).count() == 1


def test_mastered_attempt_does_not_create_remediation(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation mastered"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("maitrise"))

    report = assessment_service.submit_assessment(
        db_session,
        student,
        assessment["id"],
        {
            "answers": {
                str(questions[0]["id"]): "Renforcer le sens",
                str(questions[1]["id"]): "Une idée mal justifiée",
            }
        },
    )

    assert report.get("remediation_plan_id") is None
    assert db_session.query(RemediationPlan).filter_by(student_id=student.id, course_id=course["id"]).count() == 0


def test_non_evaluated_attempt_does_not_create_remediation(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation non evalue"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("non_evalue", events_used=0))

    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise reponse" for question in questions}})

    assert report.get("remediation_plan_id") is None
    assert db_session.query(RemediationPlan).filter_by(student_id=student.id, course_id=course["id"]).count() == 0


def test_personalized_assessment_reevaluates_source_plan_without_loop(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe remediation reevaluate"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))
    initial = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise reponse" for question in questions}})
    personalized = assessment_service.create_personalized_assessment(db_session, student, initial["remediation_plan_id"])
    personalized_questions = assessment_service.get_student_assessment(db_session, student, personalized["id"])["questions"]
    before_count = db_session.query(RemediationPlan).filter_by(student_id=student.id, course_id=course["id"]).count()

    assessment_service.submit_assessment(
        db_session,
        student,
        personalized["id"],
        {"answers": {str(question["id"]): "Mauvaise reponse" for question in personalized_questions}},
    )
    plan = db_session.get(RemediationPlan, initial["remediation_plan_id"])

    assert db_session.query(RemediationPlan).filter_by(student_id=student.id, course_id=course["id"]).count() == before_count
    assert plan.status == "to_reevaluate"


def test_phase6_personalized_assessment_is_assigned_only_to_student(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    other_student = UserProfile(id=704, email="phase6-other-student@example.com", full_name="Other Student", role="student", status="active")
    db_session.add(other_student)
    db_session.commit()
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe personalized"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))
    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise réponse" for question in questions}})

    personalized = assessment_service.create_personalized_assessment(db_session, student, report["remediation_plan_id"])
    other_client = build_test_client(db_session, other_student)

    assert personalized["assessment_type"] == "personalized"
    assert other_client.get(f"/api/assessments/{personalized['id']}").status_code == 404


def test_phase6_comparison_uses_real_attempt_scores(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe compare"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))
    initial = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise réponse" for question in questions}})
    personalized = assessment_service.create_personalized_assessment(db_session, student, initial["remediation_plan_id"])
    personalized_questions = assessment_service.get_student_assessment(db_session, student, personalized["id"])["questions"]
    improved = assessment_service.submit_assessment(
        db_session,
        student,
        personalized["id"],
        {"answers": {str(question["id"]): question["choices"][0] for question in personalized_questions}},
    )

    comparison = assessment_service.compare_attempts(db_session, student, initial["attempt_id"], improved["attempt_id"])

    assert comparison["initial_score"] == 0
    assert comparison["personalized_score"] >= comparison["initial_score"]
    assert comparison["variation_points"] >= 0


def test_phase6_role_protection_on_professor_routes(db_session):
    _, _, student = make_phase6_users(db_session)
    client = build_test_client(db_session, student)

    response = client.get("/api/professor/assessments")

    assert response.status_code == 403


def test_phase6_course_ids_are_preserved_after_new_models(db_session):
    course_service.seed_courses_from_mock(db_session)

    ids = [course.id for course in db_session.query(Course).order_by(Course.id).all()]

    assert ids[:8] == list(range(1, 9))


def make_phase7_plan(db_session):
    professor, other_professor, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe phase 7"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    original_predict = assessment_service.student_weakness_model_service.predict_student_weaknesses
    assessment_service.student_weakness_model_service.predict_student_weaknesses = lambda db, user: weakness_prediction("faible")
    try:
        report = assessment_service.submit_assessment(
            db_session,
            student,
            assessment["id"],
            {"answers": {str(question["id"]): "Mauvaise reponse" for question in questions}},
        )
    finally:
        assessment_service.student_weakness_model_service.predict_student_weaknesses = original_predict
    return professor, other_professor, student, course, assessment, report


def test_phase7_creates_personalized_lessons_from_weak_chapters(db_session):
    _, _, student, course, _, report = make_phase7_plan(db_session)

    response = build_test_client(db_session, student).post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate")
    body = response.json()

    assert response.status_code == 200
    assert len(body["lessons"]) == 2
    assert db_session.query(PersonalizedLesson).filter_by(remediation_plan_id=report["remediation_plan_id"]).count() == 2
    assert {lesson["course_id"] for lesson in body["lessons"]} == {course["id"]}
    assert all(lesson["structured_content"] for lesson in body["lessons"])


def test_phase7_generation_is_idempotent_for_same_plan(db_session):
    _, _, student, _, _, report = make_phase7_plan(db_session)
    client = build_test_client(db_session, student)

    first = client.post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate")
    second = client.post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first.json()["lessons"]) == len(second.json()["lessons"])
    assert db_session.query(PersonalizedLesson).filter_by(remediation_plan_id=report["remediation_plan_id"]).count() == len(first.json()["lessons"])


def test_phase7_student_can_read_and_complete_own_lesson(db_session):
    _, _, student, _, _, report = make_phase7_plan(db_session)
    client = build_test_client(db_session, student)
    lesson = client.post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate").json()["lessons"][0]

    detail = client.get(f"/api/personalized-lessons/{lesson['id']}")
    completed = client.put(f"/api/personalized-lessons/{lesson['id']}/complete")

    assert detail.status_code == 200
    assert detail.json()["id"] == lesson["id"]
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_phase7_student_cannot_read_other_student_lesson(db_session):
    _, _, student, _, _, report = make_phase7_plan(db_session)
    other_student = UserProfile(id=950, email="phase7-other@example.com", full_name="Other", role="student", status="active")
    db_session.add(other_student)
    db_session.commit()
    lesson = build_test_client(db_session, student).post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate").json()["lessons"][0]

    response = build_test_client(db_session, other_student).get(f"/api/personalized-lessons/{lesson['id']}")

    assert response.status_code == 403


def test_phase7_professor_sees_only_own_lessons_and_can_approve(db_session):
    professor, other_professor, student, _, _, report = make_phase7_plan(db_session)
    lesson = build_test_client(db_session, student).post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate").json()["lessons"][0]

    own_response = build_test_client(db_session, professor).get("/api/professor/remediation/lessons")
    other_response = build_test_client(db_session, other_professor).get("/api/professor/remediation/lessons")
    approve_response = build_test_client(db_session, professor).put(f"/api/professor/personalized-lessons/{lesson['id']}/approve")

    assert own_response.status_code == 200
    assert lesson["id"] in [item["id"] for item in own_response.json()]
    assert other_response.status_code == 200
    assert other_response.json() == []
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"


def test_phase7_knowledge_check_is_corrected_backend_side(db_session):
    _, _, student, _, _, report = make_phase7_plan(db_session)
    client = build_test_client(db_session, student)
    lesson = client.post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate").json()["lessons"][0]
    check = next(block["content"] for block in lesson["structured_content"] if block["type"] == "knowledge_check")

    response = client.post(f"/api/personalized-lessons/{lesson['id']}/knowledge-check/submit", json={"answer": check["answer"]})

    assert response.status_code == 200
    assert response.json()["correct"] is True


def test_phase7_deterministic_fallback_when_groq_fails(db_session, monkeypatch):
    _, _, student, _, _, report = make_phase7_plan(db_session)
    monkeypatch.setattr(personalized_lesson_service, "improve_lesson_with_groq", lambda payload: None)

    response = build_test_client(db_session, student).post(
        f"/api/remediation/{report['remediation_plan_id']}/lessons/generate",
        json={"use_groq": True},
    )

    assert response.status_code == 200
    assert all(lesson["generation_method"] == "deterministic" for lesson in response.json()["lessons"])


def test_phase7_invalid_structured_content_is_rejected(db_session):
    professor, _, student, _, _, report = make_phase7_plan(db_session)
    lesson = build_test_client(db_session, student).post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate").json()["lessons"][0]

    response = build_test_client(db_session, professor).put(
        f"/api/professor/personalized-lessons/{lesson['id']}",
        json={"structured_content": "invalid"},
    )

    assert response.status_code == 422


def test_phase8_accuracy_completion_and_unanswered_are_calculated_correctly(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    payload = make_phase6_assessment_payload(course)
    payload["questions"].append({
        "chapter_id": course["chapters"][1]["id"],
        "question": "Quelle pratique aide a corriger une erreur ",
        "choices": ["Lire le message", "Ignorer le probleme", "Fermer le cours", "Changer de compte"],
        "correct_answer": "Lire le message",
        "explanation": "Lire le message aide a comprendre l'origine de l'erreur.",
        "points": 1,
        "active": True,
    })
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe phase8 metrics"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    payload["classroom_id"] = classroom["id"]
    assessment = assessment_service.create_assessment(db_session, professor, payload)
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]

    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {
        "answers": {
            str(questions[0]["id"]): "Renforcer le sens",
            str(questions[1]["id"]): "Mauvaise reponse",
        },
        "time_spent_seconds": {
            str(questions[0]["id"]): 10,
            str(questions[1]["id"]): 40,
            str(questions[2]["id"]): 100,
        },
    })
    detailed = assessment_service.get_detailed_attempt_report(db_session, student, report["attempt_id"])
    metrics = detailed["global_metrics"]

    assert metrics["total_questions"] == 3
    assert metrics["answered_questions"] == 2
    assert metrics["correct_answers"] == 1
    assert metrics["incorrect_answers"] == 1
    assert metrics["unanswered_questions"] == 1
    assert metrics["accuracy"] == 50
    assert round(metrics["completion_rate"], 2) == 66.67
    assert round(metrics["percentage"], 2) == 33.33
    assert len(detailed["unanswered_questions"]) == 1


def test_phase8_negative_time_is_rejected_and_does_not_affect_scoring(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe phase8 time"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    question = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"][0]

    response = build_test_client(db_session, student).post(
        f"/api/assessments/{assessment['id']}/submit",
        json={"answers": {str(question["id"]): question["choices"][0]}, "time_spent_seconds": {str(question["id"]): -5}},
    )

    assert response.status_code == 422
    assert "negatif" in response.json()["detail"]


def test_phase8_slow_questions_require_three_valid_times(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    payload = make_phase6_assessment_payload(course)
    payload["questions"].append({
        "chapter_id": course["chapters"][1]["id"],
        "question": "Comment identifier une erreur ",
        "choices": ["Observer le message", "Ignorer", "Effacer tout", "Changer de langue"],
        "correct_answer": "Observer le message",
        "explanation": "Le message guide la correction.",
        "points": 1,
        "active": True,
    })
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe phase8 slow"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    payload["classroom_id"] = classroom["id"]
    assessment = assessment_service.create_assessment(db_session, professor, payload)
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]

    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {
        "answers": {str(question["id"]): question["choices"][0] for question in questions},
        "time_spent_seconds": {str(questions[0]["id"]): 10, str(questions[1]["id"]): 12, str(questions[2]["id"]): 40},
    })
    detailed = assessment_service.get_detailed_attempt_report(db_session, student, report["attempt_id"])

    assert detailed["global_metrics"]["average_time_per_question"] == 20.67
    assert [item["question_id"] for item in detailed["slow_questions"]] == [questions[2]["id"]]


def test_phase8_old_attempt_without_time_keeps_time_unavailable(db_session):
    professor, _, student, _, _, report = make_phase7_plan(db_session)

    detailed = assessment_service.get_detailed_attempt_report(db_session, student, report["attempt_id"])

    assert detailed["global_metrics"]["average_time_per_question"] is None
    assert detailed["global_metrics"]["average_time_per_question_label"] == "Non disponible"
    assert detailed["slow_questions"] == []


def test_phase8_detailed_report_ownership_student_and_professor(db_session):
    professor, other_professor, student, _, _, report = make_phase7_plan(db_session)
    other_student = UserProfile(id=980, email="phase8-other@example.com", full_name="Other", role="student", status="active")
    db_session.add(other_student)
    db_session.commit()

    student_response = build_test_client(db_session, student).get(f"/api/assessment-results/{report['attempt_id']}/detailed")
    other_student_response = build_test_client(db_session, other_student).get(f"/api/assessment-results/{report['attempt_id']}/detailed")
    professor_response = build_test_client(db_session, professor).get(f"/api/assessment-results/{report['attempt_id']}/detailed")
    other_professor_response = build_test_client(db_session, other_professor).get(f"/api/assessment-results/{report['attempt_id']}/detailed")

    assert student_response.status_code == 200
    assert other_student_response.status_code == 403
    assert professor_response.status_code == 200
    assert other_professor_response.status_code == 403


def test_phase8_professor_analytics_ignore_non_participants_in_average(db_session):
    professor, _, student = make_phase6_users(db_session)
    absent = UserProfile(id=981, email="phase8-absent@example.com", full_name="Absent", role="student", status="active")
    db_session.add(absent)
    db_session.commit()
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe phase8 analytics"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": absent.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): question["choices"][0] for question in questions}})

    analytics = assessment_service.get_professor_assessment_results(db_session, professor, assessment["id"])["analytics"]

    assert analytics["assigned_students"] == 2
    assert analytics["completed_students"] == 1
    assert analytics["average_score"] == 100


def test_phase8_detailed_comparison_marks_missing_final_skill_not_evaluated(db_session):
    professor, _, student, course, assessment, initial = make_phase7_plan(db_session)
    source_assessment = db_session.get(Assessment, assessment["id"])
    skill_a = assessment_service.ensure_skill_for_chapter(db_session, source_assessment.subject_id, source_assessment.course_id, source_assessment.questions[0].chapter)
    skill_b = assessment_service.ensure_skill_for_chapter(db_session, source_assessment.subject_id, source_assessment.course_id, source_assessment.questions[1].chapter)
    source_assessment.questions[0].skill_id = skill_a.id
    source_assessment.questions[1].skill_id = skill_b.id
    db_session.commit()
    personalized = assessment_service.create_personalized_assessment(db_session, student, initial["remediation_plan_id"])
    personalized_model = db_session.get(Assessment, personalized["id"])
    personalized_model.questions[1].active = False
    db_session.commit()
    personalized_questions = assessment_service.get_student_assessment(db_session, student, personalized["id"])["questions"]
    assessment_service.submit_assessment(
        db_session,
        student,
        personalized["id"],
        {"answers": {str(personalized_questions[0]["id"]): personalized_questions[0]["choices"][0]}},
    )

    comparison = assessment_service.compare_latest_for_plan_detailed(db_session, student, initial["remediation_plan_id"])

    assert comparison["available"] is True
    assert "score_delta" in comparison
    assert any(item["final_status"] == "Non evaluee dans le test personnalise" for item in comparison["skill_comparison"])


def test_phase8_next_action_changes_after_lessons_complete(db_session):
    _, _, student, _, _, report = make_phase7_plan(db_session)
    client = build_test_client(db_session, student)
    lessons = client.post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate").json()["lessons"]

    before = client.get(f"/api/assessment-results/{report['attempt_id']}/detailed").json()
    for lesson in lessons:
        client.put(f"/api/personalized-lessons/{lesson['id']}/complete")
    after = client.get(f"/api/assessment-results/{report['attempt_id']}/detailed").json()

    assert before["next_action"]["type"] in {"review_chapter", "start_lesson", "continue_remediation"}
    assert after["next_action"]["type"] in {"knowledge_check", "personalized_assessment"}


def make_phase9_plan(db_session):
    professor, other_professor, student = make_phase6_users(db_session)
    other_student = UserProfile(id=9901, email="phase9-other-student@example.com", full_name="Other Phase9", role="student", status="active")
    db_session.add(other_student)
    db_session.commit()
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe phase 9"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    source_assessment = db_session.get(Assessment, assessment["id"])
    skill_a = assessment_service.ensure_skill_for_chapter(db_session, source_assessment.subject_id, source_assessment.course_id, source_assessment.questions[0].chapter)
    skill_b = assessment_service.ensure_skill_for_chapter(db_session, source_assessment.subject_id, source_assessment.course_id, source_assessment.questions[1].chapter)
    source_assessment.questions[0].skill_id = skill_a.id
    source_assessment.questions[1].skill_id = skill_b.id
    db_session.commit()
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    original_predict = assessment_service.student_weakness_model_service.predict_student_weaknesses
    assessment_service.student_weakness_model_service.predict_student_weaknesses = lambda db, user: weakness_prediction("faible", skill_b.name)
    try:
        report = assessment_service.submit_assessment(
            db_session,
            student,
            assessment["id"],
            {"answers": {str(questions[0]["id"]): questions[0]["choices"][0], str(questions[1]["id"]): "Mauvaise reponse"}},
        )
    finally:
        assessment_service.student_weakness_model_service.predict_student_weaknesses = original_predict
    return professor, other_professor, student, other_student, course, assessment, report


def test_phase9_personalized_assessment_targets_only_weak_skills_and_uses_new_questions(db_session):
    professor, _, student, _, _, assessment, report = make_phase9_plan(db_session)

    personalized = assessment_service.create_personalized_assessment(db_session, student, report["remediation_plan_id"])
    original_questions = assessment_service.get_professor_assessment(db_session, professor, assessment["id"])["questions"]
    personalized_questions = personalized["questions"]

    assert personalized["status"] == "published"
    assert personalized_questions
    assert {question["skill_id"] for question in personalized_questions} == {original_questions[1]["skill_id"]}
    assert all(question["question"] != original_questions[1]["question"] for question in personalized_questions)
    assert all(question["choices"] != original_questions[1]["choices"] for question in personalized_questions)
    assert all(question["source_question_id"] == original_questions[1]["id"] for question in personalized_questions)
    assert all(question["generation_method"] == "deterministic" for question in personalized_questions)
    assert all(question["adaptation_reason"] for question in personalized_questions)
    assert all((question["similarity_score"] or 0) < assessment_service.PERSONALIZED_SIMILARITY_THRESHOLD for question in personalized_questions)


def test_phase9_antidup_rejects_exact_question_and_same_choices(db_session):
    professor, _, student, _, _, assessment, report = make_phase9_plan(db_session)
    personalized = assessment_service.create_personalized_assessment(db_session, student, report["remediation_plan_id"], {"validation_mode": "professor"})
    source_question = assessment_service.get_professor_assessment(db_session, professor, assessment["id"])["questions"][1]

    response = build_test_client(db_session, professor).post(
        f"/api/professor/personalized-assessments/{personalized['id']}/questions",
        json={
            "question": source_question["question"],
            "choices": source_question["choices"],
            "correct_answer": source_question["correct_answer"],
            "explanation": source_question["explanation"],
            "chapter_id": source_question["chapter_id"],
            "skill_id": source_question["skill_id"],
        },
    )

    assert response.status_code == 422
    assert "trop proche" in response.json()["detail"]


def test_phase9_course_isolation_and_groq_invalid_falls_back(db_session, monkeypatch):
    _, _, student, _, course, _, report = make_phase9_plan(db_session)
    monkeypatch.setattr(assessment_service, "generate_personalized_question_with_groq", lambda *args, **kwargs: None)

    personalized = assessment_service.create_personalized_assessment(db_session, student, report["remediation_plan_id"], {"use_groq": True})
    question_rows = db_session.query(AssessmentQuestion).filter_by(assessment_id=personalized["id"]).all()

    assert question_rows
    assert {row.generation_method for row in question_rows} == {"deterministic"}
    assert all((row.chapter is None or row.chapter.course_id == course["id"]) for row in question_rows)
    assert all((row.skill is None or row.skill.course_id in {None, course["id"]}) for row in question_rows)


def test_phase9_professor_validation_draft_then_publish(db_session):
    professor, _, student, other_student, _, _, report = make_phase9_plan(db_session)
    client_student = build_test_client(db_session, student)
    client_professor = build_test_client(db_session, professor)

    draft = client_student.post(f"/api/remediation/{report['remediation_plan_id']}/personalized-assessment", json={"validation_mode": "professor"}).json()
    invisible = client_student.get(f"/api/assessments/{draft['id']}")
    approved = client_professor.post(f"/api/professor/personalized-assessments/{draft['id']}/approve")
    still_invisible = client_student.get(f"/api/assessments/{draft['id']}")
    published = client_professor.post(f"/api/professor/personalized-assessments/{draft['id']}/publish")
    assigned = client_student.get(f"/api/assessments/{draft['id']}")
    other = build_test_client(db_session, other_student).get(f"/api/assessments/{draft['id']}")
    repeated = client_professor.post(f"/api/professor/personalized-assessments/{draft['id']}/publish")

    assert draft["status"] == "draft"
    assert invisible.status_code == 404
    assert approved.status_code == 200
    assert approved.json()["status"] == "scheduled"
    assert still_invisible.status_code == 404
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["assigned_student_count"] == 1
    assert assigned.status_code == 200
    assert other.status_code == 404
    assert repeated.status_code == 200
    assert db_session.query(AssessmentAssignment).filter_by(assessment_id=draft["id"], student_id=student.id).count() == 1


def test_phase9_difficulty_reason_and_comparison_are_preserved(db_session):
    _, _, student, _, _, _, report = make_phase9_plan(db_session)
    personalized = assessment_service.create_personalized_assessment(db_session, student, report["remediation_plan_id"])
    questions = assessment_service.get_student_assessment(db_session, student, personalized["id"])["questions"]
    submitted = assessment_service.submit_assessment(
        db_session,
        student,
        personalized["id"],
        {"answers": {str(question["id"]): question["choices"][0] for question in questions}},
    )
    comparison = assessment_service.compare_latest_for_plan_detailed(db_session, student, report["remediation_plan_id"])
    rows = db_session.query(AssessmentQuestion).filter_by(assessment_id=personalized["id"]).all()

    assert submitted["assessment_id"] == personalized["id"]
    assert comparison["available"] is True
    assert comparison["personalized_attempt_id"] == submitted["attempt_id"]
    assert all(row.adaptation_reason for row in rows)
    assert all(row.source_attempt_id == report["attempt_id"] for row in rows)


def make_phase10_path(db_session):
    professor, other_professor, student, other_student, course, assessment, report = make_phase9_plan(db_session)
    path = db_session.query(StudyPath).filter_by(remediation_plan_id=report["remediation_plan_id"]).one()
    return professor, other_professor, student, other_student, course, assessment, report, path


def test_phase10_study_path_created_once_with_ordered_items(db_session):
    _, _, student, _, _, _, report, path = make_phase10_path(db_session)
    refreshed = study_path_service.create_or_refresh_for_plan(db_session, db_session.get(RemediationPlan, report["remediation_plan_id"]))
    first_count = db_session.query(StudyPathItem).filter_by(study_path_id=path.id).count()
    refreshed = study_path_service.create_or_refresh_for_plan(db_session, db_session.get(RemediationPlan, report["remediation_plan_id"]))
    second_count = db_session.query(StudyPathItem).filter_by(study_path_id=path.id).count()
    detail = build_test_client(db_session, student).get(f"/api/study-paths/{path.id}").json()

    assert refreshed.id == path.id
    assert first_count == second_count
    assert detail["items"] == sorted(detail["items"], key=lambda item: item["order_index"])
    assert detail["progress"]["total_items"] == first_count
    assert db_session.query(StudyPath).filter_by(remediation_plan_id=report["remediation_plan_id"]).count() == 1


def test_phase10_mastered_skill_is_not_added_as_remediation_step(db_session):
    _, _, student, _, _, assessment, _, path = make_phase10_path(db_session)
    original = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    detail = study_path_service.serialize_path(db_session, study_path_service.refresh_existing_path(db_session, path), detail=True)

    assert original[0]["skill_id"] not in {item["metadata"].get("skill_id") for item in detail["items"]}
    assert original[1]["skill_id"] in {item["metadata"].get("skill_id") for item in detail["items"]}


def test_phase10_locking_progress_skip_and_next_action(db_session):
    _, _, student, _, _, _, report, path = make_phase10_path(db_session)
    client = build_test_client(db_session, student)
    detail = client.get(f"/api/study-paths/{path.id}").json()
    required_total = detail["progress"]["required_items"]
    optional_item = next(item for item in detail["items"] if item["item_type"] == "ask_chatbot")
    first_required = next(item for item in detail["items"] if item["required"])
    locked_test = next(item for item in detail["items"] if item["item_type"] == "personalized_assessment")

    skip_required = client.post(f"/api/study-paths/{path.id}/items/{first_required['id']}/skip")
    skip_optional = client.post(f"/api/study-paths/{path.id}/items/{optional_item['id']}/skip")

    assert locked_test["status"] == "locked"
    assert skip_required.status_code == 422
    assert skip_optional.status_code in {200, 409}
    refreshed = client.post(f"/api/study-paths/{path.id}/refresh").json()
    assert refreshed["progress"]["required_items"] == required_total
    assert refreshed["next_action"]["study_path_item_id"] == refreshed["current_item"]["id"]


def test_phase10_personalized_assessment_unlocks_after_required_steps_and_comparison_after_submit(db_session):
    _, _, student, _, _, _, report, path = make_phase10_path(db_session)
    client = build_test_client(db_session, student)
    lessons = client.post(f"/api/remediation/{report['remediation_plan_id']}/lessons/generate").json()["lessons"]
    for lesson in lessons:
        client.put(f"/api/personalized-lessons/{lesson['id']}/complete")
        check = next(block["content"] for block in lesson["structured_content"] if block["type"] == "knowledge_check")
        client.post(f"/api/personalized-lessons/{lesson['id']}/knowledge-check/submit", json={"answer": check["answer"]})
    personalized = assessment_service.create_personalized_assessment(db_session, student, report["remediation_plan_id"])
    detail = client.post(f"/api/study-paths/{path.id}/refresh").json()
    test_item = next(item for item in detail["items"] if item["item_type"] == "personalized_assessment")
    questions = assessment_service.get_student_assessment(db_session, student, personalized["id"])["questions"]
    assessment_service.submit_assessment(db_session, student, personalized["id"], {"answers": {str(question["id"]): question["choices"][0] for question in questions}})
    after = client.post(f"/api/study-paths/{path.id}/refresh").json()
    comparison_item = next(item for item in after["items"] if item["item_type"] == "view_comparison")

    assert test_item["status"] == "available"
    assert comparison_item["status"] == "available"


def test_phase10_security_notifications_and_professor_access(db_session):
    professor, other_professor, student, other_student, _, _, report, path = make_phase10_path(db_session)
    own = build_test_client(db_session, student).get(f"/api/study-paths/{path.id}")
    other_student_response = build_test_client(db_session, other_student).get(f"/api/study-paths/{path.id}")
    professor_response = build_test_client(db_session, professor).get(f"/api/professor/study-paths/{path.id}")
    other_professor_response = build_test_client(db_session, other_professor).get(f"/api/professor/study-paths/{path.id}")
    first_notifications = db_session.query(Notification).filter_by(user_id=student.id, title="Parcours cree").count()
    study_path_service.create_or_refresh_for_plan(db_session, db_session.get(RemediationPlan, report["remediation_plan_id"]))
    second_notifications = db_session.query(Notification).filter_by(user_id=student.id, title="Parcours cree").count()

    assert own.status_code == 200
    assert other_student_response.status_code == 403
    assert professor_response.status_code == 200
    assert other_professor_response.status_code == 403
    assert first_notifications == second_notifications == 1


def test_phase10_next_course_filter_and_empty_state(db_session):
    professor, _, student, _, course, _, report, path = make_phase10_path(db_session)
    current_course = db_session.get(Course, course["id"])
    next_course = Course(
        id=9910,
        title="Suite francais ciblee",
        level=current_course.level,
        duration="1h",
        progress=0,
        summary="Cours suivant compatible.",
        description="Cours suivant compatible.",
        subject_id=current_course.subject_id,
        education_level_id=current_course.education_level_id,
        difficulty_level_id=current_course.difficulty_level_id,
        professor_id=professor.id,
        display_order=999,
        published=True,
        status="published",
    )
    db_session.add(next_course)
    db_session.commit()
    with_next = build_test_client(db_session, student).post(f"/api/study-paths/{path.id}/refresh").json()
    db_session.delete(next_course)
    db_session.commit()
    without_next = build_test_client(db_session, student).post(f"/api/study-paths/{path.id}/refresh").json()

    assert any(item["item_type"] == "continue_course" and item["entity_id"] == 9910 for item in with_next["items"])
    empty = next(item for item in without_next["items"] if item["item_type"] == "continue_course")
    assert empty["metadata"].get("empty_state") is True


def test_phase61_professor_dashboard_contains_assessment_widgets(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe dashboard"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])

    dashboard = build_test_client(db_session, professor).get("/api/professor/dashboard").json()

    assert dashboard["classroom_count"] == 1
    assert dashboard["classroom_student_count"] == 1
    assert dashboard["assessment_published_count"] == 1
    assert dashboard["assessment_participation_rate"] == 0
    assert dashboard["recent_assessments"][0]["id"] == assessment["id"]


def test_professor_student_tracking_lists_five_students_and_protects_detail(db_session):
    professor, other_professor, _ = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe suivi professeur"})
    students = []
    for index in range(5):
        student = UserProfile(
            id=8100 + index,
            email=f"tracked-{index}@example.com",
            full_name=f"Tracked Student {index}",
            role="student",
            status="active",
            level="Intermediaire",
        )
        db_session.add(student)
        students.append(student)
    db_session.commit()
    for student in students:
        assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
        db_session.add(CourseProgress(user_id=student.id, course_id=course["id"], progress=40 + student.id % 10, chapters=[]))
        db_session.add(QuizResult(
            user_id=student.id,
            course_id=course["id"],
            score=55,
            correct=1,
            total=2,
            corrections=[{"competence": "Comprehension", "max_points": 10, "points_awarded": 4, "correct": False}],
            answers=[{"competence": "Comprehension", "selected_answer": "reponse partielle"}],
        ))
    db_session.commit()

    professor_client = build_test_client(db_session, professor)
    other_client = build_test_client(db_session, other_professor)
    students_response = professor_client.get("/api/professor/students")
    detail_response = professor_client.get(f"/api/professor/students/{students[0].id}")
    forbidden_response = other_client.get(f"/api/professor/students/{students[0].id}")
    detail_json = detail_response.json()
    technical_dump = json.dumps(detail_json).lower()

    assert students_response.status_code == 200
    assert len(students_response.json()) == 5
    assert detail_response.status_code == 200
    assert detail_json["email"] == students[0].email
    assert detail_json["course_progress"]
    assert detail_json["quiz_results"]
    assert detail_json["competencies"]
    assert forbidden_response.status_code == 403
    for forbidden_key in ["model_version", "decision_scores", "svm_fallback", "embedding", "chunks", "holdout"]:
        assert forbidden_key not in technical_dump


def test_phase61_student_dashboard_contains_available_and_active_remediation(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe student dashboard"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    before_submit = build_test_client(db_session, student).get("/api/student/dashboard").json()
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))
    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise réponse" for question in questions}})
    after_submit = build_test_client(db_session, student).get("/api/student/dashboard").json()

    assert before_submit["available_count"] == 1
    assert after_submit["latest_result"]["attempt_id"] == report["attempt_id"]
    assert after_submit["active_remediation"]["id"] == report["remediation_plan_id"]
    assert after_submit["active_study_path"]["remediation_plan_id"] == report["remediation_plan_id"]
    assert after_submit["next_action"]["study_path_item_id"] == after_submit["active_study_path"]["current_item"]["id"]
    assert after_submit["next_action"]["path"] == after_submit["active_study_path"]["current_item"]["route"]


def test_phase61_comparison_without_second_test_has_empty_state(db_session, monkeypatch):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe empty comparison"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    monkeypatch.setattr(assessment_service.student_weakness_model_service, "predict_student_weaknesses", lambda db, user: weakness_prediction("faible"))
    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise réponse" for question in questions}})

    comparison = build_test_client(db_session, student).get(f"/api/remediation/{report['remediation_plan_id']}/comparison").json()

    assert comparison["available"] is False
    assert comparison["personalized_score"] is None


def test_phase61_notifications_are_not_duplicated_on_repeated_publish(db_session):
    professor, _, student = make_phase6_users(db_session)
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe notif"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))

    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    assessment_service.publish_assessment(db_session, professor, assessment["id"])

    notification_count = db_session.query(Notification).filter_by(user_id=student.id, title="Nouveau test publie").count()
    assert notification_count == 1


def test_phase61_student_results_are_isolated_between_students(db_session):
    professor, _, student = make_phase6_users(db_session)
    other_student = UserProfile(id=705, email="phase61-other@example.com", full_name="Other", role="student", status="active")
    db_session.add(other_student)
    db_session.commit()
    course = make_phase6_course(db_session, professor)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe isolation"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    assessment = assessment_service.create_assessment(db_session, professor, make_phase6_assessment_payload(course, classroom["id"]))
    assessment_service.publish_assessment(db_session, professor, assessment["id"])
    questions = assessment_service.get_student_assessment(db_session, student, assessment["id"])["questions"]
    report = assessment_service.submit_assessment(db_session, student, assessment["id"], {"answers": {str(question["id"]): "Mauvaise réponse" for question in questions}})

    response = build_test_client(db_session, other_student).get(f"/api/assessment-results/{report['attempt_id']}")

    assert response.status_code == 403


def phase10_package_json() -> str:
    return """
    {
      "schema_version": "1.0",
      "course": {
        "title": "Preparation au regional de francais",
        "summary": "Preparation personnalisee a l'examen regional.",
        "description": "Cours destine aux eleves de premiere annee du baccalaureat.",
        "subject": "Francais",
        "education_level": "1ere annee Baccalaureat",
        "difficulty": "Adaptatif",
        "estimated_duration_hours": 30,
        "prerequisites": []
      },
      "target": {
        "country": "Maroc",
        "cycle": "1ere_bac",
        "academic_year": "2026-2027",
        "region": "Casablanca-Settat",
        "stream": "Sciences",
        "exam_type": "regional"
      },
      "works": [
        {
          "id": "oeuvre_1",
          "title": "Oeuvre source",
          "author": "Auteur source",
          "genre": "Roman",
          "context": "Contexte fourni",
          "chapters": [
            {
              "id": "oeuvre_1_chapitre_1",
              "title": "Chapitre 1",
              "summary": "Resume du chapitre",
              "characters": ["Personnage A"],
              "themes": ["Theme 1"],
              "vocabulary": [{"term": "mot", "definition": "definition"}]
            }
          ]
        }
      ],
      "chapters": [
        {
          "id": "chapter_1",
          "title": "Comprehension de l'oeuvre",
          "order": 1,
          "objectives": ["Comprendre les evenements principaux"],
          "skills": ["Comprehension"],
          "content_blocks": [
            {"type": "heading", "content": "Introduction"},
            {"type": "paragraph", "content": "Le personnage principal commence par observer son environnement."},
            {"type": "example", "content": "Exemple d'analyse guidee."}
          ],
          "latex_reference": "chapter_1"
        },
        {
          "id": "chapter_2",
          "title": "Analyse litteraire",
          "order": 2,
          "objectives": ["Identifier un theme"],
          "skills": ["Analyse litteraire"],
          "content_blocks": [
            {"type": "paragraph", "content": "Le theme central est justifie par des indices du texte."},
            {"type": "exercise", "question": "Relevez un indice.", "solution": "Justifier par le texte."}
          ]
        }
      ],
      "assessment_blueprint": {
        "questions_per_assessment": 10,
        "duration_minutes": 30,
        "passing_score": 70,
        "max_attempts": 2,
        "skills": ["Comprehension", "Langue", "Production ecrite", "Analyse litteraire"],
        "levels": {
          "debutant": {"direct_questions_ratio": 0.7, "analysis_questions_ratio": 0.2, "production_questions_ratio": 0.1},
          "intermediaire": {"direct_questions_ratio": 0.4, "analysis_questions_ratio": 0.4, "production_questions_ratio": 0.2},
          "avance": {"direct_questions_ratio": 0.2, "analysis_questions_ratio": 0.4, "production_questions_ratio": 0.4}
        }
      }
    }
    """


def phase10_v2_package_json() -> str:
    data = json.loads(phase10_package_json())
    data["schema_version"] = "2.0"
    data["course"]["title"] = "Preparation regionale V2"
    data["course"]["summary"] = "Preparation regionale enrichie par des specifications visuelles."
    data["chapters"] = []
    for index in range(1, 7):
        data["chapters"].append({
            "id": f"chapter_{index}",
            "title": f"Chapitre V2 {index}",
            "order": index,
            "objectives": [f"Objectif V2 {index}"],
            "skills": [f"Competence V2 {index}"],
            "content_blocks": [
                {"type": "paragraph", "content": f"Contenu JSON V2 du chapitre {index}."},
                {"type": "example", "content": f"Exemple V2 du chapitre {index}."},
            ],
            "latex_reference": f"chapter_{index}",
        })
    data["visuals"] = [
        {
            "id": f"visual_{index}",
            "type": "mermaid" if index % 2 else "table",
            "title": f"Visuel {index}",
            "description": f"Specification visuelle {index}",
            "chapter_ref": f"chapter_{((index - 1) % 6) + 1}",
            "status": "to_provide_or_generate",
        }
        for index in range(1, 14)
    ]
    data["exam_training"] = {"objectives": ["Se preparer au regional"], "methods": ["Lire la consigne"]}
    data["content_quality_requirements"] = {
        "min_words_per_chapter": 800,
        "max_words_per_chapter": 1500,
        "required_sections": ["introduction", "exercices"],
    }
    data["source_policy"] = {"allow_external_knowledge": False, "citation_required": True}
    data["assets"] = {"generate_missing": True, "statuses": ["to_provide_or_generate"]}
    data["ai_generation_rules"] = {"enabled": True, "provider": "groq", "retries": 2}
    data["regional_exam_bank"] = {"items": []}
    data["latex_export"] = {"enabled": True, "include_visuals": True}
    return json.dumps(data)


def phase10_v2_latex() -> str:
    return "\n".join(
        f"\\section{{Chapitre V2 {index}}}\n\\label{{chapter_{index}}}\nTexte LaTeX V2 du chapitre {index}."
        for index in range(1, 7)
    )


def diagnostic_package_json(course_title: str, works: list[dict], academic_year: str = "2026-2027") -> str:
    data = json.loads(phase10_package_json())
    data["course"]["title"] = course_title
    data["target"]["academic_year"] = academic_year
    data["works"] = works
    for index, work in enumerate(works, start=1):
        data["chapters"].append({
            "id": f"work_chapter_{index}",
            "title": work["title"],
            "order": len(data["chapters"]) + 1,
            "objectives": [f"Comprendre {work['title']}"],
            "skills": ["Comprehension", "Analyse litteraire"],
            "content_blocks": [
                {"type": "paragraph", "content": f"{work['title']} est une oeuvre du texte regional avec ses personnages, ses themes et son contexte."},
                {"type": "example", "content": f"Exemple d'analyse autour de {work['title']}."},
            ],
        })
    return json.dumps(data)


def old_samir_package_json() -> str:
    return diagnostic_package_json(
        "Ancien package fictif Francais",
        [
            {
                "id": "oeuvre_demo",
                "title": "Le Voyage de Samir",
                "author": "Auteur fictif",
                "genre": "Recit fictif",
                "context": "Ancien package fictif utilise uniquement pour les tests.",
                "chapters": [
                    {
                        "id": "samir_1",
                        "title": "Le depart de Samir",
                        "summary": "Samir part avec Nadia dans un voyage invente.",
                        "characters": ["Samir", "Nadia"],
                        "themes": ["Voyage fictif"],
                        "vocabulary": [{"term": "depart", "definition": "Moment du commencement"}],
                    }
                ],
            }
        ],
    )


def official_french_package_json(academic_year: str = "2026-2027") -> str:
    return diagnostic_package_json(
        "Preparation au regional de francais - texte officiel",
        [
            {
                "id": "boite_merveilles",
                "title": "La Boite a merveilles",
                "author": "Ahmed Sefrioui",
                "genre": "Roman autobiographique",
                "context": "Oeuvre officielle du texte de francais.",
                "chapters": [{"id": "bm_1", "title": "Souvenirs d'enfance", "summary": "Le narrateur evoque l'enfance et la solitude.", "characters": ["Sidi Mohammed"], "themes": ["Souvenir", "Solitude"], "vocabulary": []}],
            },
            {
                "id": "antigone",
                "title": "Antigone",
                "author": "Jean Anouilh",
                "genre": "Theatre",
                "context": "Tragedie moderne et conflit entre loi et conscience.",
                "chapters": [{"id": "ant_1", "title": "Conflit tragique", "summary": "Antigone defend son devoir moral face a Creon.", "characters": ["Antigone", "Creon"], "themes": ["Devoir", "Pouvoir"], "vocabulary": []}],
            },
            {
                "id": "dernier_jour",
                "title": "Le Dernier Jour d'un condamne",
                "author": "Victor Hugo",
                "genre": "Roman a these",
                "context": "Plaidoyer contre la peine de mort.",
                "chapters": [{"id": "dj_1", "title": "Condamnation", "summary": "Le condamne exprime son angoisse et sa reflexion.", "characters": ["Le condamne"], "themes": ["Justice", "Peine de mort"], "vocabulary": []}],
            },
        ],
        academic_year=academic_year,
    )


def make_phase10_import_context(db_session):
    professor, other_professor, student = make_phase6_users(db_session)
    classroom = assessment_service.create_classroom(db_session, professor, {"name": "Classe import auto"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom["id"], {"student_id": student.id})
    return professor, other_professor, student, classroom


def test_phase10_automatic_import_json_without_latex_generates_course_assessments_and_assignments(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["course_id"]
    assert db_session.query(CourseLevelVariant).filter_by(course_id=data["course_id"]).count() == 3
    assert db_session.query(Quiz).filter_by(course_id=data["course_id"]).count() == 1
    assert db_session.query(QuizQuestion).join(Quiz).filter(Quiz.course_id == data["course_id"]).count() == 10
    assert db_session.query(Assessment).filter_by(course_id=data["course_id"], status="published").count() == 3
    assert db_session.query(AssessmentAssignment).filter_by(student_id=student.id).count() == 3
    assert db_session.query(ClassroomCourseAssignment).filter_by(course_id=data["course_id"], classroom_id=classroom["id"], active=True).count() == 1
    assert data["result_summary"]["course_classroom_assignments"] == 1
    assert data["result_summary"]["assessment_assignments"] == 3
    assert data["result_summary"]["students_with_course_access"] == 1
    assert db_session.query(RegionalExamProfile).filter_by(student_id=student.id).count() == 1
    assert db_session.query(LiteraryWork).filter_by(course_id=data["course_id"]).count() == 1
    course = db_session.get(Course, data["course_id"])
    assert course.subject.slug == "francais"
    assert course.education_level.slug == "1ere_bac"


def test_imported_course_is_visible_only_to_active_classroom_students(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    outsider = UserProfile(id=704, email="phase10-outsider@example.com", full_name="Outsider", role="student", status="active")
    db_session.add(outsider)
    db_session.commit()
    response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )
    course_id = response.json()["course_id"]

    student_client = build_test_client(db_session, student)
    outsider_client = build_test_client(db_session, outsider)
    student_courses = student_client.get("/api/courses")
    outsider_courses = outsider_client.get("/api/courses")
    student_detail = student_client.get(f"/api/courses/{course_id}")
    outsider_detail = outsider_client.get(f"/api/courses/{course_id}")

    assert student_courses.status_code == 200
    assert course_id in [item["id"] for item in student_courses.json()]
    assert student_detail.status_code == 200
    assert student_detail.json()["id"] == course_id
    assert course_id not in [item["id"] for item in outsider_courses.json()]
    assert outsider_detail.status_code == 404


def test_auto_assign_false_does_not_create_course_classroom_assignment(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "false"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )
    course_id = response.json()["course_id"]

    assert response.status_code == 200
    assert db_session.query(ClassroomCourseAssignment).filter_by(course_id=course_id, classroom_id=classroom["id"]).count() == 0
    assert db_session.query(AssessmentAssignment).filter_by(student_id=student.id).count() == 0
    assert course_id in [item["id"] for item in build_test_client(db_session, student).get("/api/courses").json()]


def test_phase10_automatic_import_with_latex_and_idempotence(db_session):
    professor, _, _, classroom = make_phase10_import_context(db_session)
    latex = "\\section{chapter_1}\\label{chapter_1}\nTexte LaTeX detaille.\n\\begin{itemize}\n\\item Idee principale\n\\end{itemize}"
    client = build_test_client(db_session, professor)

    first = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package.json", phase10_package_json(), "application/json"),
            "latex_file": ("cours.tex", latex, "text/plain"),
        },
    )
    second = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package.json", phase10_package_json(), "application/json"),
            "latex_file": ("cours.tex", latex, "text/plain"),
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert db_session.query(PedagogicalPackageImportJob).count() == 1
    assert db_session.query(ClassroomCourseAssignment).filter_by(course_id=first.json()["course_id"], classroom_id=classroom["id"]).count() == 1


def test_phase10_v2_import_accepts_visual_specs_and_keeps_json_latex_chapter_count(db_session):
    professor, _, _, classroom = make_phase10_import_context(db_session)
    client = build_test_client(db_session, professor)

    first = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package-v2.json", phase10_v2_package_json(), "application/json"),
            "latex_file": ("cours-v2.tex", phase10_v2_latex(), "text/plain"),
        },
    )
    second = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package-v2.json", phase10_v2_package_json(), "application/json"),
            "latex_file": ("cours-v2.tex", phase10_v2_latex(), "text/plain"),
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["schema_version"] == "2.0"
    assert first.json()["chapters_count"] == 6
    assert first.json()["visuals_count"] == 13
    assert first.json()["regional_exams_count"] == 0
    assert db_session.query(CourseChapter).filter_by(course_id=first.json()["course_id"]).count() == 6
    visual_blocks = [
        block
        for chapter in db_session.query(CourseChapter).filter_by(course_id=first.json()["course_id"]).all()
        for block in (chapter.structured_content or [])
        if isinstance(block, dict) and block.get("type") == "visual"
    ]
    assert len(visual_blocks) == 13
    assert db_session.query(PedagogicalPackageImportJob).count() == 1


def test_phase10_v2_import_reports_missing_latex_reference_readably(db_session):
    professor, _, _, classroom = make_phase10_import_context(db_session)

    response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package-v2.json", phase10_v2_package_json(), "application/json"),
            "latex_file": ("cours-v2.tex", phase10_v2_latex().replace("\\label{chapter_6}", "\\label{missing_6}"), "text/plain"),
        },
    )

    assert response.status_code == 422
    assert "Reference LaTeX absente: chapter_6" in response.text


def test_completed_import_repair_recreates_missing_course_classroom_assignment(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )
    course_id = response.json()["course_id"]
    course = db_session.get(Course, course_id)
    course.published = False
    course.status = "draft"
    db_session.query(ClassroomCourseAssignment).filter_by(course_id=course_id, classroom_id=classroom["id"]).delete()
    db_session.commit()

    repair = automatic_course_generation_service.repair_completed_course_classroom_assignments(db_session)

    assert repair["course_classroom_assignments"] == 1
    assert db_session.get(Course, course_id).published is True
    assert db_session.get(Course, course_id).status == "published"
    assert db_session.query(ClassroomCourseAssignment).filter_by(course_id=course_id, classroom_id=classroom["id"], active=True).count() == 1
    assert course_id in [item["id"] for item in build_test_client(db_session, student).get("/api/courses").json()]


def test_public_seed_courses_remain_visible_to_students(db_session):
    professor, _, student = make_phase6_users(db_session)
    course_service.seed_courses_from_mock(db_session)

    response = build_test_client(db_session, student).get("/api/courses")

    assert response.status_code == 200
    assert {1, 2, 3}.issubset({item["id"] for item in response.json()})


def test_diagnostic_bank_is_generated_from_automatic_import_sources(db_session):
    professor, _, _, classroom = make_phase10_import_context(db_session)
    response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )

    assert response.status_code == 200
    course_id = response.json()["course_id"]
    course = db_session.get(Course, course_id)
    questions = db_session.query(DiagnosticQuestion).filter_by(
        subject_id=course.subject_id,
        education_level_id=course.education_level_id,
        source_course_id=course.id,
        active=True,
    ).all()
    by_difficulty = {
        slug: db_session.query(DiagnosticQuestion)
        .join(persistence_models.DifficultyLevel)
        .filter(
            DiagnosticQuestion.source_course_id == course.id,
            DiagnosticQuestion.active.is_(True),
            persistence_models.DifficultyLevel.slug == slug,
        )
        .count()
        for slug in ["debutant", "intermediaire", "avance"]
    }

    assert len(questions) >= 20
    assert all(question.source_chapter_id for question in questions)
    assert all(question.source_hash and question.question_hash for question in questions)
    assert all(question.correct_answer in question.choices for question in questions)
    assert all(question.generation_method == "deterministic_fallback" for question in questions)
    assert by_difficulty == {"debutant": 10, "intermediaire": 10, "avance": 10}
    assert response.json()["result_summary"]["diagnostic_bank"]["active_questions"] == 30


def test_diagnostic_bank_with_latex_keeps_idempotence_and_no_duplicates(db_session):
    professor, _, _, classroom = make_phase10_import_context(db_session)
    latex = "\\section{chapter_1}\\label{chapter_1}\nTexte LaTeX detaille pour le test diagnostic."
    client = build_test_client(db_session, professor)

    first = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package.json", phase10_package_json(), "application/json"),
            "latex_file": ("cours.tex", latex, "text/plain"),
        },
    )
    second = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package.json", phase10_package_json(), "application/json"),
            "latex_file": ("cours.tex", latex, "text/plain"),
        },
    )
    course_id = first.json()["course_id"]
    hashes = [
        row.question_hash for row in db_session.query(DiagnosticQuestion)
        .filter_by(source_course_id=course_id, active=True)
        .all()
    ]

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(hashes) >= 20
    assert len(hashes) == len(set(hashes))
    assert db_session.query(PedagogicalPackageImportJob).count() == 1


def test_diagnostic_question_selection_is_filtered_balanced_and_hides_answers(db_session):
    professor, _, _, classroom = make_phase10_import_context(db_session)
    import_response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )
    course = db_session.get(Course, import_response.json()["course_id"])
    client = build_test_client(db_session)

    availability = client.get(f"/api/diagnostic/availability?subject_id={course.subject_id}&education_level_id={course.education_level_id}&limit=20")
    response = client.get(f"/api/diagnostic/questions?subject_id={course.subject_id}&education_level_id={course.education_level_id}&limit=20")
    questions = response.json()["questions"]
    by_difficulty = {}
    for question in questions:
        by_difficulty[question["difficulty"]] = by_difficulty.get(question["difficulty"], 0) + 1

    assert availability.status_code == 200
    assert availability.json()["available_count"] >= 20
    assert availability.json()["can_start"] is True
    assert response.status_code == 200
    assert len(questions) == 20
    assert all(question["subject_id"] == course.subject_id for question in questions)
    assert all("correct_answer" not in question for question in questions)
    assert sorted(by_difficulty.values()) == [6, 7, 7]


def test_diagnostic_availability_blocks_incomplete_bank(db_session):
    subject = db_session.query(Subject).filter_by(slug="francais").one()
    difficulty = db_session.query(persistence_models.DifficultyLevel).filter_by(slug="debutant").one()
    db_session.query(DiagnosticQuestion).filter_by(subject_id=subject.id).update({"active": False})
    db_session.add(DiagnosticQuestion(
        subject_id=subject.id,
        difficulty_level_id=difficulty.id,
        topic="Comprehension",
        question="Question unique ",
        choices=["Oui", "Non"],
        correct_answer="Oui",
        explanation="Source unique.",
    ))
    db_session.commit()
    client = build_test_client(db_session)

    availability = client.get(f"/api/diagnostic/availability?subject_id={subject.id}&limit=20")
    questions = client.get(f"/api/diagnostic/questions?subject_id={subject.id}&limit=20")

    assert availability.status_code == 200
    assert availability.json()["can_start"] is False
    assert availability.json()["missing_count"] == 19
    assert questions.status_code == 409


def test_diagnostic_submit_keeps_false_advanced_protection_for_generated_bank(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    import_response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )
    course = db_session.get(Course, import_response.json()["course_id"])
    client = build_test_client(db_session, student)
    payload = client.get(f"/api/diagnostic/questions?subject_id={course.subject_id}&education_level_id={course.education_level_id}&limit=20").json()
    questions = db_session.query(DiagnosticQuestion).filter(DiagnosticQuestion.id.in_([item["id"] for item in payload["questions"]])).all()
    answers = {}
    for question in questions:
        if question.difficulty_level.slug == "avance":
            answers[str(question.id)] = "__wrong__"
        else:
            answers[str(question.id)] = question.correct_answer

    result = client.post("/api/diagnostic/submit", json={
        "subject_id": course.subject_id,
        "education_level_id": course.education_level_id,
        "answers": answers,
    })

    assert result.status_code == 200
    assert result.json()["level"] == "Intermédiaire"
    assert db_session.query(DiagnosticSession).filter_by(student_id=student.id, completed=True).count() == 1
    assert db_session.query(DiagnosticAnswer).count() == 20


def test_new_import_deactivates_obsolete_samir_bank_for_same_classroom(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    client = build_test_client(db_session, professor)
    old_import = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("old.json", old_samir_package_json(), "application/json")},
    )
    new_import = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("new.json", official_french_package_json(), "application/json")},
    )
    course = db_session.get(Course, new_import.json()["course_id"])
    student_client = build_test_client(db_session, student)

    availability = student_client.get(f"/api/diagnostic/availability?subject_id={course.subject_id}&education_level_id={course.education_level_id}&limit=20")
    response = student_client.get(f"/api/diagnostic/questions?subject_id={course.subject_id}&education_level_id={course.education_level_id}&limit=20")
    selected_text = json.dumps(response.json(), ensure_ascii=False)
    active_old_count = db_session.query(DiagnosticQuestion).filter_by(import_job_id=old_import.json()["id"], active=True).count()
    active_new_count = db_session.query(DiagnosticQuestion).filter_by(import_job_id=new_import.json()["id"], active=True).count()
    active_bank_text = json.dumps([
        question.source_snapshot for question in db_session.query(DiagnosticQuestion).filter_by(import_job_id=new_import.json()["id"], active=True).all()
    ], ensure_ascii=False)

    assert old_import.status_code == 200
    assert new_import.status_code == 200
    assert db_session.get(PedagogicalPackageImportJob, old_import.json()["id"]).is_current is False
    assert db_session.get(PedagogicalPackageImportJob, new_import.json()["id"]).is_current is True
    assert active_old_count == 0
    assert active_new_count == 30
    assert availability.json()["available_count"] == 30
    assert availability.json()["active_package"]["id"] == new_import.json()["id"]
    assert "Le Voyage de Samir" not in selected_text
    assert "Samir" not in selected_text
    assert "Nadia" not in selected_text
    assert "La Boite a merveilles" in active_bank_text
    assert "Antigone" in active_bank_text
    assert "Le Dernier Jour d'un condamne" in active_bank_text


def test_current_diagnostic_bank_is_separated_between_classrooms(db_session):
    professor, _, student_a, classroom_a = make_phase10_import_context(db_session)
    student_b = UserProfile(id=704, email="phase10-student-b@example.com", full_name="Student B", role="student", status="active")
    db_session.add(student_b)
    db_session.commit()
    classroom_b = assessment_service.create_classroom(db_session, professor, {"name": "Classe import auto B"})
    assessment_service.add_student_to_classroom(db_session, professor, classroom_b["id"], {"student_id": student_b.id})
    client = build_test_client(db_session, professor)
    import_a = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom_a["id"]), "auto_assign": "true"},
        files={"json_file": ("official.json", official_french_package_json(), "application/json")},
    )
    import_b = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom_b["id"]), "auto_assign": "true"},
        files={"json_file": ("old.json", old_samir_package_json(), "application/json")},
    )
    course_a = db_session.get(Course, import_a.json()["course_id"])

    availability_a = build_test_client(db_session, student_a).get(f"/api/diagnostic/availability?subject_id={course_a.subject_id}&education_level_id={course_a.education_level_id}&limit=20").json()
    availability_b = build_test_client(db_session, student_b).get(f"/api/diagnostic/availability?subject_id={course_a.subject_id}&education_level_id={course_a.education_level_id}&limit=20").json()

    assert availability_a["active_package"]["id"] == import_a.json()["id"]
    assert availability_b["active_package"]["id"] == import_b.json()["id"]


def test_current_diagnostic_bank_prefers_latest_academic_year_for_student(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    client = build_test_client(db_session, professor)
    old_year = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("official-2025.json", official_french_package_json("2025-2026"), "application/json")},
    )
    new_year = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("official-2026.json", official_french_package_json("2026-2027"), "application/json")},
    )
    course = db_session.get(Course, new_year.json()["course_id"])

    availability = build_test_client(db_session, student).get(f"/api/diagnostic/availability?subject_id={course.subject_id}&education_level_id={course.education_level_id}&limit=20").json()

    assert db_session.get(PedagogicalPackageImportJob, old_year.json()["id"]).is_current is True
    assert db_session.get(PedagogicalPackageImportJob, new_year.json()["id"]).is_current is True
    assert availability["active_package"]["id"] == new_year.json()["id"]
    assert availability["active_package"]["academic_year"] == "2026-2027"


def test_obsolete_started_session_is_abandoned_when_new_package_is_current(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    client = build_test_client(db_session, professor)
    old_import = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("old.json", old_samir_package_json(), "application/json")},
    )
    old_course = db_session.get(Course, old_import.json()["course_id"])
    old_session = DiagnosticSession(
        student_id=student.id,
        subject_id=old_course.subject_id,
        education_level_id=old_course.education_level_id,
        import_job_id=old_import.json()["id"],
        imported_package_hash=old_import.json()["json_sha256"] if "json_sha256" in old_import.json() else None,
        status="started",
    )
    db_session.add(old_session)
    db_session.commit()
    db_session.refresh(old_session)
    new_import = client.post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("new.json", official_french_package_json(), "application/json")},
    )
    new_course = db_session.get(Course, new_import.json()["course_id"])
    student_client = build_test_client(db_session, student)
    questions_payload = student_client.get(f"/api/diagnostic/questions?subject_id={new_course.subject_id}&education_level_id={new_course.education_level_id}&limit=20").json()
    new_questions = db_session.query(DiagnosticQuestion).filter(DiagnosticQuestion.id.in_([item["id"] for item in questions_payload["questions"]])).all()
    answers = {str(question.id): question.correct_answer for question in new_questions}

    result = student_client.post("/api/diagnostic/submit", json={
        "subject_id": new_course.subject_id,
        "education_level_id": new_course.education_level_id,
        "session_id": old_session.id,
        "answers": answers,
    })
    db_session.refresh(old_session)
    completed_session = db_session.query(DiagnosticSession).filter(
        DiagnosticSession.student_id == student.id,
        DiagnosticSession.import_job_id == new_import.json()["id"],
        DiagnosticSession.completed.is_(True),
    ).one()

    assert result.status_code == 200
    assert old_session.status == "abandoned"
    assert completed_session.imported_package_hash == db_session.get(PedagogicalPackageImportJob, new_import.json()["id"]).json_sha256


def test_phase10_automatic_import_rejects_dangerous_latex_and_rolls_back(db_session):
    professor, _, _, classroom = make_phase10_import_context(db_session)
    response = build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={
            "json_file": ("package.json", phase10_package_json(), "application/json"),
            "latex_file": ("cours.tex", "\\write18{rm -rf /}", "text/plain"),
        },
    )

    assert response.status_code == 422
    assert db_session.query(PedagogicalPackageImportJob).count() == 0
    assert db_session.query(Course).filter(Course.title == "Preparation au regional de francais").count() == 0


def test_phase10_automatic_import_forbids_other_professor_classroom(db_session):
    professor, other_professor, _, classroom = make_phase10_import_context(db_session)
    response = build_test_client(db_session, other_professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )

    assert response.status_code == 403


def test_phase10_parent_link_dashboard_and_isolation(db_session):
    _, _, student = make_phase6_users(db_session)
    parent = UserProfile(id=810, email="parent@example.com", full_name="Parent", role="parent", status="active")
    other_student = UserProfile(id=811, email="other-child@example.com", full_name="Other Child", role="student", status="active")
    admin = UserProfile(id=812, email="admin-phase10@example.com", full_name="Admin", role="admin", status="active")
    db_session.add_all([parent, other_student, admin])
    db_session.commit()

    link = admin_service.create_parent_student_link(db_session, admin, {"parent_id": parent.id, "student_id": student.id})
    dashboard = build_test_client(db_session, parent).get("/api/parent/dashboard")
    own_child = build_test_client(db_session, parent).get(f"/api/parent/students/{student.id}")
    forbidden = build_test_client(db_session, parent).get(f"/api/parent/students/{other_student.id}")

    assert link["parent_id"] == parent.id
    assert dashboard.status_code == 200
    assert dashboard.json()["children"][0]["id"] == student.id
    assert own_child.status_code == 200
    assert forbidden.status_code == 403
    assert db_session.query(ParentNotification).filter_by(parent_id=parent.id, student_id=student.id).count() == 1


def test_parent_space_exposes_public_pedagogical_tracking_only(db_session):
    parent = UserProfile(id=821, email="parent-public@example.com", full_name="Parent Public", role="parent", status="active")
    student = UserProfile(id=822, email="child-public@example.com", full_name="Child Public", role="student", status="active", level="Intermediaire")
    outsider = UserProfile(id=823, email="child-outsider@example.com", full_name="Outsider", role="student", status="active")
    db_session.add_all([parent, student, outsider])
    db_session.flush()
    db_session.add(ParentStudentLink(parent_id=parent.id, student_id=student.id, status="active"))
    db_session.add(DiagnosticResult(user_id=student.id, score=14, total=20, correct_count=14, level="Intermediaire", results_by_topic=[{"topic": "Langue", "score": 70}]))
    db_session.add(CourseProgress(user_id=student.id, course_id=1, progress=60, chapters=[{"title": "Antigone"}]))
    db_session.add(QuizResult(user_id=student.id, course_id=1, score=8, correct=8, total=10, recommendation="Revoir la méthodologie."))
    db_session.commit()

    client = build_test_client(db_session, parent)
    dashboard = client.get("/api/parent/dashboard")
    detail = client.get(f"/api/parent/students/{student.id}")
    progress = client.get(f"/api/parent/students/{student.id}/progress")
    weaknesses = client.get(f"/api/parent/students/{student.id}/weaknesses")
    attempts = client.get(f"/api/parent/students/{student.id}/attempts")
    recommendations = client.get(f"/api/parent/students/{student.id}/recommendations")
    forbidden = client.get(f"/api/parent/students/{outsider.id}")

    assert dashboard.status_code == 200
    assert detail.status_code == 200
    assert progress.status_code == 200
    assert weaknesses.status_code == 200
    assert attempts.status_code == 200
    assert recommendations.status_code == 200
    assert forbidden.status_code == 403
    payload_text = str(detail.json())
    for technical_key in ["model_version", "decision_scores", "svm_fallback", "adaptation_id", "embeddings", "chunks", "confidence"]:
        assert technical_key not in payload_text
    assert detail.json()["diagnostic"]["level"] == "Intermediaire"
    assert {row["competence"] for row in detail.json()["competencies"]} >= {"Compréhension", "Langue", "Figures de style", "Production écrite", "Méthodologie"}


def test_parent_routes_reject_student_and_professor_roles(db_session):
    parent = UserProfile(id=831, email="parent-role@example.com", full_name="Parent", role="parent", status="active")
    student = UserProfile(id=832, email="student-role@example.com", full_name="Student", role="student", status="active")
    professor = UserProfile(id=833, email="prof-role@example.com", full_name="Professor", role="professor", status="active")
    db_session.add_all([parent, student, professor])
    db_session.commit()

    assert build_test_client(db_session, student).get("/api/parent/dashboard").status_code == 403
    assert build_test_client(db_session, professor).get("/api/parent/dashboard").status_code == 403


def test_parent_cannot_access_admin_or_professor_creation_routes(db_session):
    parent = UserProfile(id=841, email="parent-forbidden@example.com", full_name="Parent", role="parent", status="active")
    db_session.add(parent)
    db_session.commit()
    client = build_test_client(db_session, parent)

    assert client.get("/api/admin/users").status_code == 403
    response = client.post("/api/professor/classrooms", json={"name": "Classe interdite"})
    assert response.status_code == 403


def test_admin_can_manage_parent_student_links_from_routes(db_session):
    admin = UserProfile(id=851, email="admin-link@example.com", full_name="Admin", role="admin", status="active")
    parent = UserProfile(id=852, email="parent-link@example.com", full_name="Parent", role="parent", status="active")
    student = UserProfile(id=853, email="student-link@example.com", full_name="Student", role="student", status="active")
    db_session.add_all([admin, parent, student])
    db_session.commit()

    admin_client = build_test_client(db_session, admin)
    parent_client = build_test_client(db_session, parent)
    linked = admin_client.post(f"/api/admin/parents/{parent.id}/students/{student.id}")
    dashboard = parent_client.get("/api/parent/dashboard")
    unlinked = admin_client.delete(f"/api/admin/parents/{parent.id}/students/{student.id}")
    empty_dashboard = parent_client.get("/api/parent/dashboard")

    assert linked.status_code == 200
    assert linked.json()["parent_id"] == parent.id
    assert linked.json()["student_id"] == student.id
    assert dashboard.status_code == 200
    assert [child["id"] for child in dashboard.json()["children"]] == [student.id]
    assert unlinked.status_code == 200
    assert empty_dashboard.status_code == 200
    assert empty_dashboard.json()["children"] == []


def test_admin_parent_student_link_rejects_duplicates_and_invalid_roles(db_session):
    admin = UserProfile(id=861, email="admin-link-rules@example.com", full_name="Admin", role="admin", status="active")
    parent = UserProfile(id=862, email="parent-link-rules@example.com", full_name="Parent", role="parent", status="active")
    student = UserProfile(id=863, email="student-link-rules@example.com", full_name="Student", role="student", status="active")
    professor = UserProfile(id=864, email="prof-link-rules@example.com", full_name="Professor", role="professor", status="active")
    other_admin = UserProfile(id=865, email="admin-child-rules@example.com", full_name="Admin Child", role="admin", status="active")
    db_session.add_all([admin, parent, student, professor, other_admin])
    db_session.commit()
    client = build_test_client(db_session, admin)

    assert client.post(f"/api/admin/parents/{parent.id}/students/{student.id}").status_code == 200
    assert client.post(f"/api/admin/parents/{parent.id}/students/{student.id}").status_code == 409
    assert client.post(f"/api/admin/parents/{parent.id}/students/{professor.id}").status_code == 422
    assert client.post(f"/api/admin/parents/{parent.id}/students/{other_admin.id}").status_code == 422
    assert client.post(f"/api/admin/parents/{parent.id}/students/{parent.id}").status_code == 422
    assert client.post(f"/api/admin/parents/{student.id}/students/{parent.id}").status_code == 422


def test_non_admin_cannot_manage_parent_student_links(db_session):
    parent = UserProfile(id=871, email="parent-non-admin-link@example.com", full_name="Parent", role="parent", status="active")
    student = UserProfile(id=872, email="student-non-admin-link@example.com", full_name="Student", role="student", status="active")
    db_session.add_all([parent, student])
    db_session.commit()
    client = build_test_client(db_session, parent)

    assert client.get(f"/api/admin/parents/{parent.id}/students").status_code == 403
    assert client.post(f"/api/admin/parents/{parent.id}/students/{student.id}").status_code == 403
    assert client.delete(f"/api/admin/parents/{parent.id}/students/{student.id}").status_code == 403


def test_admin_parent_dashboard_returns_multiple_children(db_session):
    admin = UserProfile(id=881, email="admin-multi-link@example.com", full_name="Admin", role="admin", status="active")
    parent = UserProfile(id=882, email="parent-multi-link@example.com", full_name="Parent", role="parent", status="active")
    student_a = UserProfile(id=883, email="student-a-multi-link@example.com", full_name="Student A", role="student", status="active")
    student_b = UserProfile(id=884, email="student-b-multi-link@example.com", full_name="Student B", role="student", status="active")
    db_session.add_all([admin, parent, student_a, student_b])
    db_session.commit()
    client = build_test_client(db_session, admin)

    assert client.post(f"/api/admin/parents/{parent.id}/students/{student_a.id}").status_code == 200
    assert client.post(f"/api/admin/parents/{parent.id}/students/{student_b.id}").status_code == 200
    parent_links = client.get(f"/api/admin/parents/{parent.id}/students")
    dashboard = build_test_client(db_session, parent).get("/api/parent/dashboard")

    assert parent_links.status_code == 200
    assert {child["student_id"] for child in parent_links.json()["children"]} == {student_a.id, student_b.id}
    assert {child["id"] for child in dashboard.json()["children"]} == {student_a.id, student_b.id}


def test_phase10_regional_exam_preparation_endpoint_uses_postgres_data(db_session):
    professor, _, student, classroom = make_phase10_import_context(db_session)
    build_test_client(db_session, professor).post(
        "/api/professor/courses/automatic-import",
        data={"classroom_id": str(classroom["id"]), "auto_assign": "true"},
        files={"json_file": ("package.json", phase10_package_json(), "application/json")},
    )

    response = build_test_client(db_session, student).get("/api/regional-exam-preparation")

    assert response.status_code == 200
    data = response.json()
    assert data["student"]["school_year"] == "1ere Bac"
    assert data["works"][0]["title"] == "Oeuvre source"
    assert data["readiness"]["certainty"] == "Non predictif"
