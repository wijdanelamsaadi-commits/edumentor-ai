from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(160), unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(160), default="Wijdane Lamsadi")
    email: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(120), default="user")
    status: Mapped[str] = mapped_column(String(40), default="active")
    level: Mapped[str] = mapped_column(String(80), default="Intermediaire")
    registration_date: Mapped[str] = mapped_column(String(80), default="Mai 2024")
    photo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    diagnostics: Mapped[list["DiagnosticResult"]] = relationship(back_populates="user")
    course_progress: Mapped[list["CourseProgress"]] = relationship(back_populates="user")
    quiz_results: Mapped[list["QuizResult"]] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")
    chat_feedback: Mapped[list["ChatFeedback"]] = relationship(back_populates="user")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(220), index=True)
    level: Mapped[str] = mapped_column(String(80), default="Debutant")
    duration: Mapped[str] = mapped_column(String(80), default="2h")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    tag: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    exercises: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    information: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chapters: Mapped[list["CourseChapter"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseChapter.position")
    objectives: Mapped[list["CourseObjective"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseObjective.position")
    examples: Mapped[list["CourseExample"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseExample.position")
    skills: Mapped[list["CourseSkill"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseSkill.position")
    quiz: Mapped["Quiz | None"] = relationship(back_populates="course", cascade="all, delete-orphan", uselist=False)


class CourseChapter(Base):
    __tablename__ = "course_chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    duration: Mapped[str] = mapped_column(String(80), default="20 min")
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="locked")
    openable: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped["Course"] = relationship(back_populates="chapters")


class CourseObjective(Base):
    __tablename__ = "course_objectives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped["Course"] = relationship(back_populates="objectives")


class CourseExample(Base):
    __tablename__ = "course_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped["Course"] = relationship(back_populates="examples")


class CourseSkill(Base):
    __tablename__ = "course_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped["Course"] = relationship(back_populates="skills")


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220), default="Quiz du cours")
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    course: Mapped["Course"] = relationship(back_populates="quiz")
    questions: Mapped[list["QuizQuestion"]] = relationship(back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.position")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    choices: Mapped[list | dict] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")


class DiagnosticResult(Base):
    __tablename__ = "diagnostic_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, default=1)
    score: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[str] = mapped_column(String(80), default="Intermediaire")
    total: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    corrections: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["UserProfile"] = relationship(back_populates="diagnostics")


class CourseProgress(Base):
    __tablename__ = "course_progress"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_course_progress_user_course"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, default=1)
    course_id: Mapped[int] = mapped_column(Integer, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    chapters: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["UserProfile"] = relationship(back_populates="course_progress")


class QuizResult(Base):
    __tablename__ = "quiz_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, default=1)
    course_id: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    answers: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    corrections: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["UserProfile"] = relationship(back_populates="quiz_results")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, default=1)
    type: Mapped[str] = mapped_column(String(80), default="general")
    title: Mapped[str] = mapped_column(String(220))
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["UserProfile"] = relationship(back_populates="notifications")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, default=1)
    title: Mapped[str] = mapped_column(String(220), default="Nouvelle conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    user: Mapped["UserProfile"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sources: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class ChatFeedback(Base):
    __tablename__ = "chat_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, default=1)
    message_id: Mapped[str] = mapped_column(String(80), index=True)
    feedback: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["UserProfile"] = relationship(back_populates="chat_feedback")


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(120), index=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    before_data: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
