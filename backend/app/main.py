from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
from app.core.diagnostic_migration import apply_diagnostic_migration
from app.services.course_service import seed_courses_from_mock
from app.services.automatic_course_generation_service import repair_completed_course_classroom_assignments
from app.services.rag_document_service import sync_rag_documents

app = FastAPI(
    title="EduMentor AI API",
    description="API pedagogique avec lecture PDF, recherche RAG et donnees de demonstration.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5190",
        "http://127.0.0.1:5190",
        "http://localhost:5192",
        "http://127.0.0.1:5192",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")


@app.on_event("startup")
def startup() -> None:
    init_db()
    with SessionLocal() as db:
        seed_courses_from_mock(db)
        repair_completed_course_classroom_assignments(db)
        sync_rag_documents(db)
    apply_catalog_migration(engine)
    apply_diagnostic_migration(engine)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "EduMentor AI API is running"}


app.include_router(router, prefix="/api")
app.include_router(ai_test_router, prefix="/api")
app.include_router(persistence_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(professor_router, prefix="/api")
app.include_router(assessment_router, prefix="/api")
app.include_router(parent_router, prefix="/api")
app.include_router(regional_router, prefix="/api")
app.include_router(nlp_router, prefix="/api")