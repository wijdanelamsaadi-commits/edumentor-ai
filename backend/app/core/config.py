from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BACKEND_DIR / ".env"


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and not os.environ.get(key):
            os.environ[key] = value


@lru_cache
def get_settings() -> dict:
    load_env_file()
    return {
        "database_url": os.environ.get("DATABASE_URL", ""),
        "groq_api_key": os.environ.get("GROQ_API_KEY", ""),
        "groq_model": os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
        "rag_score_threshold": _read_float("RAG_SCORE_THRESHOLD", 0.65),
        "firebase_credentials_path": os.environ.get("FIREBASE_CREDENTIALS_PATH", ""),
        "firebase_service_account_json": os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", ""),
        "firebase_project_id": os.environ.get("FIREBASE_PROJECT_ID", "yancode-2c5f9"),
    }


def _read_float(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback
