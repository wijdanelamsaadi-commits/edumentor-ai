from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import NotificationDelivery, ParentNotification, ParentNotificationPreference, UserProfile
from app.services.notifications.email_provider import send_email
from app.services.notifications.whatsapp_provider import send_whatsapp


def get_or_create_preferences(db: Session, parent_id: int) -> ParentNotificationPreference:
    preferences = db.scalars(select(ParentNotificationPreference).where(ParentNotificationPreference.parent_id == parent_id)).first()
    if preferences:
        return preferences
    preferences = ParentNotificationPreference(parent_id=parent_id)
    db.add(preferences)
    db.flush()
    return preferences


def create_parent_notification(
    db: Session,
    parent: UserProfile,
    student: UserProfile,
    event_type: str,
    title: str,
    message: str,
    dedupe_key: str,
    severity: str = "info",
) -> ParentNotification:
    existing = db.scalars(
        select(ParentNotification).where(
            ParentNotification.parent_id == parent.id,
            ParentNotification.student_id == student.id,
            ParentNotification.event_type == event_type,
            ParentNotification.dedupe_key == dedupe_key,
        )
    ).first()
    if existing:
        return existing

    notification = ParentNotification(
        parent_id=parent.id,
        student_id=student.id,
        event_type=event_type,
        title=title,
        message=message,
        dedupe_key=dedupe_key,
        severity=severity,
    )
    db.add(notification)
    db.flush()
    enqueue_deliveries(db, parent, notification)
    return notification


def enqueue_deliveries(db: Session, parent: UserProfile, notification: ParentNotification) -> None:
    preferences = get_or_create_preferences(db, parent.id)
    if preferences.email_enabled:
        result = send_email(parent.email, notification.title, notification.message)
        db.add(NotificationDelivery(
            parent_notification_id=notification.id,
            channel="email",
            status=result["status"],
            provider=result.get("provider"),
            error_message=result.get("error_message"),
            sent_at=datetime.utcnow() if result["status"] == "sent" else None,
        ))
    if preferences.whatsapp_enabled:
        result = send_whatsapp(preferences.phone_number, notification.message)
        db.add(NotificationDelivery(
            parent_notification_id=notification.id,
            channel="whatsapp",
            status=result["status"],
            provider=result.get("provider"),
            error_message=result.get("error_message"),
            sent_at=datetime.utcnow() if result["status"] == "sent" else None,
        ))
