from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Level(str, Enum):
    debutant = "debutant"
    intermediaire = "intermediaire"
    avance = "avance"


class Task(str, Enum):
    comprehension = "comprehension"
    interpretation = "interpretation"
    langue = "langue"


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


class ContentTypeRequest(BaseModel):
    text: str = Field(default="", max_length=12000)
    instruction: str = Field(default="", max_length=3000)
    ui_section: str = Field(default="", max_length=100)
    context: str = Field(default="", max_length=8000)
    pair_role: str = Field(default="none", max_length=50)
    competence: str = Field(default="", max_length=100)
    language_skill: str = Field(default="", max_length=100)
    bloom_verb: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def validate_mode(self) -> "ContentTypeRequest":
        metadata_mode = bool(self.instruction.strip() and self.ui_section.strip())
        text_mode = bool(self.text.strip())
        if not metadata_mode and not text_mode:
            raise ValueError(
                "Fournir instruction + ui_section, ou text."
            )
        return self


class AdaptationRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=12000)
    source_level: Level
    target_level: Level
    content_type: str = Field(min_length=1, max_length=100)
    unit_title: str = Field(default="Unité pédagogique", max_length=300)
    adaptation_id: str = Field(default="new-adaptation", max_length=300)


class QuestionGenerationRequest(BaseModel):
    unit_id: str = Field(min_length=1, max_length=100)
    task: Task
    level: Level


class CorrectionRequest(BaseModel):
    question: str = Field(default="", max_length=5000)
    task: Task | None = None
    level: Level | None = None
    unit_id: str = Field(default="", max_length=100)
    pair_id: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_source(self) -> "CorrectionRequest":
        if self.pair_id.strip():
            return self
        if not self.question.strip() or self.task is None or self.level is None:
            raise ValueError(
                "Sans pair_id, fournir question, task et level."
            )
        return self


class AnalyzeAllRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    instruction: str = Field(default="", max_length=3000)
    ui_section: str = Field(default="", max_length=100)
    context: str = Field(default="", max_length=8000)
    pair_role: str = Field(default="none", max_length=50)
    competence: str = Field(default="", max_length=100)
    language_skill: str = Field(default="", max_length=100)
    bloom_verb: str = Field(default="", max_length=100)
    treat_as_exam_question: bool = False


class GenericResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]
    warnings: list[str] = []
