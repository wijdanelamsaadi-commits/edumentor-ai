from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.ai.ai_provider import AIProviderError
from app.services.ollama_variant_preview_service import (
    OllamaVariantTestRequest,
    test_ollama_variant_preview,
)

router = APIRouter(prefix="/ai", tags=["AI test"])


@router.post("/test-ollama-variant")
def test_ollama_variant(payload: OllamaVariantTestRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return test_ollama_variant_preview(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
