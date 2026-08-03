from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.roles import DEFAULT_ROLE


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(160), unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(160), default="Wijdane Lamsadi")
    email: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(120), default=DEFAULT_ROLE)
    status: Mapped[str] = mapped_column(String(40), default="active")
    level: Mapped[str] = mapped_column(String(80), default="Intermediaire")
    registration_date: Mapped[str] = mapped_column(String(80), default="Mai 2024")
    photo: Mapped[str | None] = mapped_column(Text, nullable=True)
    school_year: Mapped[str | None] = mapped_column(String(120), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(80), nullable=True)
    study_stream: Mapped[str | None] = mapped_column(String(160), nullable=True)
    region: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prepared_subjects: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    regional_exam_date: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    diagnostics: Mapped[list["DiagnosticResult"]] = relationship(back_populates="user")
    course_progress: Mapped[list["CourseProgress"]] = relationship(back_populates="user")
    quiz_results: Mapped[list["QuizResult"]] = relationship(back_populates="user")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")
    chat_feedback: Mapped[list["ChatFeedback"]] = relationship(back_populates="user")
    owned_courses: Mapped[list["Course"]] = relationship(back_populates="professor")
    personalized_lessons: Mapped[list["PersonalizedLesson"]] = relationship(back_populates="student")


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    courses: Mapped[list["Course"]] = relationship(back_populates="subject")


class EducationLevel(Base):
    __tablename__ = "education_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    courses: Mapped[list["Course"]] = relationship(back_populates="education_level")


