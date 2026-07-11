from __future__ import annotations

import os
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


def semantic_search(query: str, limit: int = 3) -> list[dict]:
    """Search chunks with real sentence-transformers embeddings in ChromaDB."""
    clean_query = query.strip()
    if not clean_query:
        return []

    collection = _get_collection()
    query_embedding = _embed_texts([clean_query])[0]
    search_limit = max(limit * 8, limit, 12)

    try:
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, search_limit),
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        _load_existing_collection()
        collection = _get_collection()
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, search_limit),
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
        initialize_vector_store()


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
                "course_name": metadata.get("course_name", ""),
                "file_name": metadata.get("file_name", ""),
                "page_number": _normalize_page_number(metadata.get("page_number")),
                "score": round(1 / (1 + distance), 4),
                "text_preview": text[:320],
            }
        )

    return formatted_results


def _rerank_results(query: str, results: list[dict]) -> list[dict]:
    normalized_query = _normalize_text(query)
    topic_files = {
        ("introduction ia", "intelligence artificielle"): "01_Introduction_IA.pdf",
        ("machine learning",): "02_Machine_Learning.pdf",
        ("deep learning", "reseau de neurones", "reseaux de neurones"): "03_Deep_Learning.pdf",
        ("llm", "large language model", "modele de langage"): "04_LLM.pdf",
        ("prompt engineering", "prompt"): "05_Prompt_Engineering.pdf",
        ("rag", "retrieval augmented generation"): "06_RAG.pdf",
        ("chatbot", "chatbots"): "07_Chatbots_IA.pdf",
        ("ia responsable", "biais", "ethique", "responsable"): "08_IA_Responsable.pdf",
    }

    expected_files = {
        file_name
        for keywords, file_name in topic_files.items()
        if any(keyword in normalized_query for keyword in keywords)
    }

    for result in results:
        adjusted_score = float(result.get("score", 0))
        text = _normalize_text(result.get("text_preview", ""))
        file_name = result.get("file_name", "")

        if file_name in expected_files:
            adjusted_score += 0.35

        for keywords, file_for_keywords in topic_files.items():
            if any(keyword in normalized_query and keyword in text for keyword in keywords):
                adjusted_score += 0.08
                if file_name == file_for_keywords:
                    adjusted_score += 0.08

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
    normalized = value.lower()
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
