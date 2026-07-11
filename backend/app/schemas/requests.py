from pydantic import BaseModel, Field


class DiagnosticSubmission(BaseModel):
    answers: list[str] = Field(default_factory=list)


class QuizSubmission(BaseModel):
    answers: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    level: str = "Intermediaire"
    context: list[dict] = Field(default_factory=list)
