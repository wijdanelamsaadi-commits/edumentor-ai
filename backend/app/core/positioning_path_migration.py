from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def apply_positioning_path_migration(engine: Engine) -> None:
    """Allow a StudyPath to originate from DiagnosticResult instead of AssessmentAttempt."""
    inspector = inspect(engine)
    if not inspector.has_table("study_paths"):
        return

    columns = {column["name"]: column for column in inspector.get_columns("study_paths")}
    source_attempt_nullable = bool(columns.get("source_attempt_id", {}).get("nullable", False))
    has_diagnostic_source = "source_diagnostic_result_id" in columns

    if source_attempt_nullable and has_diagnostic_source:
        return

    if engine.dialect.name == "sqlite":
        _migrate_sqlite(engine, columns)
        return

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE study_paths "
                "ALTER COLUMN source_attempt_id DROP NOT NULL"
            ))
            connection.execute(text(
                "ALTER TABLE study_paths "
                "ADD COLUMN IF NOT EXISTS source_diagnostic_result_id INTEGER "
                "REFERENCES diagnostic_results(id)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_study_paths_source_diagnostic_result_id "
                "ON study_paths (source_diagnostic_result_id)"
            ))
        return

    logger.warning(
        "Positioning-path migration was not applied automatically for dialect %s.",
        engine.dialect.name,
    )


def _migrate_sqlite(engine: Engine, columns: dict) -> None:
    old_column_names = set(columns)
    dbapi_connection = engine.raw_connection()
    cursor = dbapi_connection.cursor()

    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("DROP TABLE IF EXISTS study_paths_new")
        cursor.execute(
            """
            CREATE TABLE study_paths_new (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                course_id INTEGER NOT NULL,
                remediation_plan_id INTEGER,
                source_attempt_id INTEGER,
                source_diagnostic_result_id INTEGER,
                title VARCHAR(260) NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status VARCHAR(40) NOT NULL DEFAULT 'active',
                progress_percentage FLOAT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                completed_at DATETIME,
                active BOOLEAN NOT NULL DEFAULT 1,
                CONSTRAINT uq_study_paths_remediation_plan UNIQUE (remediation_plan_id),
                FOREIGN KEY(student_id) REFERENCES user_profiles (id),
                FOREIGN KEY(subject_id) REFERENCES subjects (id),
                FOREIGN KEY(course_id) REFERENCES courses (id),
                FOREIGN KEY(remediation_plan_id) REFERENCES remediation_plans (id),
                FOREIGN KEY(source_attempt_id) REFERENCES assessment_attempts (id),
                FOREIGN KEY(source_diagnostic_result_id) REFERENCES diagnostic_results (id)
            )
            """
        )

        diagnostic_select = (
            "source_diagnostic_result_id"
            if "source_diagnostic_result_id" in old_column_names
            else "NULL"
        )
        cursor.execute(
            f"""
            INSERT INTO study_paths_new (
                id,
                student_id,
                subject_id,
                course_id,
                remediation_plan_id,
                source_attempt_id,
                source_diagnostic_result_id,
                title,
                reason,
                status,
                progress_percentage,
                created_at,
                updated_at,
                completed_at,
                active
            )
            SELECT
                id,
                student_id,
                subject_id,
                course_id,
                remediation_plan_id,
                source_attempt_id,
                {diagnostic_select},
                title,
                reason,
                status,
                progress_percentage,
                created_at,
                updated_at,
                completed_at,
                active
            FROM study_paths
            """
        )

        cursor.execute("DROP TABLE study_paths")
        cursor.execute("ALTER TABLE study_paths_new RENAME TO study_paths")

        indexes = [
            ("ix_study_paths_student_id", "student_id"),
            ("ix_study_paths_subject_id", "subject_id"),
            ("ix_study_paths_course_id", "course_id"),
            ("ix_study_paths_remediation_plan_id", "remediation_plan_id"),
            ("ix_study_paths_source_attempt_id", "source_attempt_id"),
            ("ix_study_paths_source_diagnostic_result_id", "source_diagnostic_result_id"),
            ("ix_study_paths_status", "status"),
            ("ix_study_paths_active", "active"),
        ]
        for index_name, column_name in indexes:
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON study_paths ({column_name})"
            )

        dbapi_connection.commit()
        logger.info("Positioning-path migration applied to SQLite.")
    except Exception:
        dbapi_connection.rollback()
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            dbapi_connection.close()
