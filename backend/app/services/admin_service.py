from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from math import ceil
from statistics import mean
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.roles import VALID_ROLES, UserRole, normalize_role
from app.models.persistence import (
    AdminAuditLog,
    ChatFeedback,
    ChatMessage,
    ChatSession,
    Course,
    CourseProgress,
    DiagnosticResult,
    Notification,
    NotificationDelivery,
    ParentNotification,
    ParentStudentLink,
    QuizResult,
    UserProfile,
)
from app.schemas.admin import AdminAuditLogRead, AdminUserRead
from app.services import course_service
from app.services.mock_data import COURSES
from app.services.notifications.parent_notification_service import create_parent_notification


def list_users(db: Session) -> list[AdminUserRead]:
    users = list(db.scalars(select(UserProfile).order_by(UserProfile.created_at.desc())))
    last_activity = get_last_activity_map(db, [user.id for user in users])
    return [to_admin_user(user, last_activity.get(user.id)) for user in users]


def get_user(db: Session, user_id: int) -> AdminUserRead:
    user = get_user_or_404(db, user_id)
    last_activity = get_last_activity_map(db, [user.id]).get(user.id)
    return to_admin_user(user, last_activity)


def create_parent_student_link(db: Session, admin: UserProfile, payload: dict) -> dict:
    ensure_admin_actor(admin)
    parent = get_user_or_404(db, int(payload.get("parent_id") or 0))
    student = get_user_or_404(db, int(payload.get("student_id") or 0))
    return create_parent_student_link_for_users(db, admin, parent, student, str(payload.get("relation") or "responsable"))


def create_parent_student_link_for_users(db: Session, admin: UserProfile, parent: UserProfile, student: UserProfile, relation: str = "responsable") -> dict:
    ensure_admin_actor(admin)
    if parent.id == student.id:
        raise HTTPException(status_code=422, detail="Un utilisateur ne peut pas etre lie a lui-meme")
    if parent.role != UserRole.PARENT.value:
        raise HTTPException(status_code=422, detail="Le compte parent doit avoir le role parent")
    if student.role != UserRole.STUDENT.value:
        raise HTTPException(status_code=422, detail="Le compte enfant doit avoir le role student")
    link = db.scalars(
        select(ParentStudentLink).where(
            ParentStudentLink.parent_id == parent.id,
            ParentStudentLink.student_id == student.id,
        )
    ).first()
    if link is None:
        link = ParentStudentLink(
            parent_id=parent.id,
            student_id=student.id,
            created_by_user_id=admin.id,
            relation=relation,
            status="active",
            verified_at=datetime.utcnow(),
        )
        db.add(link)
    elif link.status == "active":
        raise HTTPException(status_code=409, detail="Cet eleve est deja associe a ce parent")
    else:
        link.status = "active"
        link.verified_at = link.verified_at or datetime.utcnow()
    create_parent_notification(
        db,
        parent,
        student,
        "student_linked",
        "Compte eleve lie",
        f"Vous pouvez maintenant suivre la progression de {student.full_name}.",
        f"student-linked-{student.id}",
    )
    db.commit()
    db.refresh(link)
    create_audit_log(db, admin.id, "link_parent_student", "parent_student_link", str(link.id), None, serialize_parent_link(link))
    return serialize_parent_link(link)


def list_parent_student_links(db: Session) -> list[dict]:
    rows = list(db.scalars(select(ParentStudentLink).order_by(ParentStudentLink.created_at.desc())))
    return [serialize_parent_link(row) for row in rows]


def list_parent_students(db: Session, admin: UserProfile, parent_id: int) -> dict:
    ensure_admin_actor(admin)
    parent = get_user_or_404(db, parent_id)
    if parent.role != UserRole.PARENT.value:
        raise HTTPException(status_code=422, detail="Le compte selectionne doit avoir le role parent")
    rows = list(
        db.scalars(
            select(ParentStudentLink)
            .where(ParentStudentLink.parent_id == parent.id, ParentStudentLink.status == "active")
            .order_by(ParentStudentLink.created_at.desc())
        )
    )
    return {
        "parent": {
            "id": parent.id,
            "full_name": parent.full_name,
            "email": parent.email,
            "role": parent.role,
        },
        "children": [serialize_parent_link(row) for row in rows],
    }


def link_parent_student(db: Session, admin: UserProfile, parent_id: int, student_id: int) -> dict:
    parent = get_user_or_404(db, parent_id)
    student = get_user_or_404(db, student_id)
    return create_parent_student_link_for_users(db, admin, parent, student)


