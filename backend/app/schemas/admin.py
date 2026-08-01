from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.core.roles import UserRole


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AdminUserRead(OrmModel):
    id: int
    firebase_uid: str | None = None
    full_name: str
    email: str
    role: str
    level: str
    registration_date: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_activity: datetime | None = None


class RoleUpdate(BaseModel):
    role: UserRole


class StatusUpdate(BaseModel):
    status: Literal["active", "disabled"]


class CourseProfessorAssignment(BaseModel):
    professor_id: int | None = None


class AdminStatsOverview(BaseModel):
    total_users: int
    total_admins: int
    total_professors: int = 0
    total_students: int = 0
    total_regular_users: int
    total_courses: int
    total_diagnostics: int
    total_quizzes: int
    completed_courses: int
    total_chat_conversations: int
    total_notifications: int
    average_quiz_score: float
    level_distribution: dict[str, int]
    most_viewed_course: dict[str, Any] | None = None
    most_completed_course: dict[str, Any] | None = None
    hardest_quiz: dict[str, Any] | None = None
    recent_activity: list[dict[str, Any]]


class AdminAuditLogRead(OrmModel):
    id: int
    admin_user_id: int
    action: str
    target_type: str
    target_id: str | None = None
    before_data: Any = None
    after_data: Any = None
    created_at: datetime
