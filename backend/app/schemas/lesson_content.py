from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


BlockType = Literal[
    "heading",
    "paragraph",
    "bullet_list",
    "numbered_list",
    "definition",
    "key_point",
    "warning",
    "tip",
    "example",
    "methodology",
    "exercise",
    "solution",
    "correction",
    "code",
    "table",
    "quote",
    "image",
    "diagram",
    "formula",
    "key_points",
    "mini_assessment",
    "knowledge_check",
    "summary",
]


class LessonBlock(BaseModel):
    type: BlockType
    title: str | None = None
    content: str | list[str] | list[list[str]] | dict[str, Any] | None = None
    language: str | None = None
    diagram_type: str | None = None
    source_document_id: str | None = None
    source_page_start: int | None = Field(default=None, ge=1)
    source_page_end: int | None = Field(default=None, ge=1)
    generated_from_pdf: bool = False

    @field_validator("content")
    @classmethod
    def validate_content(cls, value, info):
        block_type = info.data.get("type")
        if block_type in {"heading", "paragraph", "definition", "key_point", "warning", "tip", "example", "methodology", "exercise", "solution", "correction", "code", "quote", "formula", "summary"}:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"Le bloc {block_type} attend un contenu texte")
        if block_type in {"bullet_list", "numbered_list", "key_points"}:
            if value is not None and not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
                raise ValueError(f"Le bloc {block_type} attend une liste de textes")
        if block_type == "table":
            if value is not None and not (isinstance(value, list) and all(isinstance(row, list) for row in value)):
                raise ValueError("Le bloc table attend une liste de lignes")
        if block_type in {"knowledge_check", "mini_assessment"}:
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"Le bloc {block_type} attend un objet")
        return value

    @field_validator("source_page_end")
    @classmethod
    def validate_page_order(cls, value, info):
        start = info.data.get("source_page_start")
        if value is not None and start is not None and value < start:
            raise ValueError("source_page_end doit etre superieur ou egal a source_page_start")
        return value


class StructuredContentPayload(BaseModel):
    blocks: list[LessonBlock]


def validate_structured_blocks(blocks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if blocks is None:
        return []
    return [LessonBlock.model_validate(block).model_dump(exclude_none=True) for block in blocks]
