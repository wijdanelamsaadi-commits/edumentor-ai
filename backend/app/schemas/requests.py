from pydantic import BaseModel, Field


class DiagnosticSubmission(BaseModel):
    answers: list[str] = Field(default_factory=list)


class QuizSubmission(BaseModel):
    answers: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    level: str = "Intermediaire"
    context: list[dict] = Field(default_factory=list)
    course_id: int | None = None
    subject_id: int | None = None
    session_id: str | None = None
    preferred_language: str | None = None
