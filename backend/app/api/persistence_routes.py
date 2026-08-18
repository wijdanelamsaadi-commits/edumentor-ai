from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_admin, get_current_user
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.schemas.persistence import (
    ChatFeedbackCreate,
    ChatFeedbackRead,
    ChatSessionCreate,
    ChatSessionRead,
    CourseProgressCreate,
    CourseProgressRead,
    CourseProgressUpdate,
    DiagnosticResultCreate,
    DiagnosticResultRead,
    NotificationCreate,
    NotificationRead,
    QuizResultCreate,
    QuizResultRead,
    UserProfileRead,
    UserProfileUpdate,
)
from app.services import persistence_service

router = APIRouter(tags=["Persistence"])


@router.put("/profile", response_model=UserProfileRead)
def update_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.update_profile(db, current_user, payload)


@router.get("/profile", response_model=UserProfileRead)
def get_profile(current_user: UserProfile = Depends(get_current_user)):
    return persistence_service.get_profile(current_user)


@router.get("/diagnostic/result", response_model=DiagnosticResultRead | None)
def get_diagnostic_result(
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.get_latest_diagnostic(db, current_user, subject_id)


@router.get("/diagnostic/results")
def get_diagnostic_results(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.get_diagnostic_results_by_subject(db, current_user)


@router.post("/diagnostic/result", response_model=DiagnosticResultRead)
def create_diagnostic_result(
    payload: DiagnosticResultCreate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.create_diagnostic(db, current_user, payload)


@router.get("/progress", response_model=list[CourseProgressRead])
def get_progress(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.get_progress(db, current_user)


@router.post("/progress", response_model=CourseProgressRead)
def create_progress(
    payload: CourseProgressCreate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.create_progress(db, current_user, payload)


@router.put("/progress/{course_id}", response_model=CourseProgressRead)
def update_progress(
    course_id: int,
    payload: CourseProgressUpdate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.update_progress(db, current_user, course_id, payload)


@router.get("/quiz-results", response_model=list[QuizResultRead])
def get_quiz_results(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.get_quiz_results(db, current_user)


@router.post("/quiz-results", response_model=QuizResultRead)
def create_quiz_result(
    payload: QuizResultCreate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.create_quiz_result(db, current_user, payload)


@router.get("/notifications", response_model=list[NotificationRead])
def get_notifications(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.get_notifications(db, current_user)


@router.post("/notifications", response_model=NotificationRead)
def create_notification(
    payload: NotificationCreate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.create_notification(db, current_user, payload)


@router.put("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.mark_notification_read(db, current_user, notification_id)


@router.delete("/notifications/{notification_id}")
def delete_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.delete_notification(db, current_user, notification_id)


@router.get("/chat/sessions", response_model=list[ChatSessionRead])
def get_chat_sessions(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.get_chat_sessions(db, current_user)


@router.post("/chat/sessions", response_model=ChatSessionRead)
def create_chat_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.create_chat_session(db, current_user, payload)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionRead)
def get_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.get_chat_session(db, current_user, session_id)


@router.delete("/chat/sessions/{session_id}")
def delete_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.delete_chat_session(db, current_user, session_id)


@router.post("/chat/feedback", response_model=ChatFeedbackRead)
def create_chat_feedback(
    payload: ChatFeedbackCreate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    return persistence_service.create_chat_feedback(db, current_user, payload)


@router.get("/admin/ping")
def admin_ping(current_admin: UserProfile = Depends(get_current_admin)):
    return {"ok": True, "user_id": current_admin.id, "role": current_admin.role}
