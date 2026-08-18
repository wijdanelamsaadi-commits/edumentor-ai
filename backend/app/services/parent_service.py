from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.persistence import (
    Assessment,
    AssessmentAssignment,
    AssessmentAttempt,
    DiagnosticResult,
    Course,
    CourseProgress,
    ParentNotification,
    ParentNotificationPreference,
    ParentStudentLink,
    QuizResult,
    RegionalExamProfile,
    RemediationPlan,
    StudyPath,
    UserProfile,
)
from app.services.notifications.parent_notification_service import get_or_create_preferences
from app.services import student_weakness_model_service


PARENT_COMPETENCIES = [
    "Compréhension",
    "Langue",
    "Figures de style",
    "Production écrite",
    "Méthodologie",
]


def list_children(db: Session, parent: UserProfile) -> dict:
    links = active_links(db, parent.id)
    children = [serialize_child_summary(db, link.student) for link in links]
    selected = children[0] if children else None
    return {
        "children": children,
        "selected_student_id": selected["id"] if selected else None,
        "selected_student": selected,
        "summary": build_parent_overview(db, selected["id"]) if selected else empty_parent_overview(),
    }


def get_child_dashboard(db: Session, parent: UserProfile, student_id: int) -> dict:
    student = get_linked_student(db, parent.id, student_id)
    progress_rows = list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == student.id).order_by(CourseProgress.updated_at.desc())))
    attempts = list(db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.student_id == student.id, AssessmentAttempt.completed.is_(True)).order_by(AssessmentAttempt.submitted_at.desc())))
    quiz_rows = list(db.scalars(select(QuizResult).where(QuizResult.user_id == student.id).order_by(QuizResult.created_at.desc())))
    latest_diagnostic = latest_diagnostic_result(db, student.id)
    remediation_rows = list(db.scalars(select(RemediationPlan).where(RemediationPlan.student_id == student.id).order_by(RemediationPlan.created_at.desc())))
    study_paths = list(db.scalars(select(StudyPath).where(StudyPath.student_id == student.id, StudyPath.active.is_(True)).order_by(StudyPath.updated_at.desc())))
    regional = db.scalars(select(RegionalExamProfile).where(RegionalExamProfile.student_id == student.id).order_by(RegionalExamProfile.updated_at.desc())).first()
    weaknesses = safe_parent_weaknesses(db, student)

    return {
        "student": serialize_student(student),
        "level": latest_diagnostic.level if latest_diagnostic else student.level,
        "diagnostic": serialize_diagnostic(latest_diagnostic),
        "progression": {
            "average": round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0,
            "courses_started": len(progress_rows),
            "courses_completed": len([row for row in progress_rows if row.progress >= 100]),
            "courses": [serialize_progress(db, row) for row in progress_rows[:8]],
            "works": build_three_works_progress(progress_rows),
        },
        "results": {
            "recent_average": round(sum(attempt.percentage for attempt in attempts[:5]) / min(len(attempts), 5), 2) if attempts else 0,
            "attempts_count": len(attempts),
            "recent": [serialize_attempt(db, attempt) for attempt in attempts[:5]],
            "quiz_scores": [serialize_quiz_result(db, quiz) for quiz in quiz_rows[:8]],
        },
        "competencies": weaknesses["competencies"],
        "weak_points": weaknesses["weak_points"],
        "recommendations": build_parent_recommendations(weaknesses["competencies"], progress_rows, attempts),
        "last_activity": latest_activity(progress_rows, attempts, quiz_rows),
        "remediations": [{"id": plan.id, "course_id": plan.course_id, "status": plan.status, "initial_score": plan.initial_score} for plan in remediation_rows[:5]],
        "study_paths": [{"id": path.id, "title": path.title, "status": path.status, "progress_percentage": path.progress_percentage} for path in study_paths[:5]],
        "regional_exam": serialize_regional_profile(regional),
        "alerts": parent_alerts(attempts, progress_rows, study_paths),
    }


def get_child_progress(db: Session, parent: UserProfile, student_id: int) -> dict:
    dashboard = get_child_dashboard(db, parent, student_id)
    return {
        "student": dashboard["student"],
        "level": dashboard["level"],
        "progression": dashboard["progression"],
        "competencies": dashboard["competencies"],
        "last_activity": dashboard["last_activity"],
    }


def get_child_weaknesses(db: Session, parent: UserProfile, student_id: int) -> dict:
    dashboard = get_child_dashboard(db, parent, student_id)
    return {
        "student": dashboard["student"],
        "weak_points": dashboard["weak_points"],
        "competencies": dashboard["competencies"],
        "recommendations": dashboard["recommendations"],
    }


