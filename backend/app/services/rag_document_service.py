from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import AdminAuditLog, Course, RagDocument, RagIndexJob, UserProfile
from app.rag.vector_store import COLLECTION_NAME, EMBEDDING_MODEL_NAME, delete_document_vectors, get_vector_store_status, index_chunks, semantic_search

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "courses"
LEGACY_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "courses"
FRENCH_REGIONAL_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "french_regional"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
MAX_TOP_K = 10


@dataclass(frozen=True)
class PageChunk:
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    chapter_title: str


def sync_rag_documents(db: Session) -> dict[str, int]:
    """Ensure each course PDF has a PostgreSQL RagDocument row."""

    created = 0
    updated = 0
    skipped = 0
    courses = db.scalars(select(Course).options(selectinload(Course.subject), selectinload(Course.professor))).all()
    for course in courses:
        if not course.pdf_url:
            continue
        pdf_path = _safe_pdf_path(course.pdf_url)
        if not pdf_path.exists():
            skipped += 1
            continue
        checksum = compute_checksum(pdf_path)
        existing_for_course = db.scalars(
            select(RagDocument)
            .where(RagDocument.course_id == course.id, RagDocument.active.is_(True))
            .order_by(RagDocument.created_at.desc())
        ).first()
        if existing_for_course and existing_for_course.checksum_sha256 == checksum:
            _update_document_from_course(existing_for_course, course, pdf_path, checksum)
            updated += 1
            continue
        if existing_for_course:
            existing_for_course.active = False
            existing_for_course.index_status = "outdated"
            delete_document_vectors(existing_for_course.id)

        document = db.scalars(
            select(RagDocument).where(RagDocument.course_id == course.id, RagDocument.checksum_sha256 == checksum)
        ).first()
        if document is None:
            page_count = _page_count(pdf_path)
            document = RagDocument(
                course_id=course.id,
                subject_id=course.subject_id,
                professor_id=course.professor_id,
                original_filename=public_pdf_name(course.pdf_url),
                stored_filename=Path(course.pdf_url).name,
                file_path=str(pdf_path),
                file_size=pdf_path.stat().st_size,
                mime_type="application/pdf",
                checksum_sha256=checksum,
                page_count=page_count,
                chunk_count=0,
                embedding_model=EMBEDDING_MODEL_NAME,
                collection_name=COLLECTION_NAME,
                index_status="pending",
                active=True,
            )
            db.add(document)
            created += 1
        else:
            _update_document_from_course(document, course, pdf_path, checksum)
            updated += 1
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def get_public_status(db: Session) -> dict[str, Any]:
    sync_rag_documents(db)
    vector_status = get_vector_store_status()
    ready_documents = db.scalar(select(func.count(RagDocument.id)).where(RagDocument.active.is_(True), RagDocument.index_status == "ready")) or 0
    total_chunks = db.scalar(select(func.coalesce(func.sum(RagDocument.chunk_count), 0)).where(RagDocument.active.is_(True), RagDocument.index_status == "ready")) or 0
    return {
        "engine_available": bool(vector_status.get("ready")),
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_dimension": 384,
        "collection_name": COLLECTION_NAME,
        "ready_documents": int(ready_documents),
        "chunk_count": int(total_chunks or vector_status.get("chunk_count") or 0),
        "error": vector_status.get("error"),
    }


def get_course_rag_status(db: Session, course_id: int) -> dict[str, Any]:
    document = get_active_document_for_course(db, course_id)
    if document is None:
        return {
            "course_id": course_id,
            "document_present": False,
            "index_status": "pending",
            "chunk_count": 0,
            "indexed_at": None,
            "outdated": False,
            "error": "Aucun support PDF associe au cours.",
        }
    return serialize_document(document)


