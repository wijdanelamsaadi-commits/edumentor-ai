from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from pypdf import PdfReader

from app.core.config import get_settings

COURSES_DOCS_DIR = Path(get_settings().get("docs_dir") or Path(__file__).resolve().parents[3] / "docs") / "courses"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
MIN_TOKEN_LENGTH = 2
STOPWORDS = {
    "c",
    "ce",
    "ces",
    "dans",
    "de",
    "des",
    "du",
    "est",
    "et",
    "la",
    "le",
    "les",
    "quoi",
    "que",
    "qui",
    "un",
    "une",
}


@dataclass(frozen=True)
class RagDocument:
    course_name: str
    file_name: str
    page_count: int
    character_count: int
    text: str
    pages: tuple[str, ...]


@dataclass(frozen=True)
class RagChunk:
    id: str
    course_name: str
    file_name: str
    page_number: int | None
    text: str
    character_count: int


_documents: list[RagDocument] = []
_chunks: list[RagChunk] = []


def load_course_documents() -> list[RagDocument]:
    """Load all course PDFs into memory for the future RAG pipeline."""
    global _documents, _chunks

    loaded_documents: list[RagDocument] = []

    if not COURSES_DOCS_DIR.exists():
        _documents = []
        _chunks = []
        return _documents

    for pdf_path in sorted(COURSES_DOCS_DIR.glob("*.pdf")):
        reader = PdfReader(str(pdf_path))
        pages_text = tuple((page.extract_text() or "").strip() for page in reader.pages)
        document_text = "\n\n".join(text.strip() for text in pages_text if text.strip())

        loaded_documents.append(
            RagDocument(
                course_name=_course_name_from_file(pdf_path),
                file_name=pdf_path.name,
                page_count=len(reader.pages),
                character_count=len(document_text),
                text=document_text,
                pages=pages_text,
            )
        )

    _documents = loaded_documents
    _chunks = build_chunks(_documents)
    return _documents


def get_documents() -> list[RagDocument]:
    if not _documents:
        load_course_documents()

    return _documents


def get_documents_summary() -> dict:
    documents = get_documents()

    return {
        "pdf_count": len(documents),
        "documents": [
            {
                "course_name": document.course_name,
                "file_name": document.file_name,
                "page_count": document.page_count,
                "character_count": document.character_count,
            }
            for document in documents
        ],
    }


def build_chunks(documents: list[RagDocument]) -> list[RagChunk]:
    chunks: list[RagChunk] = []

    for document in documents:
        chunk_index = 1

        for page_index, page_text in enumerate(document.pages, start=1):
            normalized_text = " ".join(page_text.split())

            if not normalized_text:
                continue

            for chunk_text in split_text_into_chunks(normalized_text):
                chunks.append(
                    RagChunk(
                        id=f"{document.file_name}:p{page_index}:c{chunk_index}",
                        course_name=document.course_name,
                        file_name=document.file_name,
                        page_number=page_index,
                        text=chunk_text,
                        character_count=len(chunk_text),
                    )
                )
                chunk_index += 1

    return chunks


def split_text_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text:
        return []

    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end].strip())

        if end == len(text):
            break

        start = end - overlap

    return [chunk for chunk in chunks if chunk]


def get_chunks() -> list[RagChunk]:
    if not _chunks:
        load_course_documents()

    return _chunks


def get_chunks_summary() -> dict:
    chunks = get_chunks()

    return {
        "total_chunks": len(chunks),
        "chunks_preview": [
            {
                "id": chunk.id,
                "file_name": chunk.file_name,
                "course_name": chunk.course_name,
                "page_number": chunk.page_number,
                "character_count": chunk.character_count,
                "text_preview": chunk.text[:220],
            }
            for chunk in chunks[:10]
        ],
    }


def search_chunks(query: str, limit: int = 5) -> list[dict]:
    tokens = _tokenize(query)

    if not tokens:
        return []

    normalized_query = _normalize_text(query)
    scored_chunks: list[tuple[float, RagChunk]] = []

    for chunk in get_chunks():
        searchable_text = " ".join([chunk.course_name, chunk.file_name, chunk.text])
        normalized_text = _normalize_text(searchable_text)
        score = _score_chunk(normalized_text, normalized_query, tokens)

        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda item: item[0], reverse=True)

    return [
        {
            "chunk_id": chunk.id,
            "course_name": chunk.course_name,
            "file_name": chunk.file_name,
            "page_number": chunk.page_number,
            "score": round(score, 3),
            "text_preview": chunk.text[:320],
        }
        for score, chunk in scored_chunks[: max(1, limit)]
    ]


def get_search_summary(query: str, limit: int = 5) -> dict:
    results = search_chunks(query, limit)

    return {
        "query": query,
        "total_results": len(results),
        "results": results,
    }


def _score_chunk(normalized_text: str, normalized_query: str, tokens: list[str]) -> float:
    score = 0.0

    for token in tokens:
        score += normalized_text.count(token)

    if normalized_query and normalized_query in normalized_text:
        score += len(tokens) * 3

    unique_matches = sum(1 for token in set(tokens) if token in normalized_text)
    score += unique_matches * 2

    return score


def _tokenize(text: str) -> list[str]:
    normalized_text = _normalize_text(text)
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized_text)
        if len(token) >= MIN_TOKEN_LENGTH and token not in STOPWORDS
    ]


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    without_accents = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
    return without_accents


def _course_name_from_file(pdf_path: Path) -> str:
    name = pdf_path.stem
    parts = name.split("_")

    if parts and parts[0].isdigit():
        parts = parts[1:]

    return " ".join(parts) or name