def get_child_attempts(db: Session, parent: UserProfile, student_id: int) -> dict:
    dashboard = get_child_dashboard(db, parent, student_id)
    return {
        "student": dashboard["student"],
        "diagnostic": dashboard["diagnostic"],
        "results": dashboard["results"],
        "regional_exam": dashboard["regional_exam"],
    }


def get_child_recommendations(db: Session, parent: UserProfile, student_id: int) -> dict:
    dashboard = get_child_dashboard(db, parent, student_id)
    return {
        "student": dashboard["student"],
        "recommendations": dashboard["recommendations"],
        "weak_points": dashboard["weak_points"],
    }


def get_preferences(db: Session, parent: UserProfile) -> dict:
    return serialize_preferences(get_or_create_preferences(db, parent.id))


def update_preferences(db: Session, parent: UserProfile, payload: dict) -> dict:
    preferences = get_or_create_preferences(db, parent.id)
    for field in [
        "email_enabled",
        "whatsapp_enabled",
        "weekly_summary_enabled",
        "immediate_alerts_enabled",
        "preferred_language",
        "phone_number",
        "phone_verified",
    ]:
        if field in payload:
            setattr(preferences, field, payload[field])
    if payload.get("consent_recorded"):
        preferences.consent_recorded_at = datetime.utcnow()
    preferences.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(preferences)
    return serialize_preferences(preferences)


def list_notifications(db: Session, parent: UserProfile) -> dict:
    rows = list(db.scalars(select(ParentNotification).where(ParentNotification.parent_id == parent.id).order_by(ParentNotification.created_at.desc()).limit(100)))
    return {"notifications": [serialize_notification(row) for row in rows]}


def active_links(db: Session, parent_id: int) -> list[ParentStudentLink]:
    return list(db.scalars(select(ParentStudentLink).where(ParentStudentLink.parent_id == parent_id, ParentStudentLink.status == "active")))


def get_linked_student(db: Session, parent_id: int, student_id: int) -> UserProfile:
    link = db.scalars(
        select(ParentStudentLink).where(
            ParentStudentLink.parent_id == parent_id,
            ParentStudentLink.student_id == student_id,
            ParentStudentLink.status == "active",
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=403, detail="Eleve non lie a ce parent")
    return link.student


def serialize_child_summary(db: Session, student: UserProfile) -> dict:
    progress_avg = db.scalar(select(func.avg(CourseProgress.progress)).where(CourseProgress.user_id == student.id)) or 0
    latest_attempt = db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.student_id == student.id, AssessmentAttempt.completed.is_(True)).order_by(AssessmentAttempt.submitted_at.desc())).first()
    latest_diagnostic = latest_diagnostic_result(db, student.id)
    return {
        "id": student.id,
        "full_name": student.full_name,
        "email": student.email,
        "level": latest_diagnostic.level if latest_diagnostic else student.level,
        "school_year": student.school_year,
        "region": student.region,
        "progression": round(float(progress_avg), 2),
        "latest_score": latest_attempt.percentage if latest_attempt else None,
        "last_activity": latest_activity(
            list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == student.id).order_by(CourseProgress.updated_at.desc()).limit(1))),
            [latest_attempt] if latest_attempt else [],
            list(db.scalars(select(QuizResult).where(QuizResult.user_id == student.id).order_by(QuizResult.created_at.desc()).limit(1))),
        ),
    }


def serialize_student(student: UserProfile) -> dict:
    return {
        "id": student.id,
        "full_name": student.full_name,
        "email": student.email,
        "school_year": student.school_year,
        "academic_year": student.academic_year,
        "study_stream": student.study_stream,
        "region": student.region,
        "prepared_subjects": student.prepared_subjects or [],
        "regional_exam_date": student.regional_exam_date,
    }


