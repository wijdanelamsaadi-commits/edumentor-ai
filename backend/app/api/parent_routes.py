from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_parent
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.services import parent_service

router = APIRouter(prefix="/parent", tags=["Parent"])


@router.get("/dashboard")
def get_parent_dashboard(
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.list_children(db, current_parent)


@router.get("/students/{student_id}")
def get_parent_student_detail(
    student_id: int,
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.get_child_dashboard(db, current_parent, student_id)


@router.get("/students/{student_id}/progress")
def get_parent_student_progress(
    student_id: int,
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.get_child_progress(db, current_parent, student_id)


@router.get("/students/{student_id}/weaknesses")
def get_parent_student_weaknesses(
    student_id: int,
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.get_child_weaknesses(db, current_parent, student_id)


@router.get("/students/{student_id}/attempts")
def get_parent_student_attempts(
    student_id: int,
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.get_child_attempts(db, current_parent, student_id)


@router.get("/students/{student_id}/recommendations")
def get_parent_student_recommendations(
    student_id: int,
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.get_child_recommendations(db, current_parent, student_id)


@router.get("/notification-preferences")
def get_parent_notification_preferences(
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.get_preferences(db, current_parent)


@router.put("/notification-preferences")
def update_parent_notification_preferences(
    payload: dict,
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.update_preferences(db, current_parent, payload)


@router.get("/notifications")
def get_parent_notifications(
    db: Session = Depends(get_db),
    current_parent: UserProfile = Depends(get_current_parent),
) -> dict:
    return parent_service.list_notifications(db, current_parent)
