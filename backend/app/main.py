from pathlib import Path
import shutil
from threading import Thread

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.admin_routes import router as admin_router
from app.api.ai_test_routes import router as ai_test_router
from app.api.assessment_routes import router as assessment_router
from app.api.persistence_routes import router as persistence_router
from app.api.parent_routes import router as parent_router
from app.api.professor_routes import router as professor_router
from app.api.regional_routes import router as regional_router
from app.api.nlp_routes import router as nlp_router
from app.api.routes import router
from app.core.database import init_db
from app.core.database import SessionLocal
from app.core.catalog_migration import apply_catalog_migration
from app.core.database import engine
from app.core.config import BACKEND_DIR, get_settings
from app.core.diagnostic_migration import apply_diagnostic_migration
from app.services.course_service import seed_courses_from_mock
from app.services.automatic_course_generation_service import repair_completed_course_classroom_assignments
from app.services.rag_document_service import sync_rag_documents

app = FastAPI(
    title="EduMentor AI API",
    description="API pedagogique avec lecture PDF, recherche RAG et donnees de demonstration.",
    version="0.1.0",
)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5190",
    "http://127.0.0.1:5190",
    "http://localhost:5192",
    "http://127.0.0.1:5192",
    "https://frontend-cjsur63vu-wijdanelamsaadi-3560s-projects.vercel.app",
    "https://frontend-ten-phi-75.vercel.app",
]


def get_cors_origins() -> list[str]:
    configured_origins = get_settings().get("cors_allow_origins") or ""
    origins = [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]
    return [*DEFAULT_CORS_ORIGINS, *origins]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_DOCS_DIR = BACKEND_DIR / "docs"
DOCS_DIR = Path(get_settings().get("docs_dir") or DEFAULT_DOCS_DIR)
DOCS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")


@app.on_event("startup")
def startup() -> None:
    if get_settings().get("fast_startup"):
        Thread(target=initialize_application, daemon=True).start()
        return
    initialize_application()


def initialize_application() -> None:
    bootstrap_docs_volume()
    bootstrap_chroma_volume()
    init_db()
    with SessionLocal() as db:
        seed_courses_from_mock(db)
        repair_completed_course_classroom_assignments(db)
        sync_rag_documents(db)
        sync_french_rag_corpus(db)
        ensure_vector_index_from_ready_documents(db)
    apply_catalog_migration(engine)
    apply_diagnostic_migration(engine)


def bootstrap_docs_volume() -> None:
    if DOCS_DIR == DEFAULT_DOCS_DIR or not DEFAULT_DOCS_DIR.exists():
        return
    if any(DOCS_DIR.iterdir()):
        return
    shutil.copytree(DEFAULT_DOCS_DIR, DOCS_DIR, dirs_exist_ok=True)


def bootstrap_chroma_volume() -> None:
    try:
        from app.rag.vector_store import bootstrap_chroma_volume as bootstrap

        bootstrap()
    except Exception:
        pass


def sync_french_rag_corpus(db) -> None:
    try:
        from app.services.french_regional_corpus_service import sync_french_regional_corpus
        from app.services.sigma_french_pdf_service import sync_sigma_french_pdf

        sync_french_regional_corpus(db, index=True)
        sync_sigma_french_pdf(db, index=True)
    except Exception:
        pass


def ensure_vector_index_from_ready_documents(db) -> None:
    from sqlalchemy import select

    from app.models.persistence import RagDocument
    from app.rag.vector_store import get_vector_store_status, index_chunks
    from app.services.rag_document_service import build_document_chunks

    status = get_vector_store_status()
    if int(status.get("chunk_count") or 0) > 0:
        return

    documents = db.scalars(
        select(RagDocument)
        .where(RagDocument.active.is_(True), RagDocument.index_status == "ready")
        .order_by(RagDocument.id)
    ).all()
    indexed = 0
    for document in documents:
        chunks = build_document_chunks(db, document)
        if not chunks:
            continue
        indexed += index_chunks(chunks)
    if indexed:
        db.commit()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "EduMentor AI API is running"}


@app.get("/health")
def health() -> dict:
    database_ok = False
    database_error = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            database_ok = True
    except Exception as exc:  # pragma: no cover - runtime deployment diagnostics
        database_error = type(exc).__name__

    try:
        from app.rag.vector_store import get_vector_store_status

        rag_status = get_vector_store_status()
    except Exception as exc:  # pragma: no cover - runtime deployment diagnostics
        rag_status = {"ready": False, "error": type(exc).__name__}

    return {
        "status": "ok" if database_ok else "degraded",
        "database": {
            "ok": database_ok,
            "dialect": engine.url.get_backend_name(),
            "database": engine.url.database,
            "error": database_error,
        },
        "rag": {
            "ready": bool(rag_status.get("ready")),
            "chunk_count": rag_status.get("chunk_count", 0),
            "mode": rag_status.get("mode"),
            "error": rag_status.get("error"),
        },
    }


app.include_router(router, prefix="/api")
app.include_router(ai_test_router, prefix="/api")
app.include_router(persistence_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(professor_router, prefix="/api")
app.include_router(assessment_router, prefix="/api")
app.include_router(parent_router, prefix="/api")
app.include_router(regional_router, prefix="/api")
app.include_router(nlp_router, prefix="/api")