def serialize_progress(db: Session, row: CourseProgress) -> dict:
    course = db.get(Course, row.course_id)
    return {"course_id": row.course_id, "course_title": course.title if course else "Cours", "progress": row.progress, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def serialize_attempt(db: Session, attempt: AssessmentAttempt) -> dict:
    assessment = db.get(Assessment, attempt.assessment_id)
    return {"assessment_id": attempt.assessment_id, "title": assessment.title if assessment else "Evaluation", "score": attempt.percentage, "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None}


def serialize_quiz_result(db: Session, quiz: QuizResult) -> dict:
    course = db.get(Course, quiz.course_id)
    return {
        "course_id": quiz.course_id,
        "course_title": course.title if course else "Cours",
        "score": quiz.score,
        "correct": quiz.correct,
        "total": quiz.total,
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
    }


def serialize_diagnostic(result: DiagnosticResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "level": result.level,
        "score": result.score,
        "total": result.total,
        "correct_count": result.correct_count,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "recommendations": public_list(result.recommendations),
        "results_by_topic": public_list(result.results_by_topic),
    }


def serialize_regional_profile(profile: RegionalExamProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "academic_year": profile.academic_year,
        "region": profile.region,
        "stream": profile.stream,
        "exam_type": profile.exam_type,
        "exam_date": profile.exam_date,
        "readiness_score": profile.readiness_score,
        "readiness_details": profile.readiness_details or {},
        "days_remaining": days_remaining(profile.exam_date),
    }


def latest_diagnostic_result(db: Session, student_id: int) -> DiagnosticResult | None:
    return db.scalars(
        select(DiagnosticResult)
        .where(DiagnosticResult.user_id == student_id)
        .order_by(DiagnosticResult.created_at.desc())
    ).first()


def safe_parent_weaknesses(db: Session, student: UserProfile) -> dict:
    try:
        prediction = student_weakness_model_service.predict_student_weaknesses(db, student)
    except Exception:
        prediction = {}
    raw_competencies = prediction.get("competencies") if isinstance(prediction, dict) else []
    rows_by_name = {normalize_competence(row.get("competence")): row for row in raw_competencies if isinstance(row, dict)}
    competencies = []
    for label in PARENT_COMPETENCIES:
        row = rows_by_name.get(normalize_competence(label))
        competencies.append(public_competence_row(label, row))
    weak_points = [
        {
            "competence": row["competence"],
            "status": row["status"],
            "score": row["score"],
            "message": row["recommendation"],
        }
        for row in competencies
        if row["status"] in {"faible", "a_renforcer"}
    ]
    return {"competencies": competencies, "weak_points": weak_points}


def public_competence_row(label: str, row: dict | None) -> dict:
    if not row:
        return {
            "competence": label,
            "score": 0,
            "status": "non_evalue",
            "status_label": "Non évalué",
            "recommendation": f"Effectuer des exercices de {label.lower()} pour lancer l'analyse.",
        }
    status_value = str(row.get("status") or "non_evalue")
    return {
        "competence": label,
        "score": round(float(row.get("score_percentage") or row.get("score") or 0), 2),
        "status": status_value,
        "status_label": readable_status(status_value),
        "recommendation": str(row.get("recommendation") or simple_recommendation(label, status_value)),
    }


def build_parent_recommendations(competencies: list[dict], progress_rows: list[CourseProgress], attempts: list[AssessmentAttempt]) -> list[str]:
    recommendations = [row["recommendation"] for row in competencies if row["status"] in {"faible", "a_renforcer"}]
    if not progress_rows:
        recommendations.append("Commencer un chapitre de cours cette semaine pour installer un rythme régulier.")
    elif all(row.progress < 100 for row in progress_rows):
        recommendations.append("Terminer le chapitre actif avant de passer à un nouvel entraînement.")
    if attempts and attempts[0].percentage < 70:
        recommendations.append("Refaire une évaluation courte sur les compétences les moins maîtrisées.")
    if not recommendations:
        recommendations.append("Maintenir le rythme actuel avec un entraînement de révision par semaine.")
    return recommendations[:5]


def build_three_works_progress(progress_rows: list[CourseProgress]) -> list[dict]:
    works = [
        ("La Boîte à merveilles", ["boite", "merveilles"]),
        ("Antigone", ["antigone"]),
        ("Le Dernier Jour d'un condamné", ["dernier", "condamne", "condamné"]),
    ]
    rows = []
    for title, keywords in works:
        matching = [
            row.progress for row in progress_rows
            if any(keyword in str(row.chapters or "").lower() for keyword in keywords)
        ]
        rows.append({"title": title, "progress": round(sum(matching) / len(matching), 2) if matching else 0})
    return rows


def latest_activity(progress_rows: list[CourseProgress], attempts: list[AssessmentAttempt], quiz_rows: list[QuizResult]) -> str | None:
    dates: list[datetime] = []
    dates.extend(row.updated_at for row in progress_rows if row and row.updated_at)
    dates.extend(row.submitted_at for row in attempts if row and row.submitted_at)
    dates.extend(row.created_at for row in quiz_rows if row and row.created_at)
    latest = max(dates) if dates else None
    return latest.isoformat() if latest else None


def build_parent_overview(db: Session, student_id: int) -> dict:
    student = db.get(UserProfile, student_id)
    if student is None:
        return empty_parent_overview()
    weaknesses = safe_parent_weaknesses(db, student)
    progress_rows = list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == student_id)))
    attempts = list(db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.student_id == student_id, AssessmentAttempt.completed.is_(True)).order_by(AssessmentAttempt.submitted_at.desc())))
    latest_diagnostic = latest_diagnostic_result(db, student_id)
    return {
        "level": latest_diagnostic.level if latest_diagnostic else student.level,
        "global_progress": round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0,
        "latest_score": attempts[0].percentage if attempts else None,
        "priority_competence": next((row["competence"] for row in weaknesses["competencies"] if row["status"] in {"faible", "a_renforcer"}), None),
        "competencies": weaknesses["competencies"],
        "weak_points": weaknesses["weak_points"],
        "recommendations": build_parent_recommendations(weaknesses["competencies"], progress_rows, attempts),
        "last_activity": latest_activity(progress_rows, attempts, list(db.scalars(select(QuizResult).where(QuizResult.user_id == student_id).order_by(QuizResult.created_at.desc()).limit(1)))),
    }


