from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine



DEFAULT_THRESHOLDS = [
    ("non_acquis", "Non acquis", 0, 39),
    ("en_cours", "En cours d'acquisition", 40, 69),
    ("acquis", "Acquis", 70, 84),
    ("maitrise", "Maitrise", 85, 100),
]


def apply_assessment_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    _add_personalized_lesson_columns(engine, inspector)
    _add_attempt_timing_columns(engine, inspector)
    _add_personalized_question_columns(engine, inspector)
    _create_study_path_tables(engine)
    if not inspector.has_table("mastery_thresholds"):
        return

    with engine.begin() as connection:
        for code, label, min_percentage, max_percentage in DEFAULT_THRESHOLDS:
            if engine.dialect.name == "postgresql":
                connection.execute(
                    text(
                        """
                        INSERT INTO mastery_thresholds (code, label, min_percentage, max_percentage, active)
                        VALUES (:code, :label, :min_percentage, :max_percentage, true)
                        ON CONFLICT (code) DO NOTHING
                        """
                    ),
                    {
                        "code": code,
                        "label": label,
                        "min_percentage": min_percentage,
                        "max_percentage": max_percentage,
                    },
                )
            else:
                connection.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO mastery_thresholds (code, label, min_percentage, max_percentage, active)
                        VALUES (:code, :label, :min_percentage, :max_percentage, 1)
                        """
                    ),
                    {
                        "code": code,
                        "label": label,
                        "min_percentage": min_percentage,
                        "max_percentage": max_percentage,
                    },
                )


def _add_personalized_lesson_columns(engine: Engine, inspector) -> None:
    if not inspector.has_table("remediation_items"):
        return

    columns = {column["name"] for column in inspector.get_columns("remediation_items")}
    if "personalized_lesson_id" in columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE remediation_items ADD COLUMN personalized_lesson_id INTEGER"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_remediation_items_personalized_lesson_id ON remediation_items (personalized_lesson_id)"))


def _add_attempt_timing_columns(engine: Engine, inspector) -> None:
    if not inspector.has_table("assessment_answers"):
        return

    columns = {column["name"] for column in inspector.get_columns("assessment_answers")}
    if "time_spent_seconds" in columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE assessment_answers ADD COLUMN time_spent_seconds INTEGER"))


def _add_personalized_question_columns(engine: Engine, inspector) -> None:
    if not inspector.has_table("assessment_questions"):
        return

    columns = {column["name"] for column in inspector.get_columns("assessment_questions")}
    additions = [
        ("source_attempt_id", "INTEGER"),
        ("source_question_id", "INTEGER"),
        ("generation_method", "VARCHAR(40)"),
        ("similarity_score", "FLOAT"),
        ("adaptation_reason", "TEXT"),
    ]
    with engine.begin() as connection:
        for name, column_type in additions:
            if name not in columns:
                connection.execute(text(f"ALTER TABLE assessment_questions ADD COLUMN {name} {column_type}"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_questions_source_attempt_id ON assessment_questions (source_attempt_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_questions_source_question_id ON assessment_questions (source_question_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_questions_generation_method ON assessment_questions (generation_method)"))


def _create_study_path_tables(engine: Engine) -> None:
    from app.core.database import Base
    from app.models.persistence import StudyPath, StudyPathItem

    Base.metadata.create_all(engine, tables=[StudyPath.__table__, StudyPathItem.__table__])