def list_documents(db: Session, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    sync_rag_documents(db)
    filters = filters or {}
    query = select(RagDocument).options(
        selectinload(RagDocument.course).selectinload(Course.subject),
        selectinload(RagDocument.professor),
    ).order_by(RagDocument.updated_at.desc(), RagDocument.id.desc())
    if filters.get("subject_id"):
        query = query.where(RagDocument.subject_id == int(filters["subject_id"]))
    if filters.get("course_id"):
        query = query.where(RagDocument.course_id == int(filters["course_id"]))
    if filters.get("professor_id"):
        query = query.where(RagDocument.professor_id == int(filters["professor_id"]))
    if filters.get("status"):
        query = query.where(RagDocument.index_status == str(filters["status"]))
    if filters.get("search"):
        pattern = f"%{str(filters['search']).strip()}%"
        query = query.where(RagDocument.original_filename.ilike(pattern))
    return [serialize_document(document) for document in db.scalars(query).all()]


def list_jobs(db: Session, current_user: UserProfile | None = None, professor_only: bool = False) -> list[dict[str, Any]]:
    query = select(RagIndexJob).options(selectinload(RagIndexJob.document), selectinload(RagIndexJob.course)).order_by(RagIndexJob.created_at.desc()).limit(50)
    if professor_only and current_user is not None:
        query = query.where(RagIndexJob.requested_by_user_id == current_user.id)
    return [serialize_job(job) for job in db.scalars(query).all()]


def request_index_document(db: Session, document_id: int, current_user: UserProfile, action: str = "index") -> dict[str, Any]:
    document = db.get(RagDocument, document_id)
    if document is None or not document.active:
        raise HTTPException(status_code=404, detail="Document RAG introuvable")
    job = _create_job(db, document, current_user, action)
    return serialize_job(job)


def request_course_reindex(db: Session, course_id: int, current_user: UserProfile) -> list[dict[str, Any]]:
    documents = db.scalars(select(RagDocument).where(RagDocument.course_id == course_id, RagDocument.active.is_(True))).all()
    if not documents:
        sync_rag_documents(db)
        documents = db.scalars(select(RagDocument).where(RagDocument.course_id == course_id, RagDocument.active.is_(True))).all()
    return [serialize_job(_create_job(db, document, current_user, "reindex")) for document in documents]


def request_subject_reindex(db: Session, subject_id: int, current_user: UserProfile) -> list[dict[str, Any]]:
    sync_rag_documents(db)
    documents = db.scalars(select(RagDocument).where(RagDocument.subject_id == subject_id, RagDocument.active.is_(True))).all()
    return [serialize_job(_create_job(db, document, current_user, "reindex")) for document in documents]


def run_job_by_id(job_id: int) -> None:
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        job = db.get(RagIndexJob, job_id)
        if job is None:
            return
        run_index_job(db, job)


def run_index_job(db: Session, job: RagIndexJob) -> RagIndexJob:
    document = db.get(RagDocument, job.document_id) if job.document_id else None
    if document is None:
        _fail_job(db, job, "Document RAG introuvable")
        return job

    job.status = "processing"
    job.started_at = datetime.utcnow()
    document.index_status = "processing"
    document.index_error = None
    db.commit()

    try:
        deleted = delete_document_vectors(document.id)
        chunks = build_document_chunks(db, document)
        chunks_created = index_chunks(chunks)
        document.chunk_count = chunks_created
        document.index_status = "ready"
        document.index_error = None
        document.indexed_at = datetime.utcnow()
        document.updated_at = datetime.utcnow()
        job.status = "ready"
        job.finished_at = datetime.utcnow()
        job.error_message = None
        job.chunks_created = chunks_created
        _audit(db, job.requested_by_user_id, f"rag_{job.action}", "rag_document", str(document.id), {"deleted_chunks": deleted}, serialize_document(document))
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(RagIndexJob, job.id)
        document = db.get(RagDocument, document.id)
        if job and document:
            _fail_job(db, job, str(exc), document)
    return job


def delete_index(db: Session, document_id: int, current_user: UserProfile) -> dict[str, Any]:
    document = db.get(RagDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document RAG introuvable")
    deleted = delete_document_vectors(document.id)
    before = serialize_document(document)
    document.chunk_count = 0
    document.index_status = "pending"
    document.indexed_at = None
    document.index_error = None
    job = _create_job(db, document, current_user, "delete_index", commit=False)
    job.status = "ready"
    job.started_at = datetime.utcnow()
    job.finished_at = datetime.utcnow()
    job.chunks_created = 0
    _audit(db, current_user.id, "rag_delete_index", "rag_document", str(document.id), before, {"deleted_chunks": deleted})
    db.commit()
    return {"deleted_chunks": deleted, "document": serialize_document(document), "job": serialize_job(job)}


def mark_course_document_outdated(db: Session, course: Course) -> None:
    documents = db.scalars(select(RagDocument).where(RagDocument.course_id == course.id, RagDocument.active.is_(True))).all()
    for document in documents:
        document.active = False
        document.index_status = "outdated"
        document.updated_at = datetime.utcnow()
        delete_document_vectors(document.id)


def filtered_semantic_search(
    db: Session,
    query: str,
    *,
    subject_id: int | None = None,
    course_id: int | None = None,
    document_id: int | None = None,
    education_level_id: int | None = None,
    difficulty_level_id: int | None = None,
    top_k: int = 3,
    published_only: bool = True,
) -> list[dict[str, Any]]:
    if len(query.strip()) > 1200:
        raise HTTPException(status_code=422, detail="Question trop longue")
    top_k = max(1, min(int(top_k or 3), MAX_TOP_K))
    return semantic_search(
        query,
        limit=top_k,
        subject_id=subject_id,
        course_id=course_id,
        document_id=document_id,
        education_level_id=education_level_id,
        difficulty_level_id=difficulty_level_id,
        published_only=published_only,
    )


def build_document_chunks(db: Session, document: RagDocument) -> list[dict[str, Any]]:
    course = db.get(Course, document.course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Cours du document introuvable")
    if document.mime_type in {"text/markdown", "text/plain", "application/json", "application/x-ndjson"}:
        return build_structured_text_document_chunks(course, document)
    pdf_path = _safe_pdf_path(document.stored_filename)
    if not pdf_path.exists():
        raise FileNotFoundError("Le fichier PDF associe est introuvable")
    pages = extract_pages(pdf_path)
    page_chunks = split_pages_into_chunks(pages)
    document.page_count = len(pages)
    chunks = []
    for chunk in page_chunks:
        chunks.append(
            {
                "id": stable_chunk_id(document, chunk),
                "text": chunk.text,
                "metadata": {
                    "document_id": document.id,
                    "course_id": course.id,
                    "course_name": course.title,
                    "course_title": course.title,
                    "subject_id": course.subject_id or -1,
                    "subject_name": course.subject.name if course.subject else "",
                    "subject_slug": course.subject.slug if course.subject else "",
                    "professor_id": course.professor_id or -1,
                    "education_level_id": course.education_level_id or -1,
                    "difficulty_level_id": course.difficulty_level_id or -1,
                    "pdf_name": document.original_filename,
                    "file_name": document.original_filename,
                    "file_url": f"/docs/courses/{document.stored_filename}",
                    "page_number": chunk.page_start,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "chapter_title": chunk.chapter_title,
                    "chunk_index": chunk.chunk_index,
                    "checksum_sha256": document.checksum_sha256,
                    "language": _document_language(course),
                    "published": bool(course.published),
                    "active": bool(document.active),
                    "index_status": "ready",
                    "character_count": len(chunk.text),
                    "source_label": f"{course.title} - {document.original_filename} - page {chunk.page_start}",
                },
            }
        )
    return chunks


def build_structured_text_document_chunks(course: Course, document: RagDocument) -> list[dict[str, Any]]:
    document_path = _safe_text_path(document.file_path or document.stored_filename)
    if not document_path.exists():
        raise FileNotFoundError("Le fichier texte associe est introuvable")

    sidecar_path = document_path.with_suffix(document_path.suffix + ".chunks.json")
    if sidecar_path.exists():
        raw_chunks = json_load(sidecar_path)
        chunks = []
        for index, raw_chunk in enumerate(raw_chunks if isinstance(raw_chunks, list) else [], start=1):
            text = " ".join(str(raw_chunk.get("text") or "").split())
            if not text:
                continue
            chunk_key = str(raw_chunk.get("chunk_key") or index)
            metadata = dict(raw_chunk.get("metadata") or {})
            page_number = metadata.get("page_number", metadata.get("page_start", -1))
            page_start = metadata.get("page_start", page_number)
            page_end = metadata.get("page_end", page_number)
            chapter_title = metadata.get("chapter_title", "")
            display_source = metadata.get("display_source", "")
            source_label = metadata.get("source_label", "")
            metadata.update({
                "document_id": document.id,
                "course_id": course.id,
                "course_name": course.title,
                "course_title": course.title,
                "subject_id": course.subject_id or -1,
                "subject_name": course.subject.name if course.subject else metadata.get("subject_name", ""),
                "subject_slug": course.subject.slug if course.subject else metadata.get("subject_slug", ""),
                "professor_id": course.professor_id or -1,
                "education_level_id": course.education_level_id or -1,
                "difficulty_level_id": course.difficulty_level_id or -1,
                "file_name": document.original_filename,
                "pdf_name": document.original_filename,
                "file_url": "",
                "page_number": page_number,
                "page_start": page_start,
                "page_end": page_end,
                "chapter_title": chapter_title,
                "chunk_index": index,
                "checksum_sha256": document.checksum_sha256,
                "published": bool(course.published),
                "active": bool(document.active),
                "index_status": "ready",
                "character_count": len(text),
                "display_source": display_source,
                "source_label": source_label,
            })
            if not metadata.get("source_label"):
                metadata["source_label"] = metadata.get("display_source") or document.original_filename
            chunks.append({
                "id": stable_text_chunk_id(document, chunk_key),
                "text": text,
                "metadata": metadata,
            })
        return chunks

    text = document_path.read_text(encoding="utf-8")
    chunks = []
    for chunk in split_text_sections_into_chunks(text):
        chunks.append({
            "id": stable_text_chunk_id(document, str(chunk.chunk_index)),
            "text": chunk.text,
            "metadata": {
                "document_id": document.id,
                "course_id": course.id,
                "course_name": course.title,
                "course_title": course.title,
                "subject_id": course.subject_id or -1,
                "subject_name": course.subject.name if course.subject else "",
                "subject_slug": course.subject.slug if course.subject else "",
                "professor_id": course.professor_id or -1,
                "education_level_id": course.education_level_id or -1,
                "difficulty_level_id": course.difficulty_level_id or -1,
                "file_name": document.original_filename,
                "pdf_name": document.original_filename,
                "page_number": -1,
                "page_start": -1,
                "page_end": -1,
                "chapter_title": chunk.chapter_title,
                "chunk_index": chunk.chunk_index,
                "checksum_sha256": document.checksum_sha256,
                "language": _document_language(course),
                "published": bool(course.published),
                "active": bool(document.active),
                "index_status": "ready",
                "character_count": len(chunk.text),
                "source_label": document.original_filename,
            },
        })
    return chunks


def extract_pages(pdf_path: Path) -> list[str]:
    reader = PdfReader(str(pdf_path))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def split_pages_into_chunks(pages: list[str], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[PageChunk]:
    chunks: list[PageChunk] = []
    chunk_index = 1
    for page_number, raw_page in enumerate(pages, start=1):
        text = " ".join(raw_page.split())
        if not text:
            continue
        chapter_title = _detect_chapter_title(raw_page)
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            piece = text[start:end].strip()
            if piece:
                chunks.append(PageChunk(page_number, page_number, chunk_index, piece, chapter_title))
                chunk_index += 1
            if end == len(text):
                break
            start = max(0, end - overlap)
    return chunks


def stable_chunk_id(document: RagDocument, chunk: PageChunk) -> str:
    return f"doc-{document.id}-{document.checksum_sha256[:12]}-p{chunk.page_start}-c{chunk.chunk_index}"


def stable_text_chunk_id(document: RagDocument, chunk_key: str) -> str:
    safe_key = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", chunk_key).strip("-")[:80] or "chunk"
    return f"doc-{document.id}-{document.checksum_sha256[:12]}-{safe_key}"


def serialize_document(document: RagDocument) -> dict[str, Any]:
    course = document.course
    return {
        "id": document.id,
        "course_id": document.course_id,
        "course_title": course.title if course else "",
        "subject_id": document.subject_id,
        "subject_name": course.subject.name if course and course.subject else "",
        "subject_slug": course.subject.slug if course and course.subject else "",
        "professor_id": document.professor_id,
        "professor_name": document.professor.full_name if document.professor else "",
        "original_filename": document.original_filename,
        "file_size": document.file_size,
        "mime_type": document.mime_type,
        "checksum_sha256": document.checksum_sha256,
        "checksum_short": document.checksum_sha256[:12],
        "page_count": document.page_count,
        "chunk_count": document.chunk_count,
        "embedding_model": document.embedding_model,
        "collection_name": document.collection_name,
        "index_status": document.index_status,
        "index_error": document.index_error,
        "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        "active": document.active,
        "document_present": True,
        "outdated": document.index_status == "outdated",
    }


def serialize_job(job: RagIndexJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "document_id": job.document_id,
        "course_id": job.course_id,
        "course_title": job.course.title if job.course else "",
        "subject_id": job.subject_id,
        "requested_by_user_id": job.requested_by_user_id,
        "requested_by_role": job.requested_by_role,
        "action": job.action,
        "status": job.status,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error_message": job.error_message,
        "chunks_created": job.chunks_created,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def get_active_document_for_course(db: Session, course_id: int) -> RagDocument | None:
    sync_rag_documents(db)
    return db.scalars(
        select(RagDocument)
        .where(RagDocument.course_id == course_id, RagDocument.active.is_(True))
        .options(selectinload(RagDocument.course).selectinload(Course.subject), selectinload(RagDocument.professor))
        .order_by(RagDocument.created_at.desc())
    ).first()


def compute_checksum(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_pdf_path(pdf_url_or_name: str) -> Path:
    file_name = Path(str(pdf_url_or_name)).name
    if not file_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Document PDF invalide")
    for root in (DOCS_DIR, LEGACY_DOCS_DIR):
        path = (root / file_name).resolve()
        docs_root = root.resolve()
        if docs_root not in path.parents and path != docs_root:
            continue
        if path.exists():
            return path
    return (DOCS_DIR / file_name).resolve()


def _safe_text_path(path_or_name: str) -> Path:
    raw = Path(str(path_or_name))
    candidates = [raw] if raw.is_absolute() else [FRENCH_REGIONAL_DOCS_DIR / raw]
    for candidate in candidates:
        path = candidate.resolve()
        docs_root = FRENCH_REGIONAL_DOCS_DIR.resolve()
        if (path == docs_root or docs_root in path.parents) and path.suffix.lower() in {".md", ".txt", ".json", ".jsonl"}:
            return path
    raise HTTPException(status_code=400, detail="Document texte RAG invalide")


def split_text_sections_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[PageChunk]:
    sections: list[tuple[str, str]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = stripped.lstrip("#").strip()
            current_lines = [stripped]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    chunks: list[PageChunk] = []
    chunk_index = 1
    for title, section_text in sections:
        normalized = " ".join(section_text.split())
        if not normalized:
            continue
        if len(normalized) <= chunk_size * 1.5:
            chunks.append(PageChunk(-1, -1, chunk_index, normalized, title))
            chunk_index += 1
            continue
        for piece in split_text_into_semantic_pieces(normalized, chunk_size, overlap):
            chunks.append(PageChunk(-1, -1, chunk_index, piece, title))
            chunk_index += 1
    return chunks


def split_text_into_semantic_pieces(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    pieces: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size or not current:
            current = f"{current} {sentence}".strip()
            continue
        pieces.append(current)
        current = f"{current[-overlap:]} {sentence}".strip()
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def json_load(path: Path) -> Any:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def public_pdf_name(pdf_url_or_name: str) -> str:
    name = Path(str(pdf_url_or_name)).name
    match = re.match(r"^professor_\d+_course_\d+_[0-9a-f]{32}_(.+\.pdf)$", name, flags=re.IGNORECASE)
    return match.group(1) if match else name


def _page_count(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def _update_document_from_course(document: RagDocument, course: Course, pdf_path: Path, checksum: str) -> None:
    document.subject_id = course.subject_id
    document.professor_id = course.professor_id
    document.original_filename = public_pdf_name(course.pdf_url or pdf_path.name)
    document.stored_filename = Path(course.pdf_url or pdf_path.name).name
    document.file_path = str(pdf_path)
    document.file_size = pdf_path.stat().st_size
    document.mime_type = "application/pdf"
    document.checksum_sha256 = checksum
    document.page_count = _page_count(pdf_path)
    document.embedding_model = EMBEDDING_MODEL_NAME
    document.collection_name = COLLECTION_NAME
    document.active = True
    document.updated_at = datetime.utcnow()


def _create_job(db: Session, document: RagDocument, current_user: UserProfile, action: str, commit: bool = True) -> RagIndexJob:
    job = RagIndexJob(
        document_id=document.id,
        course_id=document.course_id,
        subject_id=document.subject_id,
        requested_by_user_id=current_user.id,
        requested_by_role=current_user.role,
        action=action,
        status="pending",
    )
    db.add(job)
    document.index_status = "processing" if action in {"index", "reindex"} else document.index_status
    if commit:
        db.commit()
        db.refresh(job)
    return job


def _fail_job(db: Session, job: RagIndexJob, message: str, document: RagDocument | None = None) -> None:
    job.status = "failed"
    job.finished_at = datetime.utcnow()
    job.error_message = message[:1000]
    if document is not None:
        document.index_status = "failed"
        document.index_error = message[:2000]
    _audit(db, job.requested_by_user_id, f"rag_{job.action}_failed", "rag_document", str(job.document_id), None, {"error": message[:500]})
    db.commit()


def _audit(db: Session, admin_user_id: int | None, action: str, target_type: str, target_id: str | None, before: Any, after: Any) -> None:
    if admin_user_id is None:
        return
    db.add(AdminAuditLog(admin_user_id=admin_user_id, action=action, target_type=target_type, target_id=target_id, before_data=before, after_data=after))


def _detect_chapter_title(raw_page: str) -> str:
    for line in raw_page.splitlines():
        clean = " ".join(line.strip().split())
        if not clean:
            continue
        lowered = clean.lower()
        if lowered.startswith(("chapitre", "module", "partie", "section")) or len(clean) <= 80:
            return clean[:120]
    return ""


def _document_language(course: Course) -> str:
    information = course.information or {}
    return str(information.get("language") or information.get("langue") or "fr")
