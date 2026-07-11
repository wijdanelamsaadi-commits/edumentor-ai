from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import firebase_admin
from fastapi import HTTPException, status
from firebase_admin import auth, credentials

from app.core.config import BACKEND_DIR, get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_firebase_app() -> firebase_admin.App:
    if firebase_admin._apps:
        return firebase_admin.get_app()

    settings = get_settings()
    service_account_json = settings.get("firebase_service_account_json") or ""
    credentials_path = settings.get("firebase_credentials_path") or ""

    if service_account_json:
        certificate = credentials.Certificate(json.loads(service_account_json))
    elif credentials_path:
        path = Path(credentials_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        certificate = credentials.Certificate(str(path))
    else:
        raise RuntimeError(
            "Firebase Admin credentials are missing. Set FIREBASE_CREDENTIALS_PATH "
            "or FIREBASE_SERVICE_ACCOUNT_JSON in backend/.env."
        )

    return firebase_admin.initialize_app(
        certificate,
        {"projectId": settings.get("firebase_project_id") or "yancode-2c5f9"},
    )


def verify_firebase_id_token(id_token: str) -> dict:
    try:
        get_firebase_app()
        return auth.verify_id_token(id_token, clock_skew_seconds=10)
    except Exception as exc:
        logger.warning("Firebase ID token verification failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase token invalide ou expiré",
        ) from exc

