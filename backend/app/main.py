from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.database import init_db
from app.rag.document_store import load_course_documents
from app.rag.vector_store import initialize_vector_store

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


@app.on_event("startup")
def startup() -> None:
    init_db()
    load_course_documents()
    initialize_vector_store()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "EduMentor AI API is running"}


app.include_router(router, prefix="/api")