class DifficultyLevel(Base):
    __tablename__ = "difficulty_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    courses: Mapped[list["Course"]] = relationship(back_populates="difficulty_level")


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
    content_import_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    content_import_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="published", index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    education_level_id: Mapped[int | None] = mapped_column(ForeignKey("education_levels.id"), nullable=True, index=True)
    difficulty_level_id: Mapped[int | None] = mapped_column(ForeignKey("difficulty_levels.id"), nullable=True, index=True)
    professor_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    estimated_duration: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prerequisites: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subject: Mapped["Subject | None"] = relationship(back_populates="courses")
    education_level: Mapped["EducationLevel | None"] = relationship(back_populates="courses")
    difficulty_level: Mapped["DifficultyLevel | None"] = relationship(back_populates="courses")
    professor: Mapped["UserProfile | None"] = relationship(back_populates="owned_courses")
    chapters: Mapped[list["CourseChapter"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseChapter.position")
    objectives: Mapped[list["CourseObjective"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseObjective.position")
    examples: Mapped[list["CourseExample"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseExample.position")
    skills: Mapped[list["CourseSkill"]] = relationship(back_populates="course", cascade="all, delete-orphan", order_by="CourseSkill.position")
    quiz: Mapped["Quiz | None"] = relationship(back_populates="course", cascade="all, delete-orphan", uselist=False)
    rag_documents: Mapped[list["RagDocument"]] = relationship(back_populates="course")


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
    structured_content: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    estimated_duration: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    description: Mapped[str] = mapped_column(Text, default="")
    passing_score: Mapped[int] = mapped_column(Integer, default=70)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    course: Mapped["Course"] = relationship(back_populates="quiz")
    questions: Mapped[list["QuizQuestion"]] = relationship(back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.position")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    choices: Mapped[list | dict] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    difficulty_level_id: Mapped[int | None] = mapped_column(ForeignKey("difficulty_levels.id"), nullable=True, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")
    chapter: Mapped["CourseChapter | None"] = relationship()
    difficulty_level: Mapped["DifficultyLevel | None"] = relationship()


class DiagnosticResult(Base):
    __tablename__ = "diagnostic_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True, default=1)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    education_level_id: Mapped[int | None] = mapped_column(ForeignKey("education_levels.id"), nullable=True, index=True)
    detected_difficulty_level_id: Mapped[int | None] = mapped_column(ForeignKey("difficulty_levels.id"), nullable=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[str] = mapped_column(String(80), default="Intermediaire")
    total: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    corrections: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    results_by_topic: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    results_by_difficulty: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["UserProfile"] = relationship(back_populates="diagnostics")
    subject: Mapped["Subject | None"] = relationship()
    education_level: Mapped["EducationLevel | None"] = relationship()
    detected_difficulty_level: Mapped["DifficultyLevel | None"] = relationship()


class DiagnosticQuestion(Base):
    __tablename__ = "diagnostic_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    education_level_id: Mapped[int | None] = mapped_column(ForeignKey("education_levels.id"), nullable=True, index=True)
    difficulty_level_id: Mapped[int] = mapped_column(ForeignKey("difficulty_levels.id"), index=True)
    topic: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    choices: Mapped[list | dict] = mapped_column(JSON)
    correct_answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.id"), nullable=True, index=True)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("pedagogical_package_import_jobs.id"), nullable=True, index=True)
    academic_year: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    source_chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    source_block_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    generation_method: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    question_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    imported_package_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_snapshot: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subject: Mapped["Subject"] = relationship()
    education_level: Mapped["EducationLevel | None"] = relationship()
    difficulty_level: Mapped["DifficultyLevel"] = relationship()
    classroom: Mapped["Classroom | None"] = relationship()
    import_job: Mapped["PedagogicalPackageImportJob | None"] = relationship()
    source_course: Mapped["Course | None"] = relationship(foreign_keys=[source_course_id])
    source_chapter: Mapped["CourseChapter | None"] = relationship(foreign_keys=[source_chapter_id])


class DiagnosticSession(Base):
    __tablename__ = "diagnostic_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    education_level_id: Mapped[int | None] = mapped_column(ForeignKey("education_levels.id"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_difficulty_level_id: Mapped[int | None] = mapped_column(ForeignKey("difficulty_levels.id"), nullable=True, index=True)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("pedagogical_package_import_jobs.id"), nullable=True, index=True)
    imported_package_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="started", index=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    student: Mapped["UserProfile"] = relationship()
    subject: Mapped["Subject"] = relationship()
    education_level: Mapped["EducationLevel | None"] = relationship()
    detected_difficulty_level: Mapped["DifficultyLevel | None"] = relationship()
    import_job: Mapped["PedagogicalPackageImportJob | None"] = relationship()
    answers: Mapped[list["DiagnosticAnswer"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class DiagnosticAnswer(Base):
    __tablename__ = "diagnostic_answers"
    __table_args__ = (UniqueConstraint("session_id", "question_id", name="uq_diagnostic_answer_session_question"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_questions.id"), index=True)
    selected_answer: Mapped[str] = mapped_column(Text)
    correct: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    session: Mapped["DiagnosticSession"] = relationship(back_populates="answers")
    question: Mapped["DiagnosticQuestion"] = relationship()


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


class RagDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        UniqueConstraint("course_id", "checksum_sha256", name="uq_rag_documents_course_checksum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    professor_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(260))
    stored_filename: Mapped[str] = mapped_column(String(260), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(120), default="application/pdf")
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(160), default="all-MiniLM-L6-v2")
    collection_name: Mapped[str] = mapped_column(String(180), default="edumentor_course_chunks")
    index_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    course: Mapped["Course"] = relationship(back_populates="rag_documents")
    subject: Mapped["Subject | None"] = relationship()
    professor: Mapped["UserProfile | None"] = relationship()
    jobs: Mapped[list["RagIndexJob"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class RagIndexJob(Base):
    __tablename__ = "rag_index_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("rag_documents.id"), nullable=True, index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    requested_by_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(40), default="index", index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks_created: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    document: Mapped["RagDocument | None"] = relationship(back_populates="jobs")
    course: Mapped["Course | None"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    requested_by: Mapped["UserProfile | None"] = relationship()


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(220), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subject: Mapped["Subject"] = relationship()
    course: Mapped["Course | None"] = relationship()
    chapter: Mapped["CourseChapter | None"] = relationship()


class Classroom(Base):
    __tablename__ = "classrooms"
    __table_args__ = (UniqueConstraint("code", name="uq_classrooms_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(220), index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    professor_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    education_level_id: Mapped[int | None] = mapped_column(ForeignKey("education_levels.id"), nullable=True, index=True)
    academic_year: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    professor: Mapped["UserProfile"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    education_level: Mapped["EducationLevel | None"] = relationship()
    memberships: Mapped[list["ClassroomMembership"]] = relationship(back_populates="classroom", cascade="all, delete-orphan")


class ClassroomMembership(Base):
    __tablename__ = "classroom_memberships"
    __table_args__ = (UniqueConstraint("classroom_id", "student_id", name="uq_classroom_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    classroom: Mapped["Classroom"] = relationship(back_populates="memberships")
    student: Mapped["UserProfile"] = relationship()


class ClassroomCourseAssignment(Base):
    __tablename__ = "classroom_course_assignments"
    __table_args__ = (UniqueConstraint("classroom_id", "course_id", name="uq_classroom_course_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    classroom: Mapped["Classroom"] = relationship()
    course: Mapped["Course"] = relationship()
    assigner: Mapped["UserProfile | None"] = relationship()


class MasteryThreshold(Base):
    __tablename__ = "mastery_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(160))
    min_percentage: Mapped[int] = mapped_column(Integer, default=0)
    max_percentage: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    professor_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.id"), nullable=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    title: Mapped[str] = mapped_column(String(240), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    assessment_type: Mapped[str] = mapped_column(String(40), default="initial", index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    difficulty_level_id: Mapped[int | None] = mapped_column(ForeignKey("difficulty_levels.id"), nullable=True, index=True)
    publication_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    professor: Mapped["UserProfile"] = relationship()
    classroom: Mapped["Classroom | None"] = relationship()
    course: Mapped["Course"] = relationship()
    subject: Mapped["Subject"] = relationship()
    difficulty_level: Mapped["DifficultyLevel | None"] = relationship()
    questions: Mapped[list["AssessmentQuestion"]] = relationship(back_populates="assessment", cascade="all, delete-orphan", order_by="AssessmentQuestion.order_index")
    assignments: Mapped[list["AssessmentAssignment"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")
    attempts: Mapped[list["AssessmentAttempt"]] = relationship(back_populates="assessment", cascade="all, delete-orphan")


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    choices: Mapped[list | dict] = mapped_column(JSON)
    correct_answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    difficulty_level_id: Mapped[int | None] = mapped_column(ForeignKey("difficulty_levels.id"), nullable=True, index=True)
    points: Mapped[float] = mapped_column(Float, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("rag_documents.id"), nullable=True, index=True)
    source_page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_attempts.id"), nullable=True, index=True)
    source_question_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_questions.id"), nullable=True, index=True)
    generation_method: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    adaptation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped["Assessment"] = relationship(back_populates="questions")
    chapter: Mapped["CourseChapter | None"] = relationship()
    skill: Mapped["Skill | None"] = relationship()
    difficulty_level: Mapped["DifficultyLevel | None"] = relationship()
    source_document: Mapped["RagDocument | None"] = relationship()
    source_attempt: Mapped["AssessmentAttempt | None"] = relationship(foreign_keys=[source_attempt_id])
    source_question: Mapped["AssessmentQuestion | None"] = relationship(remote_side=[id])


class AssessmentAssignment(Base):
    __tablename__ = "assessment_assignments"
    __table_args__ = (UniqueConstraint("assessment_id", "student_id", name="uq_assessment_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    classroom_id: Mapped[int | None] = mapped_column(ForeignKey("classrooms.id"), nullable=True, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(40), default="assigned", index=True)

    assessment: Mapped["Assessment"] = relationship(back_populates="assignments")
    student: Mapped["UserProfile"] = relationship()
    classroom: Mapped["Classroom | None"] = relationship()


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    percentage: Mapped[float] = mapped_column(Float, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)

    assessment: Mapped["Assessment"] = relationship(back_populates="attempts")
    student: Mapped["UserProfile"] = relationship()
    answers: Mapped[list["AssessmentAnswer"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_assessment_answer_question"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("assessment_attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("assessment_questions.id"), index=True)
    selected_answer: Mapped[str] = mapped_column(Text, default="")
    correct: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    points_awarded: Mapped[float] = mapped_column(Float, default=0)
    response_time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    attempt: Mapped["AssessmentAttempt"] = relationship(back_populates="answers")
    question: Mapped["AssessmentQuestion"] = relationship()


class RemediationPlan(Base):
    __tablename__ = "remediation_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    source_attempt_id: Mapped[int] = mapped_column(ForeignKey("assessment_attempts.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    initial_score: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    student: Mapped["UserProfile"] = relationship()
    source_attempt: Mapped["AssessmentAttempt"] = relationship()
    course: Mapped["Course"] = relationship()
    subject: Mapped["Subject"] = relationship()
    items: Mapped[list["RemediationItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan", order_by="RemediationItem.order_index")
    personalized_lessons: Mapped[list["PersonalizedLesson"]] = relationship(back_populates="plan", cascade="all, delete-orphan", order_by="PersonalizedLesson.created_at")


class RemediationItem(Base):
    __tablename__ = "remediation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    remediation_plan_id: Mapped[int] = mapped_column(ForeignKey("remediation_plans.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"), nullable=True, index=True)
    item_type: Mapped[str] = mapped_column(String(40), default="revision", index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    personalized_lesson_id: Mapped[int | None] = mapped_column(ForeignKey("personalized_lessons.id"), nullable=True, index=True)

    plan: Mapped["RemediationPlan"] = relationship(back_populates="items")
    chapter: Mapped["CourseChapter | None"] = relationship()
    skill: Mapped["Skill | None"] = relationship()
    personalized_lesson: Mapped["PersonalizedLesson | None"] = relationship(back_populates="remediation_items")


class PersonalizedLesson(Base):
    __tablename__ = "personalized_lessons"
    __table_args__ = (
        UniqueConstraint("remediation_plan_id", "chapter_id", "skill_id", name="uq_personalized_lesson_plan_chapter_skill"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    remediation_plan_id: Mapped[int] = mapped_column(ForeignKey("remediation_plans.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(260))
    objective: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    structured_content: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    generation_method: Mapped[str] = mapped_column(String(40), default="deterministic", index=True)
    status: Mapped[str] = mapped_column(String(40), default="ready", index=True)
    source_attempt_id: Mapped[int] = mapped_column(ForeignKey("assessment_attempts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    plan: Mapped["RemediationPlan"] = relationship(back_populates="personalized_lessons")
    student: Mapped["UserProfile"] = relationship(back_populates="personalized_lessons")
    course: Mapped["Course"] = relationship()
    subject: Mapped["Subject"] = relationship()
    chapter: Mapped["CourseChapter | None"] = relationship()
    skill: Mapped["Skill | None"] = relationship()
    source_attempt: Mapped["AssessmentAttempt"] = relationship()
    sources: Mapped[list["PersonalizedLessonSource"]] = relationship(back_populates="lesson", cascade="all, delete-orphan")
    remediation_items: Mapped[list["RemediationItem"]] = relationship(back_populates="personalized_lesson")


class PersonalizedLessonSource(Base):
    __tablename__ = "personalized_lesson_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    personalized_lesson_id: Mapped[int] = mapped_column(ForeignKey("personalized_lessons.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("rag_documents.id"), nullable=True, index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default="chapter", index=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    lesson: Mapped["PersonalizedLesson"] = relationship(back_populates="sources")
    document: Mapped["RagDocument | None"] = relationship()
    chapter: Mapped["CourseChapter | None"] = relationship()


class StudyPath(Base):
    __tablename__ = "study_paths"
    __table_args__ = (
        UniqueConstraint("remediation_plan_id", name="uq_study_paths_remediation_plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    remediation_plan_id: Mapped[int | None] = mapped_column(ForeignKey("remediation_plans.id"), nullable=True, index=True)
    source_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_attempts.id"), nullable=True, index=True)
    source_diagnostic_result_id: Mapped[int | None] = mapped_column(ForeignKey("diagnostic_results.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(260))
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    progress_percentage: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    student: Mapped["UserProfile"] = relationship()
    subject: Mapped["Subject"] = relationship()
    course: Mapped["Course"] = relationship()
    remediation_plan: Mapped["RemediationPlan | None"] = relationship()
    source_attempt: Mapped["AssessmentAttempt | None"] = relationship()
    source_diagnostic_result: Mapped["DiagnosticResult | None"] = relationship()
    items: Mapped[list["StudyPathItem"]] = relationship(back_populates="study_path", cascade="all, delete-orphan", order_by="StudyPathItem.order_index")


class StudyPathItem(Base):
    __tablename__ = "study_path_items"
    __table_args__ = (
        UniqueConstraint("study_path_id", "item_type", "entity_id", "order_index", name="uq_study_path_item_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_path_id: Mapped[int] = mapped_column(ForeignKey("study_paths.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    item_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(260))
    description: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    route: Mapped[str] = mapped_column(String(320), default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="locked", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)

    study_path: Mapped["StudyPath"] = relationship(back_populates="items")


class PedagogicalPackageImportJob(Base):
    __tablename__ = "pedagogical_package_import_jobs"
    __table_args__ = (
        UniqueConstraint("json_sha256", "latex_sha256", "classroom_id", "professor_id", name="uq_package_import_source_classroom"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    professor_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    education_level_id: Mapped[int | None] = mapped_column(ForeignKey("education_levels.id"), nullable=True, index=True)
    academic_year: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    schema_version: Mapped[str] = mapped_column(String(40), default="1.0")
    json_filename: Mapped[str] = mapped_column(String(260))
    latex_filename: Mapped[str | None] = mapped_column(String(260), nullable=True)
    json_sha256: Mapped[str] = mapped_column(String(64), index=True)
    latex_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    generation_method: Mapped[str] = mapped_column(String(80), default="deterministic")
    groq_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_summary: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapters_count: Mapped[int] = mapped_column(Integer, default=0)
    variants_count: Mapped[int] = mapped_column(Integer, default=0)
    questions_count: Mapped[int] = mapped_column(Integer, default=0)
    assigned_students_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    professor: Mapped["UserProfile"] = relationship()
    classroom: Mapped["Classroom"] = relationship()
    course: Mapped["Course | None"] = relationship()
    subject: Mapped["Subject | None"] = relationship()
    education_level: Mapped["EducationLevel | None"] = relationship()


class CourseLevelVariant(Base):
    __tablename__ = "course_level_variants"
    __table_args__ = (
        UniqueConstraint("course_id", "level", "source_hash", name="uq_course_variant_level_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    level: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(260))
    structured_content: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    source_chapter_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    source_block_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    source_work_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    generation_method: Mapped[str] = mapped_column(String(80), default="deterministic", index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    course: Mapped["Course"] = relationship()


class AIGenerationRecord(Base):
    __tablename__ = "ai_generation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generation_type: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("course_chapters.id"), nullable=True, index=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), default="deterministic", index=True)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["UserProfile | None"] = relationship(foreign_keys=[user_id])
    student: Mapped["UserProfile | None"] = relationship(foreign_keys=[student_id])
    course: Mapped["Course | None"] = relationship()
    chapter: Mapped["CourseChapter | None"] = relationship()


class RegionalExamProfile(Base):
    __tablename__ = "regional_exam_profiles"
    __table_args__ = (
        UniqueConstraint("student_id", "academic_year", "region", "stream", name="uq_regional_profile_student_year_region_stream"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    country: Mapped[str] = mapped_column(String(120), default="Maroc")
    cycle: Mapped[str] = mapped_column(String(80), default="1ere_bac", index=True)
    academic_year: Mapped[str] = mapped_column(String(80), index=True)
    region: Mapped[str] = mapped_column(String(160), index=True)
    stream: Mapped[str] = mapped_column(String(160), default="")
    exam_type: Mapped[str] = mapped_column(String(80), default="regional", index=True)
    exam_date: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prepared_subjects: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    readiness_score: Mapped[float] = mapped_column(Float, default=0)
    readiness_details: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student: Mapped["UserProfile"] = relationship()


class LiteraryWork(Base):
    __tablename__ = "literary_works"
    __table_args__ = (
        UniqueConstraint("course_id", "source_work_id", name="uq_literary_work_course_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    source_work_id: Mapped[str] = mapped_column(String(160), index=True)
    title: Mapped[str] = mapped_column(String(260), index=True)
    author: Mapped[str] = mapped_column(String(220), default="")
    genre: Mapped[str] = mapped_column(String(120), default="")
    context: Mapped[str] = mapped_column(Text, default="")
    chapters: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    target_metadata: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    course: Mapped["Course"] = relationship()


class ParentStudentLink(Base):
    __tablename__ = "parent_student_links"
    __table_args__ = (
        UniqueConstraint("parent_id", "student_id", name="uq_parent_student_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    relation: Mapped[str] = mapped_column(String(120), default="responsable")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent: Mapped["UserProfile"] = relationship(foreign_keys=[parent_id])
    student: Mapped["UserProfile"] = relationship(foreign_keys=[student_id])
    created_by: Mapped["UserProfile | None"] = relationship(foreign_keys=[created_by_user_id])


class ParentNotificationPreference(Base):
    __tablename__ = "parent_notification_preferences"
    __table_args__ = (
        UniqueConstraint("parent_id", name="uq_parent_notification_preferences_parent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_summary_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    immediate_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_language: Mapped[str] = mapped_column(String(40), default="fr")
    phone_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent: Mapped["UserProfile"] = relationship()


class ParentNotification(Base):
    __tablename__ = "parent_notifications"
    __table_args__ = (
        UniqueConstraint("parent_id", "student_id", "event_type", "dedupe_key", name="uq_parent_notification_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(260))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(40), default="info")
    dedupe_key: Mapped[str] = mapped_column(String(220), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    parent: Mapped["UserProfile"] = relationship(foreign_keys=[parent_id])
    student: Mapped["UserProfile"] = relationship(foreign_keys=[student_id])
    deliveries: Mapped[list["NotificationDelivery"]] = relationship(back_populates="notification", cascade="all, delete-orphan")


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("parent_notification_id", "channel", name="uq_notification_delivery_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_notification_id: Mapped[int] = mapped_column(ForeignKey("parent_notifications.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(80), default="pending", index=True)
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    notification: Mapped["ParentNotification"] = relationship(back_populates="deliveries")
