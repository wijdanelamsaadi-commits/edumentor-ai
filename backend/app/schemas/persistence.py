from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.roles import DEFAULT_ROLE


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserProfileBase(BaseModel):
    full_name: str = "Wijdane Lamsadi"
    email: str = "wijdane@edumentor.ai"
    role: str = DEFAULT_ROLE
    status: str = "active"
    level: str = "Intermediaire"
    registration_date: str = "Mai 2024"
    photo: str | None = None


class UserProfileCreate(UserProfileBase):
    pass


class UserProfileUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    level: str | None = None
    registration_date: str | None = None
    photo: str | None = None


class UserProfileRead(UserProfileBase, OrmModel):
    id: int
    firebase_uid: str | None = None
    created_at: datetime
    updated_at: datetime


class DiagnosticResultCreate(BaseModel):
    subject_id: int | None = None
    education_level_id: int | None = None
    detected_difficulty_level_id: int | None = None
    score: int = 0
    level: str = "Intermediaire"
    total: int = 0
    correct_count: int = 0
    corrections: Any = None
    results_by_topic: Any = None
    results_by_difficulty: Any = None
    recommendations: Any = None
    justification: str | None = None


class DiagnosticResultUpdate(DiagnosticResultCreate):
    pass


class DiagnosticResultRead(DiagnosticResultCreate, OrmModel):
    id: int
    user_id: int
    created_at: datetime


class CourseProgressCreate(BaseModel):
    course_id: int
    progress: int = 0
    chapters: Any = None


class CourseProgressUpdate(BaseModel):
    progress: int | None = None
    chapters: Any = None


class CourseProgressRead(CourseProgressCreate, OrmModel):
    id: int
    user_id: int
    updated_at: datetime


class QuizResultCreate(BaseModel):
    course_id: int
    score: int = 0
    correct: int = 0
    total: int = 0
    answers: Any = None
    corrections: Any = None
    recommendation: str | None = None


class QuizResultUpdate(QuizResultCreate):
    pass


class QuizResultRead(QuizResultCreate, OrmModel):
    id: int
    user_id: int
    created_at: datetime


class NotificationCreate(BaseModel):
    id: str | None = None
    type: str = "general"
    title: str
    message: str
    read: bool = False


class NotificationUpdate(BaseModel):
    type: str | None = None
    title: str | None = None
    message: str | None = None
    read: bool | None = None


class NotificationRead(OrmModel):
    id: str
    user_id: int
    type: str
    title: str
    message: str
    read: bool
    created_at: datetime


class ChatMessageCreate(BaseModel):
    id: str | None = None
    role: str
    content: str
    mode: str | None = None
    sources: Any = None


class ChatMessageUpdate(BaseModel):
    role: str | None = None
    content: str | None = None
    mode: str | None = None
    sources: Any = None


class ChatMessageRead(ChatMessageCreate, OrmModel):
    id: str
    session_id: str
    created_at: datetime


class ChatSessionCreate(BaseModel):
    id: str | None = None
    title: str = "Nouvelle conversation"
    messages: list[ChatMessageCreate] = Field(default_factory=list)


class ChatSessionUpdate(BaseModel):
    title: str | None = None
    messages: list[ChatMessageCreate] | None = None


class ChatSessionRead(OrmModel):
    id: str
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatFeedbackCreate(BaseModel):
    message_id: str
    feedback: str


class ChatFeedbackUpdate(ChatFeedbackCreate):
    pass


class ChatFeedbackRead(ChatFeedbackCreate, OrmModel):
    id: int
    user_id: int
    created_at: datetime
