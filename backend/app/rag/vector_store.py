from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import chromadb
from chromadb.api.models.Collection import Collection
from sentence_transformers import SentenceTransformer

from app.rag.document_store import RagChunk, get_chunks, load_course_documents

CHROMA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"
COLLECTION_NAME = "edumentor_course_chunks"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

_lock = Lock()
_client: chromadb.PersistentClient | None = None
_collection: Collection | None = None
_embedding_model: SentenceTransformer | None = None
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
    """Rebuild the ChromaDB index from the current PDF chunks."""
    global _client, _collection

    with _lock:
        try:
            load_course_documents()
            chunks = get_chunks()
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)

            _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            _reset_collection()

            if chunks:
                _add_chunks_to_collection(_collection, chunks)

            _index_status.update(
                {
                    "ready": True,
                    "chunk_count": _collection.count(),
                    "error": None,
                }
            )
        except Exception as exc:  # pragma: no cover - visible through status endpoint
            _index_status.update(
                {
                    "ready": False,
                    "chunk_count": 0,
                    "error": str(exc),
                }
            )

        return get_vector_store_status()


def semantic_search(query: str, limit: int = 3) -> list[dict]:
    """Search chunks with real sentence-transformers embeddings in ChromaDB."""
    clean_query = query.strip()
    if not clean_query:
        return []

    collection = _get_collection()
    query_embedding = _embed_texts([clean_query])[0]

    try:
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, limit),
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        _load_existing_collection()
        collection = _get_collection()
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, limit),
            include=["documents", "metadatas", "distances"],
        )

    return _format_query_results(result)


def get_semantic_search_summary(query: str, limit: int = 3) -> dict:
    results = semantic_search(query, limit)
    return {
        "query": query,
        "total_results": len(results),
        "results": results,
        "mode": "rag_semantic",
    }


def get_vector_store_status() -> dict[str, Any]:
    return dict(_index_status)


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
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _client.get_collection(COLLECTION_NAME)
        _index_status.update(
            {
                "ready": True,
                "chunk_count": _collection.count(),
                "error": None,
            }
        )
    except Exception:
        initialize_vector_store()


def _add_chunks_to_collection(collection: Collection | None, chunks: list[RagChunk]) -> None:
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


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    return _embedding_model


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
                "course_name": metadata.get("course_name", ""),
                "file_name": metadata.get("file_name", ""),
                "page_number": _normalize_page_number(metadata.get("page_number")),
                "score": round(1 / (1 + distance), 4),
                "text_preview": text[:320],
            }
        )

    return formatted_results


def _normalize_page_number(value: Any) -> int | None:
    if value in (None, "", -1):
        return None

    try:
        page_number = int(value)
    except (TypeError, ValueError):
        return None

    return page_number if page_number > 0 else None
