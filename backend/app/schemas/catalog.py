from __future__ import annotations

from pydantic import BaseModel, Field


class SubjectPayload(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None
    description: str = ""
    icon: str | None = None
    active: bool = True
    display_order: int = 0


class EducationLevelPayload(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None
    description: str = ""
    active: bool = True
    display_order: int = 0


class DifficultyLevelPayload(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None
    active: bool = True
    display_order: int = 0
