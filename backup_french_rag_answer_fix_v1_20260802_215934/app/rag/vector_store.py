from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from threading import Lock
from time import time
from typing import Any

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from app.rag.document_store import RagChunk, get_chunks, load_course_documents

CHROMA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"
COLLECTION_NAME = "edumentor_course_chunks"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

_lock = Lock()
_client: Any = None
_collection: Any = None
_embedding_model: Any = None
_index_status: dict[str, Any] = {
    "ready": False,
    "mode": "rag_semantic",
    "collection": COLLECTION_NAME,
    "embedding_model": EMBEDDING_MODEL_NAME,
    "embedding_backend": "sentence-transformers",
    "chunk_count": 0,
    "error": None,
}


def initialize_vector_store() -> dict[str, Any]:
    """Rebuild the ChromaDB index from the current PDF chunks.

    A temporary collection is built first so semantic_search can keep using the
    previous collection until the new one is ready.
    """
    global _client, _collection

    try:
        load_course_documents()
        chunks = get_chunks()
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)

        client = _get_chromadb().PersistentClient(path=str(CHROMA_DIR))
        temp_name = f"{COLLECTION_NAME}_building_{int(time())}"
        try:
            client.delete_collection(temp_name)
        except Exception:
            pass

        temp_collection = client.get_or_create_collection(
            name=temp_name,
            metadata={
                "description": "EduMentor AI course PDF chunks",
                "embedding_model": EMBEDDING_MODEL_NAME,
            },
        )

        if chunks:
            _add_chunks_to_collection(temp_collection, chunks)

        with _lock:
            _client = client
            try:
                _client.delete_collection(COLLECTION_NAME)
            except Exception:
                pass
            temp_collection.modify(name=COLLECTION_NAME)
            _collection = _client.get_collection(COLLECTION_NAME)
            _index_status.update(
                {
                    "ready": True,
                    "chunk_count": _collection.count(),
                    "error": None,
                }
            )
    except Exception as exc:  # pragma: no cover - visible through status endpoint
        with _lock:
            _index_status.update({"error": str(exc)})

    return get_vector_store_status()


def semantic_search(
    query: str,
    limit: int = 3,
    *,
    subject_id: int | None = None,
    course_id: int | None = None,
    document_id: int | None = None,
    education_level_id: int | None = None,
    difficulty_level_id: int | None = None,
    published_only: bool = True,
) -> list[dict]:
    """Search chunks with real sentence-transformers embeddings in ChromaDB."""
    clean_query = query.strip()
    if not clean_query:
        return []

    collection = _get_collection()
    query_embedding = _embed_texts([clean_query])[0]
    search_limit = max(limit * 8, limit, 12)
    where_filter = _build_where_filter(
        subject_id=subject_id,
        course_id=course_id,
        document_id=document_id,
        education_level_id=education_level_id,
        difficulty_level_id=difficulty_level_id,
        published_only=published_only,
    )

    try:
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, search_limit),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        _load_existing_collection()
        collection = _get_collection()
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, search_limit),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

    return _rerank_results(clean_query, _format_query_results(result))[:limit]


def get_semantic_search_summary(query: str, limit: int = 3) -> dict:
    results = semantic_search(query, limit)
    return {
        "query": query,
        "total_results": len(results),
        "results": results,
        "mode": "rag_semantic",
    }


def get_vector_store_status() -> dict[str, Any]:
    status = dict(_index_status)
    try:
        collection = _get_collection()
        status["ready"] = True
        status["chunk_count"] = collection.count()
        status["error"] = None
    except Exception as exc:
        status["error"] = status.get("error") or str(exc)
    return status


def index_chunks(chunks: list[dict[str, Any]]) -> int:
    """Add pre-built chunks with rich metadata to the global collection."""

    if not chunks:
        return 0

    collection = _get_or_create_collection()
    texts = [str(chunk["text"]) for chunk in chunks]
    collection.add(
        ids=[str(chunk["id"]) for chunk in chunks],
        documents=texts,
        embeddings=_embed_texts(texts),
        metadatas=[_clean_metadata(chunk.get("metadata") or {}) for chunk in chunks],
    )
    with _lock:
        _index_status.update({"ready": True, "chunk_count": collection.count(), "error": None})
    return len(chunks)


def delete_document_vectors(document_id: int) -> int:
    collection = _get_or_create_collection()
    before = collection.count()
    try:
        collection.delete(where={"document_id": int(document_id)})
    except ValueError:
        return 0
    after = collection.count()
    with _lock:
        _index_status.update({"ready": True, "chunk_count": after, "error": None})
    return max(0, before - after)


