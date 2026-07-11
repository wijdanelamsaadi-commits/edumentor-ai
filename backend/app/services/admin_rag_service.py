from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any

from app.rag.document_store import get_documents_summary
from app.rag.vector_store import get_vector_store_status, initialize_vector_store

_status_lock = Lock()
_status: dict[str, Any] = {
    "state": "pending",
    "pdf_count": 0,
    "chunk_count": 0,
    "last_indexed_at": None,
    "error": None,
    "progress": 0,
}


def get_admin_rag_status() -> dict[str, Any]:
    with _status_lock:
        vector_status = get_vector_store_status()
        documents = get_documents_summary()
        return {
            **_status,
            "pdf_count": documents.get("pdf_count", _status.get("pdf_count", 0)),
            "chunk_count": vector_status.get("chunk_count") or _status.get("chunk_count", 0),
            "vector_store": vector_status,
        }


def mark_reindex_started() -> bool:
    with _status_lock:
        if _status["state"] == "running":
            return False
        _status.update({"state": "running", "error": None, "progress": 10})
        return True


def run_reindex() -> None:
    with _status_lock:
        _status["progress"] = 35

    try:
        documents = get_documents_summary()
        result = initialize_vector_store()
        with _status_lock:
            _status.update(
                {
                    "state": "success",
                    "pdf_count": documents.get("pdf_count", 0),
                    "chunk_count": result.get("chunk_count", 0),
                    "last_indexed_at": datetime.utcnow().isoformat(),
                    "error": None,
                    "progress": 100,
                }
            )
    except Exception as exc:  # pragma: no cover - surfaced through status endpoint
        with _status_lock:
            _status.update(
                {
                    "state": "failed",
                    "error": str(exc),
                    "progress": 100,
                }
            )
