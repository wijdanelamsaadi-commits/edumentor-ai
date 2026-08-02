from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.catalog_migration import apply_catalog_migration
from app.core.database import Base
from app.models import persistence as persistence_models  # noqa: F401
from app.models.persistence import Course, RagDocument, Subject, UserProfile
from app.services import french_regional_corpus_service, rag_document_service


def build_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'french_corpus.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    apply_catalog_migration(engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, TestingSession()


def seed_french_course(db):
    subject = db.query(Subject).filter_by(slug="francais").one()
    professor = UserProfile(id=8301, firebase_uid="prof-corpus", email="prof-corpus@example.com", full_name="Prof", role="professor")
    course = Course(
        id=8302,
        title="Preparation au regional de francais - 1ere Bac",
        subject=subject,
        professor=professor,
        published=True,
        status="published",
        summary="Cours de preparation au regional.",
    )
    db.add_all([professor, course])
    db.commit()
    return subject, course


def test_french_corpus_dry_run_builds_semantic_documents(tmp_path):
    engine, db = build_session(tmp_path)
    try:
        subject, course = seed_french_course(db)

        summary = french_regional_corpus_service.sync_french_regional_corpus(db, dry_run=True)

        assert summary["subject_id"] == subject.id
        assert summary["course_id"] == course.id
        assert summary["documents"] >= 15
        assert summary["chunks"] > summary["documents"]
        assert "regional_exam_text" in summary["document_types"]
        assert "regional_exam_question" in summary["document_types"] or summary["competences"]
    finally:
        db.close()
        engine.dispose()


def test_text_document_chunks_keep_question_and_correction_together(tmp_path, monkeypatch):
    engine, db = build_session(tmp_path)
    try:
        subject, course = seed_french_course(db)
        corpus_dir = tmp_path / "french_regional"
        corpus_dir.mkdir()
        document_path = corpus_dir / "exam.md"
        document_path.write_text("# Exam\n\nQuestion et correction", encoding="utf-8")
        (corpus_dir / "exam.md.chunks.json").write_text(
            """[
  {
    "chunk_key": "question-q1",
    "text": "Question: Qui est l'auteur ? Correction officielle ou verifiee: Ahmed Sefrioui.",
    "metadata": {
      "language": "fr",
      "subject": "francais",
      "level": "1ere_bac_maroc",
      "program": "regional",
      "document_type": "regional_exam_question",
      "work": "La Boite a merveilles",
      "question_id": "q1",
      "competence": "Methodologie",
      "display_source": "Examen regional - question 1"
    }
  }
]""",
            encoding="utf-8",
        )
        monkeypatch.setattr(rag_document_service, "FRENCH_REGIONAL_DOCS_DIR", corpus_dir)
        document = RagDocument(
            course_id=course.id,
            subject_id=subject.id,
            original_filename="Corpus francais test",
            stored_filename="exam.md",
            file_path=str(document_path),
            file_size=document_path.stat().st_size,
            mime_type="text/markdown",
            checksum_sha256="a" * 64,
            active=True,
            index_status="pending",
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        chunks = rag_document_service.build_document_chunks(db, document)

        assert len(chunks) == 1
        assert "Question:" in chunks[0]["text"]
        assert "Correction officielle" in chunks[0]["text"]
        assert chunks[0]["metadata"]["subject"] == "francais"
        assert chunks[0]["metadata"]["display_source"] == "Examen regional - question 1"
    finally:
        db.close()
        engine.dispose()


def test_chat_french_scope_filters_out_legacy_ai_documents(monkeypatch, tmp_path):
    engine, db = build_session(tmp_path)
    try:
        subject, course = seed_french_course(db)
        student = UserProfile(id=8303, firebase_uid="student-corpus", email="student-corpus@example.com", full_name="Student", role="student")
        db.add(student)
        db.commit()
        captured = {}

        def fake_semantic_search(query, limit=3, **kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr(rag_document_service, "semantic_search", fake_semantic_search)

        rag_document_service.filtered_semantic_search(db, "Resume Antigone", subject_id=subject.id, course_id=course.id)

        assert captured["course_id"] == course.id
        assert captured["subject_id"] == subject.id
        assert captured["published_only"] is True
    finally:
        db.close()
        engine.dispose()
