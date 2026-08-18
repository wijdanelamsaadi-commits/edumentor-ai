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
        "groq_model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
        "rag_score_threshold": _read_float("RAG_SCORE_THRESHOLD", 0.65),
        "cors_allow_origins": os.environ.get("CORS_ALLOW_ORIGINS", ""),
        "docs_dir": os.environ.get("EDUMENTOR_DOCS_DIR", ""),
        "chroma_dir": os.environ.get("EDUMENTOR_CHROMA_DIR", ""),
        "fast_startup": _read_bool("EDUMENTOR_FAST_STARTUP", False),
        "firebase_credentials_path": os.environ.get("FIREBASE_CREDENTIALS_PATH", ""),
        "firebase_service_account_json": os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", ""),
        "firebase_project_id": os.environ.get("FIREBASE_PROJECT_ID", "yancode-2c5f9"),
        "ai_content_generation_enabled": _read_bool("AI_CONTENT_GENERATION_ENABLED", False),
        "ai_assessment_generation_enabled": _read_bool("AI_ASSESSMENT_GENERATION_ENABLED", False),
        "ai_remediation_enabled": _read_bool("AI_REMEDIATION_ENABLED", False),
        "ai_teacher_analysis_enabled": _read_bool("AI_TEACHER_ANALYSIS_ENABLED", False),
        "ai_parent_summary_enabled": _read_bool("AI_PARENT_SUMMARY_ENABLED", False),
        "ai_provider": os.environ.get("AI_PROVIDER", "groq"),
        "ai_model": os.environ.get("AI_MODEL", os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")),
        "ai_timeout_seconds": _read_float("AI_TIMEOUT_SECONDS", 20),
        "ai_max_retries": _read_int("AI_MAX_RETRIES", 1),
        "ai_max_source_chars": _read_int("AI_MAX_SOURCE_CHARS", 6000),
        "ai_max_tokens": _read_int("AI_MAX_TOKENS", 1200),
        "ai_duplicate_threshold": _read_float("AI_DUPLICATE_THRESHOLD", 0.82),
        "ai_variant_model": os.environ.get("AI_VARIANT_MODEL", os.environ.get("AI_MODEL", os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"))),
        "ai_variant_timeout_seconds": _read_float("AI_VARIANT_TIMEOUT_SECONDS", _read_float("AI_TIMEOUT_SECONDS", 20)),
        "ai_variant_max_retries": _read_int("AI_VARIANT_MAX_RETRIES", _read_int("AI_MAX_RETRIES", 1)),
        "ai_variant_max_rate_limit_retries": _read_int("AI_VARIANT_MAX_RATE_LIMIT_RETRIES", 3),
        "ai_variant_max_input_tokens": _read_int("AI_VARIANT_MAX_INPUT_TOKENS", 2200),
        "ai_variant_max_output_tokens": _read_int("AI_VARIANT_MAX_OUTPUT_TOKENS", 1800),
        "ai_variant_level_max_output_tokens": _read_int("AI_VARIANT_LEVEL_MAX_OUTPUT_TOKENS", _read_int("AI_VARIANT_MAX_OUTPUT_TOKENS", 1800)),
        "ai_variant_source_max_chars": _read_int("AI_VARIANT_SOURCE_MAX_CHARS", 8000),
        "ai_variant_max_sources": _read_int("AI_VARIANT_MAX_SOURCES", 5),
        "ai_groq_tpm_budget": _read_int("AI_GROQ_TPM_BUDGET", 5500),
        "ai_variant_min_interval_seconds": _read_float("AI_VARIANT_MIN_INTERVAL_SECONDS", 35),
    }


def _read_float(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


def _read_int(name: str, fallback: int) -> int:
    try:
        return int(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


def _read_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}
