from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.roles import DEFAULT_ROLE, normalize_role
from app.models.persistence import (
    ChatFeedback,
    ChatMessage,
    ChatSession,
    CourseProgress,
    DiagnosticResult,
    Notification,
    QuizResult,
    UserProfile,
)
from app.services import diagnostic_service
from app.schemas.persistence import (
    ChatFeedbackCreate,
    ChatSessionCreate,
    CourseProgressCreate,
    CourseProgressUpdate,
    DiagnosticResultCreate,
    NotificationCreate,
    QuizResultCreate,
    UserProfileUpdate,
)

PLACEHOLDER_UID_PREFIXES = ("test-firebase-", "placeholder-", "demo-")


def get_or_create_user_from_firebase(db: Session, decoded_token: dict) -> UserProfile:
    firebase_uid = decoded_token.get("uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Firebase uid manquant")

    user = db.scalars(select(UserProfile).where(UserProfile.firebase_uid == firebase_uid)).first()
    if user is not None:
        normalized_role = normalize_role(user.role)
        if normalized_role != user.role:
            user.role = normalized_role
            return commit_user(db, user)
        return user

    email = normalize_email(decoded_token.get("email") or f"{firebase_uid}@firebase.local")
    full_name = decoded_token.get("name") or email.split("@")[0] or "Utilisateur EduMentor"

    email_user = get_user_by_email(db, email)
    if email_user is not None:
        if is_reusable_firebase_uid(email_user.firebase_uid):
            email_user.firebase_uid = firebase_uid
            email_user.email = email
            email_user.full_name = email_user.full_name or full_name
            email_user.role = normalize_role(email_user.role)
            return commit_user(db, email_user)

        raise HTTPException(
            status_code=409,
            detail="Un profil existe déjà avec cet email pour un autre compte Firebase. Veuillez lier les comptes.",
        )

    try:
        user = UserProfile(
            firebase_uid=firebase_uid,
            email=email,
            full_name=full_name,
            role=DEFAULT_ROLE,
            level="Intermediaire",
            registration_date="2026",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError as exc:
        db.rollback()
        recovered_user = db.scalars(select(UserProfile).where(UserProfile.firebase_uid == firebase_uid)).first()
        if recovered_user is not None:
            return recovered_user

        recovered_email_user = get_user_by_email(db, email)
        if recovered_email_user is not None and is_reusable_firebase_uid(recovered_email_user.firebase_uid):
            recovered_email_user.firebase_uid = firebase_uid
            return commit_user(db, recovered_email_user)

        raise HTTPException(
            status_code=409,
            detail="Impossible de créer le profil : email déjà associé à un autre compte Firebase.",
        ) from exc


def get_user_by_email(db: Session, email: str) -> UserProfile | None:
    return db.scalars(
        select(UserProfile).where(func.lower(UserProfile.email) == email.lower())
    ).first()


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def is_reusable_firebase_uid(firebase_uid: str | None) -> bool:
    if not firebase_uid:
        return True

    return firebase_uid.startswith(PLACEHOLDER_UID_PREFIXES)


def commit_user(db: Session, user: UserProfile) -> UserProfile:
    try:
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Impossible de lier ce profil : UID ou email déjà utilisé.",
        ) from exc


def get_profile(user: UserProfile) -> UserProfile:
    return user


def update_profile(db: Session, user: UserProfile, payload: UserProfileUpdate) -> UserProfile:
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "role":
            continue
        if field == "email" and value:
            value = normalize_email(value)
        setattr(user, field, value)
    try:
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cet email est déjà associé à un autre profil.",
        ) from exc


def get_latest_diagnostic(db: Session, user: UserProfile, subject_id: int | None = None) -> DiagnosticResult | None:
    query = select(DiagnosticResult).where(DiagnosticResult.user_id == user.id)
    if subject_id:
        query = query.where(DiagnosticResult.subject_id == subject_id)
    return db.scalars(query.order_by(DiagnosticResult.created_at.desc()).limit(1)).first()


def get_diagnostic_results_by_subject(db: Session, user: UserProfile) -> list[dict]:
    return diagnostic_service.get_latest_results_by_subject(db, user)


def create_diagnostic(db: Session, user: UserProfile, payload: DiagnosticResultCreate) -> DiagnosticResult:
    diagnostic = DiagnosticResult(user_id=user.id, **payload.model_dump())
    db.add(diagnostic)
    db.commit()
    db.refresh(diagnostic)
    return diagnostic


def get_progress(db: Session, user: UserProfile) -> list[CourseProgress]:
    return list(db.scalars(select(CourseProgress).where(CourseProgress.user_id == user.id)))


def create_progress(db: Session, user: UserProfile, payload: CourseProgressCreate) -> CourseProgress:
    if db.bind and db.bind.dialect.name == "postgresql":
        return upsert_progress(
            db,
            user,
            payload.course_id,
            {"progress": payload.progress, "chapters": payload.chapters},
        )

    existing = db.scalars(
        select(CourseProgress).where(
            CourseProgress.user_id == user.id,
            CourseProgress.course_id == payload.course_id,
        )
    ).first()
    if existing:
        existing.progress = payload.progress
        existing.chapters = payload.chapters
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    progress = CourseProgress(user_id=user.id, **payload.model_dump())
    db.add(progress)
    db.commit()
    db.refresh(progress)
    return progress


def update_progress(db: Session, user: UserProfile, course_id: int, payload: CourseProgressUpdate) -> CourseProgress:
    if db.bind and db.bind.dialect.name == "postgresql":
        return upsert_progress(db, user, course_id, payload.model_dump(exclude_unset=True))

    progress = db.scalars(
        select(CourseProgress).where(
            CourseProgress.user_id == user.id,
            CourseProgress.course_id == course_id,
        )
    ).first()
    if progress is None:
        progress = CourseProgress(user_id=user.id, course_id=course_id)
        db.add(progress)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(progress, field, value)
    progress.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(progress)
    return progress


def upsert_progress(db: Session, user: UserProfile, course_id: int, values: dict) -> CourseProgress:
    now = datetime.utcnow()
    insert_values = {
        "user_id": user.id,
        "course_id": course_id,
        "progress": values.get("progress", 0),
        "chapters": values.get("chapters"),
        "updated_at": now,
    }
    update_values = {"updated_at": now}
    if "progress" in values:
        update_values["progress"] = values["progress"]
    if "chapters" in values:
        update_values["chapters"] = values["chapters"]

    statement = (
        postgresql_insert(CourseProgress)
        .values(**insert_values)
        .on_conflict_do_update(
            constraint="uq_course_progress_user_course",
            set_=update_values,
        )
        .returning(CourseProgress.id)
    )

    progress_id = db.execute(statement).scalar_one()
    db.commit()
    return db.get(CourseProgress, progress_id)


def get_quiz_results(db: Session, user: UserProfile) -> list[QuizResult]:
    return list(
        db.scalars(
            select(QuizResult)
            .where(QuizResult.user_id == user.id)
            .order_by(QuizResult.created_at.desc())
        )
    )


def create_quiz_result(db: Session, user: UserProfile, payload: QuizResultCreate) -> QuizResult:
    result = QuizResult(user_id=user.id, **payload.model_dump())
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def get_notifications(db: Session, user: UserProfile) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
        )
    )


def create_notification(db: Session, user: UserProfile, payload: NotificationCreate) -> Notification:
    data = payload.model_dump()
    notification_id = data.pop("id") or str(uuid4())
    notification = Notification(id=notification_id, user_id=user.id, **data)
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def mark_notification_read(db: Session, user: UserProfile, notification_id: str) -> Notification:
    notification = _get_notification_or_404(db, user, notification_id)
    notification.read = True
    db.commit()
    db.refresh(notification)
    return notification


def delete_notification(db: Session, user: UserProfile, notification_id: str) -> dict:
    notification = _get_notification_or_404(db, user, notification_id)
    db.delete(notification)
    db.commit()
    return {"deleted": True, "id": notification_id}


def get_chat_sessions(db: Session, user: UserProfile) -> list[ChatSession]:
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .options(selectinload(ChatSession.messages))
            .order_by(ChatSession.updated_at.desc())
        )
    )


def create_chat_session(db: Session, user: UserProfile, payload: ChatSessionCreate) -> ChatSession:
    session = ChatSession(
        id=payload.id or str(uuid4()),
        user_id=user.id,
        title=payload.title,
    )
    for item in payload.messages:
        session.messages.append(
            ChatMessage(
                id=item.id or str(uuid4()),
                role=item.role,
                content=item.content,
                mode=item.mode,
                sources=item.sources,
            )
        )
    db.add(session)
    db.commit()
    db.refresh(session)
    return get_chat_session(db, user, session.id)


def get_chat_session(db: Session, user: UserProfile, session_id: str) -> ChatSession:
    session = db.scalars(
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.user_id == user.id)
        .options(selectinload(ChatSession.messages))
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation introuvable")
    return session


def delete_chat_session(db: Session, user: UserProfile, session_id: str) -> dict:
    session = get_chat_session(db, user, session_id)
    db.delete(session)
    db.commit()
    return {"deleted": True, "id": session_id}


def create_chat_feedback(db: Session, user: UserProfile, payload: ChatFeedbackCreate) -> ChatFeedback:
    feedback = ChatFeedback(user_id=user.id, **payload.model_dump())
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def _get_notification_or_404(db: Session, user: UserProfile, notification_id: str) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    return notification
