from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.persistence import (
    Assessment,
    AssessmentAssignment,
    AssessmentAttempt,
    Course,
    CourseProgress,
    ParentNotification,
    ParentNotificationPreference,
    ParentStudentLink,
    RegionalExamProfile,
    RemediationPlan,
    StudyPath,
    UserProfile,
)
from app.services.notifications.parent_notification_service import get_or_create_preferences


def list_children(db: Session, parent: UserProfile) -> dict:
    links = active_links(db, parent.id)
    return {"children": [serialize_child_summary(db, link.student) for link in links]}


def get_child_dashboard(db: Session, parent: UserProfile, student_id: int) -> dict:
    student = get_linked_student(db, parent.id, student_id)
    progress_rows = list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == student.id).order_by(CourseProgress.updated_at.desc())))
    attempts = list(db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.student_id == student.id, AssessmentAttempt.completed.is_(True)).order_by(AssessmentAttempt.submitted_at.desc())))
    remediation_rows = list(db.scalars(select(RemediationPlan).where(RemediationPlan.student_id == student.id).order_by(RemediationPlan.created_at.desc())))
    study_paths = list(db.scalars(select(StudyPath).where(StudyPath.student_id == student.id, StudyPath.active.is_(True)).order_by(StudyPath.updated_at.desc())))
    regional = db.scalars(select(RegionalExamProfile).where(RegionalExamProfile.student_id == student.id).order_by(RegionalExamProfile.updated_at.desc())).first()

    return {
        "student": serialize_student(student),
        "progression": {
            "average": round(sum(row.progress for row in progress_rows) / len(progress_rows), 2) if progress_rows else 0,
            "courses_started": len(progress_rows),
            "courses": [serialize_progress(db, row) for row in progress_rows[:8]],
        },
        "results": {
            "recent_average": round(sum(attempt.percentage for attempt in attempts[:5]) / min(len(attempts), 5), 2) if attempts else 0,
            "attempts_count": len(attempts),
            "recent": [serialize_attempt(db, attempt) for attempt in attempts[:5]],
        },
        "remediations": [{"id": plan.id, "course_id": plan.course_id, "status": plan.status, "initial_score": plan.initial_score} for plan in remediation_rows[:5]],
        "study_paths": [{"id": path.id, "title": path.title, "status": path.status, "progress_percentage": path.progress_percentage} for path in study_paths[:5]],
        "regional_exam": serialize_regional_profile(regional),
        "alerts": parent_alerts(attempts, progress_rows, study_paths),
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
    return {
        "id": student.id,
        "full_name": student.full_name,
        "email": student.email,
        "school_year": student.school_year,
        "region": student.region,
        "progression": round(float(progress_avg), 2),
        "latest_score": latest_attempt.percentage if latest_attempt else None,
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
