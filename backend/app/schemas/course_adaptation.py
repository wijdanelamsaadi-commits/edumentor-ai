from __future__ import annotations

from pydantic import BaseModel, Field


class CourseImportAdaptRequest(BaseModel):
    mode: str = Field(default="automatic_class")
    target_levels: list[str] = Field(default_factory=list)


class CourseImportSectionUpdate(BaseModel):
    adapted_content: str | None = None
    section_type: str | None = None
    target_level: str | None = None
    status: str | None = None


class CourseImportPublishRequest(BaseModel):
    auto_assign: bool = True
    adaptation_ids: list[int] = Field(default_factory=list)