def _reset_collection() -> None:
    global _collection

    if _client is None:
        raise RuntimeError("ChromaDB client is not initialized")

    try:
        _client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={
            "description": "EduMentor AI course PDF chunks",
            "embedding_model": EMBEDDING_MODEL_NAME,
        },
    )


def _get_or_create_collection() -> Any:
    global _client, _collection

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    if _client is None:
        _client = _get_chromadb().PersistentClient(path=str(CHROMA_DIR))
    if _collection is None:
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "description": "EduMentor AI course PDF chunks",
                "embedding_model": EMBEDDING_MODEL_NAME,
            },
        )
        _index_status.update({"ready": True, "chunk_count": _collection.count(), "error": None})
    return _collection


def _get_collection() -> Collection:
    if _collection is None or not _index_status.get("ready"):
        _load_existing_collection()

    if _collection is None or not _index_status.get("ready"):
        error = _index_status.get("error") or "Vector store is not initialized"
        raise RuntimeError(error)

    return _collection


def _load_existing_collection() -> None:
    global _client, _collection

    try:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = _get_chromadb().PersistentClient(path=str(CHROMA_DIR))
        _collection = _client.get_collection(COLLECTION_NAME)
        _index_status.update(
            {
                "ready": True,
                "chunk_count": _collection.count(),
                "error": None,
            }
        )
    except Exception:
        with _lock:
            _index_status.update({"ready": False, "error": "Vector store is not initialized"})


def _add_chunks_to_collection(collection: Any, chunks: list[RagChunk]) -> None:
    if collection is None:
        raise RuntimeError("ChromaDB collection is not initialized")

    texts = [chunk.text for chunk in chunks]
    collection.add(
        ids=[chunk.id for chunk in chunks],
        documents=texts,
        embeddings=_embed_texts(texts),
        metadatas=[
            {
                "course_name": chunk.course_name,
                "file_name": chunk.file_name,
                "page_number": chunk.page_number or -1,
                "character_count": chunk.character_count,
                "course_id": -1,
                "subject_id": -1,
                "document_id": -1,
                "published": True,
                "active": True,
                "index_status": "ready",
            }
            for chunk in chunks
        ],
    )


def _embed_texts(texts: list[str]) -> list[list[float]]:
    embeddings = _get_embedding_model().encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [embedding.tolist() for embedding in embeddings]


def _get_embedding_model() -> Any:
    global _embedding_model

    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    return _embedding_model


def _get_chromadb() -> Any:
    import chromadb

    return chromadb


