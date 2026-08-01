from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def apply_rag_migration(engine: Engine) -> dict[str, int]:
    """Create/repair RAG document metadata tables without deleting data."""

    import app.models.persistence as persistence_models  # noqa: F401
    from app.core.database import Base

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    counts = {"rag_documents": 0, "rag_index_jobs": 0}
    if not inspector.has_table("rag_documents"):
        return counts

    document_columns = {column["name"] for column in inspector.get_columns("rag_documents")}
    job_columns = {column["name"] for column in inspector.get_columns("rag_index_jobs")} if inspector.has_table("rag_index_jobs") else set()

    dialect = engine.dialect.name
    with engine.begin() as connection:
        _add_column(connection, document_columns, "rag_documents", "active", _bool_type(dialect))
        _add_column(connection, document_columns, "rag_documents", "index_status", "VARCHAR(40)")
        _add_column(connection, document_columns, "rag_documents", "chunk_count", "INTEGER")
        connection.execute(text("UPDATE rag_documents SET active = TRUE WHERE active IS NULL"))
        connection.execute(text("UPDATE rag_documents SET index_status = 'pending' WHERE index_status IS NULL OR index_status = ''"))
        connection.execute(text("UPDATE rag_documents SET chunk_count = 0 WHERE chunk_count IS NULL"))

        if inspector.has_table("rag_index_jobs"):
            _add_column(connection, job_columns, "rag_index_jobs", "chunks_created", "INTEGER")
            connection.execute(text("UPDATE rag_index_jobs SET chunks_created = 0 WHERE chunks_created IS NULL"))

        counts["rag_documents"] = connection.execute(text("SELECT COUNT(*) FROM rag_documents")).scalar_one_or_none() or 0
        counts["rag_index_jobs"] = connection.execute(text("SELECT COUNT(*) FROM rag_index_jobs")).scalar_one_or_none() or 0

    return counts


def _add_column(connection, columns: set[str], table_name: str, column_name: str, column_type: str) -> None:
    if column_name not in columns:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
        columns.add(column_name)


def _bool_type(dialect: str) -> str:
    return "BOOLEAN" if dialect == "postgresql" else "BOOLEAN"
