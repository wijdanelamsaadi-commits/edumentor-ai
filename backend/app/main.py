from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.admin_routes import router as admin_router
from app.api.persistence_routes import router as persistence_router
from app.api.routes import router
from app.core.database import init_db
from app.core.database import SessionLocal
from app.rag.document_store import load_course_documents
from app.services.course_service import seed_courses_from_mock

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
        "http://localhost:5190",
        "http://127.0.0.1:5190",
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
    load_course_documents()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "EduMentor AI API is running"}


app.include_router(router, prefix="/api")
app.include_router(persistence_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
