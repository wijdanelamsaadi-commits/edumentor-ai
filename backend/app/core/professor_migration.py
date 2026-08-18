from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def apply_professor_migration(engine: Engine) -> dict[str, int | list[int]]:
    """Add professor-space columns without rebuilding existing tables."""

    inspector = inspect(engine)
    counts: dict[str, int | list[int]] = {
        "professors": 0,
        "courses": 0,
        "courses_with_professor": 0,
        "courses_without_professor": 0,
        "chapters": 0,
        "quizzes": 0,
        "quiz_results": 0,
        "ai_course_ids": [],
    }
    if not inspector.has_table("courses"):
        return counts

    dialect = engine.dialect.name
    table_columns = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in ["courses", "course_chapters", "quizzes", "quiz_questions"]
        if inspector.has_table(table_name)
    }
    with engine.begin() as connection:
        _add_column(connection, table_columns, "courses", "status", "VARCHAR(40)")
        _add_column(connection, table_columns, "courses", "content_import_status", "VARCHAR(40)")
        _add_column(connection, table_columns, "courses", "content_import_error", "TEXT")
        _add_column(connection, table_columns, "courses", "content_imported_at", _datetime_type(dialect))
        connection.execute(text("UPDATE courses SET status = CASE WHEN published THEN 'published' ELSE 'draft' END WHERE status IS NULL OR status = ''"))
        connection.execute(text("UPDATE courses SET content_import_status = 'pending' WHERE content_import_status IS NULL OR content_import_status = ''"))

        if inspector.has_table("course_chapters"):
            _add_column(connection, table_columns, "course_chapters", "estimated_duration", "VARCHAR(80)")
            _add_column(connection, table_columns, "course_chapters", "active", _bool_type(dialect))
            _add_column(connection, table_columns, "course_chapters", "created_at", _datetime_type(dialect))
            _add_column(connection, table_columns, "course_chapters", "updated_at", _datetime_type(dialect))
            _add_column(connection, table_columns, "course_chapters", "structured_content", _json_type(dialect))
            connection.execute(text("UPDATE course_chapters SET estimated_duration = duration WHERE estimated_duration IS NULL"))
            connection.execute(text("UPDATE course_chapters SET active = TRUE WHERE active IS NULL"))
            connection.execute(text("UPDATE course_chapters SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
            connection.execute(text("UPDATE course_chapters SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))

        if inspector.has_table("quizzes"):
            _add_column(connection, table_columns, "quizzes", "description", "TEXT")
            _add_column(connection, table_columns, "quizzes", "passing_score", "INTEGER")
            _add_column(connection, table_columns, "quizzes", "active", _bool_type(dialect))
            connection.execute(text("UPDATE quizzes SET description = '' WHERE description IS NULL"))
            connection.execute(text("UPDATE quizzes SET passing_score = 70 WHERE passing_score IS NULL"))
            connection.execute(text("UPDATE quizzes SET active = published WHERE active IS NULL"))

        if inspector.has_table("quiz_questions"):
            _add_column(connection, table_columns, "quiz_questions", "chapter_id", "INTEGER")
            _add_column(connection, table_columns, "quiz_questions", "difficulty_level_id", "INTEGER")
            _add_column(connection, table_columns, "quiz_questions", "active", _bool_type(dialect))
            connection.execute(text("UPDATE quiz_questions SET active = TRUE WHERE active IS NULL"))

        counts["professors"] = connection.execute(text("SELECT COUNT(*) FROM user_profiles WHERE role = 'professor'")).scalar_one_or_none() or 0
        counts["courses"] = connection.execute(text("SELECT COUNT(*) FROM courses")).scalar_one_or_none() or 0
        counts["courses_with_professor"] = connection.execute(text("SELECT COUNT(*) FROM courses WHERE professor_id IS NOT NULL")).scalar_one_or_none() or 0
        counts["courses_without_professor"] = connection.execute(text("SELECT COUNT(*) FROM courses WHERE professor_id IS NULL")).scalar_one_or_none() or 0
        counts["chapters"] = connection.execute(text("SELECT COUNT(*) FROM course_chapters")).scalar_one_or_none() or 0
        counts["quizzes"] = connection.execute(text("SELECT COUNT(*) FROM quizzes")).scalar_one_or_none() or 0
        counts["quiz_results"] = connection.execute(text("SELECT COUNT(*) FROM quiz_results")).scalar_one_or_none() or 0
        counts["ai_course_ids"] = [row[0] for row in connection.execute(text("SELECT id FROM courses WHERE id BETWEEN 1 AND 8 ORDER BY id")).all()]

    return counts


def _add_column(connection, table_columns: dict[str, set[str]], table_name: str, column_name: str, column_type: str) -> None:
    columns = table_columns.setdefault(table_name, set())
    if column_name not in columns:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
        columns.add(column_name)


def _bool_type(dialect: str) -> str:
    return "BOOLEAN" if dialect == "postgresql" else "BOOLEAN"


def _datetime_type(dialect: str) -> str:
    return "TIMESTAMP" if dialect == "postgresql" else "DATETIME"


def _json_type(dialect: str) -> str:
    return "JSONB" if dialect == "postgresql" else "JSON"
