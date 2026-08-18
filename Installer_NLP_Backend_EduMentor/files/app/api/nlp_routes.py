from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.auth_dependencies import get_current_professor_or_admin
from app.models.persistence import UserProfile
from app.services.content_import_service import extract_pdf_pages
from app.services.nlp_model_service import (
    NLPModelError,
    analyze_text,
    health_status,
)

router = APIRouter(prefix="/nlp", tags=["NLP model"])

MAX_FILE_BYTES = 15 * 1024 * 1024
ALLOWED_SUFFIXES = {".json", ".tex", ".latex", ".pdf"}


class TextAnalysisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    max_units: int = Field(default=30, ge=1, le=100)


@router.get("/health")
def get_nlp_health() -> dict[str, Any]:
    return health_status()


@router.post("/analyze-text")
def analyze_nlp_text(
    payload: TextAnalysisRequest,
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict[str, Any]:
    try:
        result = analyze_text(payload.text, max_units=payload.max_units)
        return {
            "requested_by": current_user.uid,
            "input_format": "text",
            **result,
        }
    except (ValueError, NLPModelError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/analyze-file")
async def analyze_nlp_file(
    file: UploadFile = File(...),
    max_units: int = Form(default=30),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict[str, Any]:
    filename = file.filename or "uploaded_file"
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Format non supporté. Utilisez JSON, LaTeX ou PDF.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Le fichier est vide.")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Le fichier dépasse la taille maximale de 15 Mo.",
        )

    try:
        if suffix == ".json":
            text = _extract_json_text(raw)
        elif suffix in {".tex", ".latex"}:
            text = _extract_latex_text(raw)
        else:
            text = _extract_pdf_text(raw, suffix)

        result = analyze_text(text, max_units=max_units)
        return {
            "requested_by": current_user.uid,
            "filename": filename,
            "input_format": suffix.lstrip("."),
            "extracted_characters": len(text),
            **result,
        }
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"JSON invalide : {exc}",
        ) from exc
    except (UnicodeDecodeError, ValueError, NLPModelError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _extract_json_text(raw: bytes) -> str:
    payload = json.loads(raw.decode("utf-8-sig"))
    strings: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            clean = value.strip()
            if clean:
                strings.append(clean)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    text = "\n\n".join(strings)
    if not text.strip():
        raise ValueError("Le fichier JSON ne contient aucun texte exploitable.")
    return text


def _extract_latex_text(raw: bytes) -> str:
    text = raw.decode("utf-8-sig")

    # Remove comments while preserving escaped percent signs.
    text = re.sub(r"(?<!\\)%.*$", " ", text, flags=re.MULTILINE)

    # Preserve structural titles.
    text = re.sub(
        r"\\(?:part|chapter|section|subsection|subsubsection)\*?\{([^{}]*)\}",
        r"\n\n\1\n\n",
        text,
    )

    # Keep common command content before removing the remaining commands.
    for _ in range(4):
        text = re.sub(
            r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}",
            r"\1",
            text,
        )

    text = re.sub(r"\\begin\{[^{}]+\}|\\end\{[^{}]+\}", " ", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace(r"\%", "%").replace(r"\&", "&")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if not text.strip():
        raise ValueError("Le fichier LaTeX ne contient aucun texte exploitable.")
    return text.strip()


def _extract_pdf_text(raw: bytes, suffix: str) -> str:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as temp_file:
            temp_file.write(raw)
            temp_path = Path(temp_file.name)

        pages = extract_pdf_pages(temp_path)
        texts: list[str] = []

        for page in pages:
            if isinstance(page, str):
                value = page
            else:
                value = (
                    page.get("text")
                    or page.get("content")
                    or page.get("raw_text")
                    or ""
                )
            value = str(value).strip()
            if value:
                texts.append(value)

        text = "\n\n".join(texts)
        if not text.strip():
            raise ValueError(
                "Aucun texte n'a été extrait du PDF. "
                "Vérifiez le PDF ou la disponibilité de l'OCR."
            )
        return text
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
