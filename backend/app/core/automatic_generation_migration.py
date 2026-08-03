from __future__ import annotations

from sqlalchemy import Engine, inspect, text


USER_PROFILE_COLUMNS = {
    "school_year": "VARCHAR(120)",
    "academic_year": "VARCHAR(80)",
    "study_stream": "VARCHAR(160)",
    "region": "VARCHAR(160)",
    "prepared_subjects": "JSON",
    "regional_exam_date": "VARCHAR(80)",
}


def apply_automatic_generation_migration(engine: Engine) -> None:
    """Create Phase import, parent and regional-exam tables additively."""
    _add_user_profile_columns(engine)
    _create_new_tables(engine)


def _add_user_profile_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("user_profiles"):
        return

    existing = {column["name"] for column in inspector.get_columns("user_profiles")}
    with engine.begin() as connection:
        for column_name, column_type in USER_PROFILE_COLUMNS.items():
            if column_name in existing:
                continue
            connection.execute(text(f"ALTER TABLE user_profiles ADD COLUMN {column_name} {column_type}"))


def _create_new_tables(engine: Engine) -> None:
    from app.core.database import Base
    from app.models.persistence import (
        CourseAdaptation,
        CourseAdaptedSection,
        CourseLevelVariant,
        LiteraryWork,
        NotificationDelivery,
        ParentNotification,
        ParentNotificationPreference,
        ParentStudentLink,
        PedagogicalPackageImportJob,
        RegionalExamProfile,
    )

    Base.metadata.create_all(
        engine,
        tables=[
            PedagogicalPackageImportJob.__table__,
            CourseLevelVariant.__table__,
            CourseAdaptation.__table__,
            CourseAdaptedSection.__table__,
            RegionalExamProfile.__table__,
            LiteraryWork.__table__,
            ParentStudentLink.__table__,
            ParentNotificationPreference.__table__,
            ParentNotification.__table__,
            NotificationDelivery.__table__,
        ],
    )