def _format_query_results(result: dict) -> list[dict]:
    ids = result.get("ids", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    formatted_results: list[dict] = []
    for index, chunk_id in enumerate(ids):
        metadata = metadatas[index] or {}
        distance = float(distances[index]) if index < len(distances) else 0.0
        text = documents[index] if index < len(documents) else ""

        formatted_results.append(
            {
                "chunk_id": chunk_id,
                "course_name": metadata.get("course_name") or metadata.get("course_title", ""),
                "course_title": metadata.get("course_title") or metadata.get("course_name", ""),
                "course_id": _normalize_positive_int(metadata.get("course_id")),
                "subject_id": _normalize_positive_int(metadata.get("subject_id")),
                "subject_name": metadata.get("subject_name", ""),
                "subject_slug": metadata.get("subject_slug", ""),
                "document_id": _normalize_positive_int(metadata.get("document_id")),
                "file_name": metadata.get("file_name") or metadata.get("pdf_name", ""),
                "pdf_name": metadata.get("pdf_name") or metadata.get("file_name", ""),
                "file_url": metadata.get("file_url", ""),
                "page_number": _normalize_page_number(metadata.get("page_number") or metadata.get("page_start")),
                "page_start": _normalize_page_number(metadata.get("page_start") or metadata.get("page_number")),
                "page_end": _normalize_page_number(metadata.get("page_end") or metadata.get("page_number")),
                "chapter_title": metadata.get("chapter_title", ""),
                "display_source": metadata.get("display_source", ""),
                "document_type": metadata.get("document_type", ""),
                "language": metadata.get("language", ""),
                "level": metadata.get("level", ""),
                "subject": metadata.get("subject", ""),
                "program": metadata.get("program", ""),
                "work": metadata.get("work", ""),
                "author": metadata.get("author", ""),
                "exam_id": metadata.get("exam_id", ""),
                "year": metadata.get("year", ""),
                "region": metadata.get("region", ""),
                "session": metadata.get("session", ""),
                "question_id": metadata.get("question_id", ""),
                "competence": metadata.get("competence", ""),
                "question_type": metadata.get("question_type", ""),
                "points": metadata.get("points", ""),
                "verified": metadata.get("verified", ""),
                "source_name": metadata.get("source_name", ""),
                "source_type": metadata.get("source_type", ""),
                "source_tier": metadata.get("source_tier", ""),
                "source_priority": metadata.get("source_priority", 0),
                "copyright_restricted": metadata.get("copyright_restricted", False),
                "source_label": metadata.get("source_label", ""),
                "score": round(1 / (1 + distance), 4),
                "text_preview": text[:320],
                "excerpt": text[:320],
            }
        )

    return formatted_results


def _rerank_results(query: str, results: list[dict]) -> list[dict]:
    normalized_query = _normalize_text(query)
    query_terms = {term for term in re.findall(r"[a-z0-9]+", normalized_query) if len(term) >= 3}

    for result in results:
        adjusted_score = float(result.get("score", 0))
        text = _normalize_text(" ".join([
            result.get("text_preview", ""),
            result.get("course_title", ""),
            result.get("subject_name", ""),
            result.get("chapter_title", ""),
        ]))
        matched_terms = sum(1 for term in query_terms if term in text)
        adjusted_score += min(0.24, matched_terms * 0.055)
        if normalized_query and normalized_query in text:
            adjusted_score += 0.12
        if "regle" in normalized_query and ("regles d'or" in text or "5 regles" in text):
            adjusted_score += 0.18
        if "installer" in normalized_query and ("installation" in text or "guide d'installation" in text):
            adjusted_score += 0.18
        if "auteur" in normalized_query and (
            "auteur" in text
            or "ecrit par" in text
            or "ahmed sefrioui" in text
            or "jean anouilh" in text
            or "victor hugo" in text
        ):
            adjusted_score += 0.22
        if ("figure" in normalized_query or "style" in normalized_query) and "figure" in text:
            adjusted_score += 0.12
        if ("vrai" in normalized_query and "faux" in normalized_query) and ("vrai" in text and "faux" in text):
            adjusted_score += 0.16

        verified = str(result.get("verified", "")).lower()
        source_tier = str(result.get("source_tier", "")).lower()
        if "official" in verified or source_tier == "official":
            adjusted_score += 0.10
        elif "unverified" in verified or source_tier == "supplementary":
            adjusted_score -= 0.03
        elif "verified" in verified or source_tier in {"primary", "validated"}:
            adjusted_score += 0.06

        result["score"] = round(adjusted_score, 4)

    return sorted(results, key=lambda item: item.get("score", 0), reverse=True)


def _normalize_text(value: str) -> str:
    replacements = {
        "à": "a",
        "â": "a",
        "ä": "a",
        "ç": "c",
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ö": "o",
        "ù": "u",
        "û": "u",
        "ü": "u",
    }
    normalized = unicodedata.normalize("NFD", value.lower())
    normalized = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _normalize_page_number(value: Any) -> int | None:
    if value in (None, "", -1):
        return None

    try:
        page_number = int(value)
    except (TypeError, ValueError):
        return None

    return page_number if page_number > 0 else None


def _normalize_positive_int(value: Any) -> int | None:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return None
    return integer if integer > 0 else None


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            if key.endswith("_id") or key in {"page_start", "page_end", "page_number", "chunk_index", "character_count"}:
                cleaned[key] = -1
            elif key in {"published", "active"}:
                cleaned[key] = False
            else:
                cleaned[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def _build_where_filter(
    *,
    subject_id: int | None,
    course_id: int | None,
    document_id: int | None,
    education_level_id: int | None,
    difficulty_level_id: int | None,
    published_only: bool,
) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    if document_id is not None:
        conditions.append({"document_id": int(document_id)})
    elif course_id is not None:
        conditions.append({"course_id": int(course_id)})
    elif subject_id is not None:
        conditions.append({"subject_id": int(subject_id)})

    if education_level_id is not None:
        conditions.append({"education_level_id": int(education_level_id)})
    if difficulty_level_id is not None:
        conditions.append({"difficulty_level_id": int(difficulty_level_id)})
    if published_only:
        conditions.extend([
            {"published": True},
            {"active": True},
            {"index_status": "ready"},
        ])

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}