def empty_parent_overview() -> dict:
    return {
        "level": None,
        "global_progress": 0,
        "latest_score": None,
        "priority_competence": None,
        "competencies": [public_competence_row(label, None) for label in PARENT_COMPETENCIES],
        "weak_points": [],
        "recommendations": [],
        "last_activity": None,
    }


def public_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def normalize_competence(value: str | None) -> str:
    return str(value or "").strip().lower().replace("é", "e").replace("è", "e").replace("ê", "e").replace("_", " ")


def readable_status(status_value: str) -> str:
    return {
        "faible": "Faible",
        "a_renforcer": "À renforcer",
        "maitrise": "Maîtrisé",
        "non_evalue": "Non évalué",
    }.get(status_value, "Non évalué")


def simple_recommendation(competence: str, status_value: str) -> str:
    if status_value == "maitrise":
        return f"{competence} : maintenir le niveau avec un exercice avancé."
    if status_value == "a_renforcer":
        return f"{competence} : refaire un entraînement ciblé."
    if status_value == "faible":
        return f"{competence} : revoir la leçon puis refaire des exercices guidés."
    return f"{competence} : réaliser quelques exercices pour obtenir une évaluation fiable."


def serialize_preferences(preferences: ParentNotificationPreference) -> dict:
    return {
        "email_enabled": preferences.email_enabled,
        "whatsapp_enabled": preferences.whatsapp_enabled,
        "weekly_summary_enabled": preferences.weekly_summary_enabled,
        "immediate_alerts_enabled": preferences.immediate_alerts_enabled,
        "preferred_language": preferences.preferred_language,
        "phone_number": preferences.phone_number,
        "phone_verified": preferences.phone_verified,
        "consent_recorded_at": preferences.consent_recorded_at.isoformat() if preferences.consent_recorded_at else None,
    }


def serialize_notification(notification: ParentNotification) -> dict:
    return {
        "id": notification.id,
        "student_id": notification.student_id,
        "event_type": notification.event_type,
        "title": notification.title,
        "message": notification.message,
        "severity": notification.severity,
        "status": notification.status,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
        "deliveries": [
            {
                "channel": delivery.channel,
                "status": delivery.status,
                "provider": delivery.provider,
                "error_message": delivery.error_message,
            }
            for delivery in notification.deliveries
        ],
    }


def parent_alerts(attempts: list[AssessmentAttempt], progress_rows: list[CourseProgress], study_paths: list[StudyPath]) -> list[dict]:
    alerts = []
    if attempts and attempts[0].percentage < 50:
        alerts.append({"type": "score_drop", "message": "Un resultat recent necessite un accompagnement."})
    if study_paths and study_paths[0].progress_percentage == 0:
        alerts.append({"type": "study_path_not_started", "message": "Un parcours personnalise n'a pas encore ete commence."})
    if not progress_rows:
        alerts.append({"type": "inactive", "message": "Aucune progression de cours n'est encore enregistree."})
    return alerts


def days_remaining(value: str | None) -> int | None:
    if not value:
        return None
    try:
        target = date.fromisoformat(value)
    except ValueError:
        return None
    return (target - date.today()).days