def unlink_parent_student(db: Session, admin: UserProfile, parent_id: int, student_id: int) -> dict:
    ensure_admin_actor(admin)
    parent = get_user_or_404(db, parent_id)
    student = get_user_or_404(db, student_id)
    if parent.role != UserRole.PARENT.value:
        raise HTTPException(status_code=422, detail="Le compte parent doit avoir le role parent")
    if student.role != UserRole.STUDENT.value:
        raise HTTPException(status_code=422, detail="Le compte enfant doit avoir le role student")
    link = db.scalars(
        select(ParentStudentLink).where(
            ParentStudentLink.parent_id == parent.id,
            ParentStudentLink.student_id == student.id,
            ParentStudentLink.status == "active",
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Association parent-eleve introuvable")
    before = serialize_parent_link(link)
    link.status = "inactive"
    db.commit()
    db.refresh(link)
    create_audit_log(db, admin.id, "unlink_parent_student", "parent_student_link", str(link.id), before, serialize_parent_link(link))
    return {"status": "unlinked", "parent_id": parent.id, "student_id": student.id}


def list_parent_notifications(db: Session) -> list[dict]:
    rows = list(db.scalars(select(ParentNotification).order_by(ParentNotification.created_at.desc()).limit(200)))
    return [serialize_parent_notification(row) for row in rows]


def retry_parent_notification_delivery(db: Session, admin: UserProfile, delivery_id: int) -> dict:
    ensure_admin_actor(admin)
    delivery = db.get(NotificationDelivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Livraison introuvable")
    before = {"status": delivery.status, "error_message": delivery.error_message}
    delivery.status = "pending_configuration"
    delivery.error_message = "Relance demandee; credentials fournisseur a verifier."
    db.commit()
    create_audit_log(db, admin.id, "retry_parent_notification", "notification_delivery", str(delivery.id), before, {"status": delivery.status})
    return {"id": delivery.id, "status": delivery.status, "channel": delivery.channel}


def update_user_role(db: Session, admin: UserProfile, user_id: int, role: str) -> AdminUserRead:
    ensure_admin_actor(admin)
    role = normalize_role(role)
    if role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="Role invalide")

    user = get_user_or_404(db, user_id)
    if user.role == UserRole.ADMIN.value and role != UserRole.ADMIN.value and count_active_admins(db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de retrograder le dernier administrateur actif.",
        )

    before = user_to_log(user)
    user.role = role
    db.commit()
    db.refresh(user)
    create_audit_log(db, admin.id, "update_role", "user", str(user.id), before, user_to_log(user))
    return get_user(db, user.id)


def update_user_status(db: Session, admin: UserProfile, user_id: int, status_value: str) -> AdminUserRead:
    ensure_admin_actor(admin)
    if status_value not in {"active", "disabled"}:
        raise HTTPException(status_code=422, detail="Statut invalide")

    user = get_user_or_404(db, user_id)
    if user.role == UserRole.ADMIN.value and status_value == "disabled" and count_active_admins(db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de desactiver le dernier administrateur actif.",
        )

    before = user_to_log(user)
    user.status = status_value
    db.commit()
    db.refresh(user)
    action = "disable_user" if status_value == "disabled" else "enable_user"
    create_audit_log(db, admin.id, action, "user", str(user.id), before, user_to_log(user))
    return get_user(db, user.id)


def assign_course_professor(db: Session, admin: UserProfile, course_id: int, professor_id: int | None) -> dict:
    ensure_admin_actor(admin)
    course = course_service.get_course_model(db, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours introuvable")

    before = {
        "course_id": course.id,
        "professor_id": course.professor_id,
        "professor": course_service.serialize_professor_ref(course.professor),
    }
    professor = None
    if professor_id is not None:
        professor = db.get(UserProfile, professor_id)
        if professor is None:
            raise HTTPException(status_code=404, detail="Professeur introuvable")
        if professor.role != UserRole.PROFESSOR.value:
            raise HTTPException(status_code=422, detail="L'utilisateur selectionne doit avoir le role professor")
    course.professor_id = professor_id
    course.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(course)
    after = {
        "course_id": course.id,
        "professor_id": course.professor_id,
        "professor": course_service.serialize_professor_ref(professor),
    }
    create_audit_log(db, admin.id, "assign_course_professor", "course", str(course.id), before, after)
    return course_service.get_course_detail(db, course.id, include_unpublished=True)


def delete_user(db: Session, admin: UserProfile, user_id: int) -> dict:
    ensure_admin_actor(admin)
    user = get_user_or_404(db, user_id)

    if user.role == UserRole.ADMIN.value and count_active_admins(db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de supprimer le dernier administrateur actif.",
        )

    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de supprimer votre propre compte administrateur.",
        )

    before = user_to_log(user)
    db.query(DiagnosticResult).filter(DiagnosticResult.user_id == user.id).delete(synchronize_session=False)
    db.query(CourseProgress).filter(CourseProgress.user_id == user.id).delete(synchronize_session=False)
    db.query(QuizResult).filter(QuizResult.user_id == user.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(ChatFeedback).filter(ChatFeedback.user_id == user.id).delete(synchronize_session=False)
    for chat_session in db.scalars(select(ChatSession).where(ChatSession.user_id == user.id)):
        db.delete(chat_session)
    db.delete(user)
    db.add(AdminAuditLog(
        admin_user_id=admin.id,
        action="delete_user",
        target_type="user",
        target_id=str(user_id),
        before_data=before,
        after_data=None,
    ))
    db.commit()

    return {
        "deleted": True,
        "user_id": user_id,
        "scope": "postgresql_only",
        "message": "Le profil et ses donnees metier PostgreSQL ont ete supprimes. Le compte Firebase Auth n'est pas supprime dans cette phase.",
    }


def get_overview(db: Session) -> dict:
    users = list(db.scalars(select(UserProfile)))
    courses = list(db.scalars(select(Course)))
    diagnostics = list(db.scalars(select(DiagnosticResult)))
    quiz_results = list(db.scalars(select(QuizResult)))
    progress_rows = list(db.scalars(select(CourseProgress)))
    notifications_count = db.scalar(select(func.count(Notification.id))) or 0
    chat_count = db.scalar(select(func.count(ChatSession.id))) or 0

    level_distribution = {"Debutant": 0, "Intermediaire": 0, "Avance": 0}
    for diagnostic in diagnostics:
        key = normalize_level(diagnostic.level)
        level_distribution[key] = level_distribution.get(key, 0) + 1

    course_lookup = build_course_lookup(courses)
    viewed_counter = Counter(row.course_id for row in progress_rows)
    completed_counter = Counter(row.course_id for row in progress_rows if row.progress >= 100)
    quiz_by_course = build_quiz_score_map(quiz_results)

    hardest_course_id = None
    hardest_average = None
    if quiz_by_course:
        hardest_course_id, scores = min(quiz_by_course.items(), key=lambda item: mean(item[1]))
        hardest_average = round(mean(scores), 2)

    return {
        "total_users": len(users),
        "total_admins": sum(1 for user in users if user.role == UserRole.ADMIN.value),
        "total_professors": sum(1 for user in users if user.role == UserRole.PROFESSOR.value),
        "total_students": sum(1 for user in users if user.role == UserRole.STUDENT.value),
        "total_regular_users": sum(1 for user in users if user.role in {UserRole.STUDENT.value, UserRole.PROFESSOR.value}),
        "total_courses": len(courses) or len(COURSES),
        "total_diagnostics": len(diagnostics),
        "total_quizzes": len(quiz_results),
        "completed_courses": sum(1 for row in progress_rows if row.progress >= 100),
        "total_chat_conversations": chat_count,
        "total_notifications": notifications_count,
        "average_quiz_score": round(mean([result.score for result in quiz_results]), 2) if quiz_results else 0,
        "level_distribution": level_distribution,
        "most_viewed_course": course_counter_to_dict(viewed_counter, course_lookup),
        "most_completed_course": course_counter_to_dict(completed_counter, course_lookup),
        "hardest_quiz": course_metric_to_dict(hardest_course_id, hardest_average, course_lookup),
        "recent_activity": build_recent_activity(diagnostics, quiz_results, progress_rows),
    }


def get_users_stats(db: Session) -> dict:
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    users = list(db.scalars(select(UserProfile)))
    active_ids = set(get_last_activity_map(db, [user.id for user in users]).keys())

    by_role = Counter(user.role for user in users)
    by_status = Counter(user.status or "active" for user in users)
    new_by_day: Counter[str] = Counter()
    for user in users:
        if user.created_at >= since:
            new_by_day[user.created_at.date().isoformat()] += 1

    return {
        "total_users": len(users),
        "active_users": len(active_ids),
        "new_users_7d": sum(1 for user in users if user.created_at >= since),
        "by_role": dict(by_role),
        "by_status": dict(by_status),
        "new_users_by_day": [{"date": key, "count": count} for key, count in sorted(new_by_day.items())],
    }


def get_courses_stats(db: Session) -> dict:
    courses = list(db.scalars(select(Course)))
    progress_rows = list(db.scalars(select(CourseProgress)))
    course_lookup = build_course_lookup(courses)
    viewed_counter = Counter(row.course_id for row in progress_rows)
    completed_counter = Counter(row.course_id for row in progress_rows if row.progress >= 100)
    average_progress = round(mean([row.progress for row in progress_rows]), 2) if progress_rows else 0

    return {
        "total_courses": len(courses),
        "published_courses": sum(1 for course in courses if course.published),
        "draft_courses": sum(1 for course in courses if not course.published),
        "average_progress": average_progress,
        "most_viewed": counters_to_list(viewed_counter, course_lookup),
        "most_completed": counters_to_list(completed_counter, course_lookup),
    }


def get_quizzes_stats(db: Session) -> dict:
    results = list(db.scalars(select(QuizResult)))
    course_lookup = build_course_lookup(list(db.scalars(select(Course))))
    scores = [result.score for result in results]
    by_course = build_quiz_score_map(results)

    hardest = []
    for course_id, course_scores in by_course.items():
        hardest.append({
            "course_id": course_id,
            "title": course_lookup.get(course_id, {}).get("title", f"Cours {course_id}"),
            "average_score": round(mean(course_scores), 2),
            "attempts": len(course_scores),
        })
    hardest.sort(key=lambda item: item["average_score"])

    return {
        "quiz_attempts": len(results),
        "average_score": round(mean(scores), 2) if scores else 0,
        "success_rate": round((sum(1 for score in scores if score >= 70) / len(scores)) * 100, 2) if scores else 0,
        "hardest_quizzes": hardest[:6],
    }


def get_chatbot_stats(db: Session) -> dict:
    conversations = db.scalar(select(func.count(ChatSession.id))) or 0
    messages = list(db.scalars(select(ChatMessage)))
    feedback = list(db.scalars(select(ChatFeedback)))
    assistant_modes = Counter(message.mode or "unknown" for message in messages if message.role == "assistant")

    return {
        "conversations": conversations,
        "messages": len(messages),
        "questions": sum(1 for message in messages if message.role == "user"),
        "rag_questions": assistant_modes.get("rag_semantic", 0),
        "groq_questions": assistant_modes.get("general", 0),
        "out_of_scope_questions": assistant_modes.get("out_of_scope", 0),
        "feedback": dict(Counter(item.feedback for item in feedback)),
    }


def create_audit_log(
    db: Session,
    admin_user_id: int,
    action: str,
    target_type: str,
    target_id: str | None = None,
    before_data: Any = None,
    after_data: Any = None,
) -> AdminAuditLogRead:
    log = AdminAuditLog(
        admin_user_id=admin_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_data=make_json_safe(before_data),
        after_data=make_json_safe(after_data),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return AdminAuditLogRead.model_validate(log)


def make_json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    return value


def list_audit_logs(
    db: Session,
    search: str = "",
    action: str = "all",
    target_type: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(1, page)
    page_size = min(max(5, page_size), 100)
    query = select(AdminAuditLog)

    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(
            AdminAuditLog.action.ilike(pattern),
            AdminAuditLog.target_type.ilike(pattern),
            AdminAuditLog.target_id.ilike(pattern),
        ))
    if action != "all":
        query = query.where(AdminAuditLog.action == action)
    if target_type != "all":
        query = query.where(AdminAuditLog.target_type == target_type)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    logs = list(
        db.scalars(
            query.order_by(AdminAuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    return {
        "items": [AdminAuditLogRead.model_validate(log) for log in logs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, ceil(total / page_size)) if total else 1,
    }


def get_user_or_404(db: Session, user_id: int) -> UserProfile:
    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return user


def count_admins(db: Session) -> int:
    return db.scalar(select(func.count(UserProfile.id)).where(UserProfile.role == UserRole.ADMIN.value)) or 0


def ensure_admin_actor(admin: UserProfile) -> None:
    if admin.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action reservee aux administrateurs.",
        )


def count_active_admins(db: Session) -> int:
    return db.scalar(
        select(func.count(UserProfile.id)).where(
            UserProfile.role == UserRole.ADMIN.value,
            UserProfile.status != "disabled",
        )
    ) or 0


def get_last_activity_map(db: Session, user_ids: list[int]) -> dict[int, datetime]:
    if not user_ids:
        return {}

    activity: dict[int, datetime] = {}
    sources = [
        (DiagnosticResult.user_id, DiagnosticResult.created_at),
        (CourseProgress.user_id, CourseProgress.updated_at),
        (QuizResult.user_id, QuizResult.created_at),
        (Notification.user_id, Notification.created_at),
        (ChatSession.user_id, ChatSession.updated_at),
    ]

    for user_column, date_column in sources:
        rows = db.execute(
            select(user_column, func.max(date_column))
            .where(user_column.in_(user_ids))
            .group_by(user_column)
        )
        for user_id, date_value in rows:
            if date_value and (user_id not in activity or date_value > activity[user_id]):
                activity[user_id] = date_value

    return activity


def to_admin_user(user: UserProfile, last_activity: datetime | None) -> AdminUserRead:
    return AdminUserRead(
        id=user.id,
        firebase_uid=user.firebase_uid,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        level=user.level,
        registration_date=user.registration_date,
        status=user.status or "active",
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_activity=last_activity,
    )


def user_to_log(user: UserProfile) -> dict[str, Any]:
    return {
        "id": user.id,
        "firebase_uid": user.firebase_uid,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "level": user.level,
    }


def build_course_lookup(courses: list[Course]) -> dict[int, dict]:
    if courses:
        return {course.id: {"title": course.title} for course in courses}
    return {course["id"]: course for course in COURSES}


def build_quiz_score_map(quiz_results: list[QuizResult]) -> dict[int, list[int]]:
    quiz_by_course: dict[int, list[int]] = {}
    for result in quiz_results:
        quiz_by_course.setdefault(result.course_id, []).append(result.score)
    return quiz_by_course


def counters_to_list(counter: Counter, course_lookup: dict[int, dict]) -> list[dict[str, Any]]:
    return [
        {
            "course_id": course_id,
            "title": course_lookup.get(course_id, {}).get("title", f"Cours {course_id}"),
            "count": count,
        }
        for course_id, count in counter.most_common(6)
    ]


def course_counter_to_dict(counter: Counter, course_lookup: dict[int, dict]) -> dict[str, Any] | None:
    if not counter:
        return None

    course_id, count = counter.most_common(1)[0]
    course = course_lookup.get(course_id, {})
    return {"course_id": course_id, "title": course.get("title", f"Cours {course_id}"), "count": count}


def course_metric_to_dict(course_id: int | None, value: float | None, course_lookup: dict[int, dict]) -> dict[str, Any] | None:
    if course_id is None:
        return None

    course = course_lookup.get(course_id, {})
    return {"course_id": course_id, "title": course.get("title", f"Cours {course_id}"), "average_score": value}


def build_recent_activity(
    diagnostics: list[DiagnosticResult],
    quiz_results: list[QuizResult],
    progress_rows: list[CourseProgress],
) -> list[dict[str, Any]]:
    activity: list[dict[str, Any]] = []

    activity.extend({
        "type": "diagnostic",
        "label": f"Diagnostic niveau {item.level}",
        "user_id": item.user_id,
        "date": item.created_at,
    } for item in diagnostics)
    activity.extend({
        "type": "quiz",
        "label": f"Quiz cours {item.course_id} - score {item.score}%",
        "user_id": item.user_id,
        "date": item.created_at,
    } for item in quiz_results)
    activity.extend({
        "type": "progress",
        "label": f"Progression cours {item.course_id} - {item.progress}%",
        "user_id": item.user_id,
        "date": item.updated_at,
    } for item in progress_rows)

    return sorted(activity, key=lambda item: item["date"], reverse=True)[:10]


def normalize_level(level: str) -> str:
    clean = str(level or "").lower()
    if "debut" in clean or "début" in clean:
        return "Debutant"
    if "avanc" in clean:
        return "Avance"
    return "Intermediaire"


def serialize_parent_link(link: ParentStudentLink) -> dict:
    return {
        "id": link.id,
        "parent_id": link.parent_id,
        "parent_name": link.parent.full_name if link.parent else None,
        "parent_email": link.parent.email if link.parent else None,
        "student_id": link.student_id,
        "student_name": link.student.full_name if link.student else None,
        "student_email": link.student.email if link.student else None,
        "relation": link.relation,
        "status": link.status,
        "verified_at": link.verified_at.isoformat() if link.verified_at else None,
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


def serialize_parent_notification(notification: ParentNotification) -> dict:
    return {
        "id": notification.id,
        "parent_id": notification.parent_id,
        "student_id": notification.student_id,
        "event_type": notification.event_type,
        "title": notification.title,
        "message": notification.message,
        "severity": notification.severity,
        "status": notification.status,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
        "deliveries": [
            {
                "id": delivery.id,
                "channel": delivery.channel,
                "status": delivery.status,
                "provider": delivery.provider,
                "error_message": delivery.error_message,
                "sent_at": delivery.sent_at.isoformat() if delivery.sent_at else None,
            }
            for delivery in notification.deliveries
        ],
    }
