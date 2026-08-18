from __future__ import annotations

from sqlalchemy import Engine, inspect, text


INITIAL_SUBJECTS = [
    ("Français", "francais", "Matière cible pour la préparation de l'examen régional de français en 1ère année Baccalauréat.", "book-open", True, 1),
]

INITIAL_EDUCATION_LEVELS = [
    ("Lycée", "lycee", "", 1, True),
    ("1ère année Baccalauréat", "1ere_bac", "Cycle parent: Lycée. Niveau cible pour la préparation de l'examen régional au Maroc.", 2, True),
]

INITIAL_DIFFICULTY_LEVELS = [
    ("Debutant", "debutant", 1, True),
    ("Intermediaire", "intermediaire", 2, True),
    ("Avance", "avance", 3, True),
]

def apply_catalog_migration(engine: Engine) -> dict[str, int | list[int]]:
    if engine.dialect.name == "postgresql":
        return apply_postgresql_catalog_migration(engine)
    return apply_sqlite_catalog_seed(engine)


def apply_postgresql_catalog_migration(engine: Engine) -> dict[str, int | list[int]]:
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS subjects (
                id SERIAL PRIMARY KEY,
                name VARCHAR(160) NOT NULL UNIQUE,
                slug VARCHAR(180) NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                icon VARCHAR(80),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT ck_subjects_slug_not_empty CHECK (length(trim(slug)) > 0)
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS education_levels (
                id SERIAL PRIMARY KEY,
                name VARCHAR(160) NOT NULL UNIQUE,
                slug VARCHAR(180) NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                display_order INTEGER NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS difficulty_levels (
                id SERIAL PRIMARY KEY,
                name VARCHAR(160) NOT NULL UNIQUE,
                slug VARCHAR(180) NOT NULL UNIQUE,
                display_order INTEGER NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        ))

        columns = get_columns(engine, "courses")
        add_column_if_missing(connection, columns, "subject_id", "INTEGER")
        add_column_if_missing(connection, columns, "education_level_id", "INTEGER")
        add_column_if_missing(connection, columns, "difficulty_level_id", "INTEGER")
        add_column_if_missing(connection, columns, "professor_id", "INTEGER")
        add_column_if_missing(connection, columns, "estimated_duration", "VARCHAR(80)")
        add_column_if_missing(connection, columns, "prerequisites", "TEXT")

        create_index_if_missing(connection, "ix_courses_subject_id", "courses", "subject_id")
        create_index_if_missing(connection, "ix_courses_education_level_id", "courses", "education_level_id")
        create_index_if_missing(connection, "ix_courses_difficulty_level_id", "courses", "difficulty_level_id")
        create_index_if_missing(connection, "ix_courses_professor_id", "courses", "professor_id")

        add_fk_if_missing(connection, "fk_courses_subject_id", "courses", "subject_id", "subjects", "id")
        add_fk_if_missing(connection, "fk_courses_education_level_id", "courses", "education_level_id", "education_levels", "id")
        add_fk_if_missing(connection, "fk_courses_difficulty_level_id", "courses", "difficulty_level_id", "difficulty_levels", "id")
        add_fk_if_missing(connection, "fk_courses_professor_id", "courses", "professor_id", "user_profiles", "id")

        seed_subjects(connection)
        seed_education_levels(connection)
        seed_difficulty_levels(connection)
        attach_existing_courses(connection)

    return get_catalog_counts(engine)


def apply_sqlite_catalog_seed(engine: Engine) -> dict[str, int | list[int]]:
    from app.models.persistence import DifficultyLevel, EducationLevel, Subject
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        for name, slug, description, icon, active, display_order in INITIAL_SUBJECTS:
            if not db.query(Subject).filter_by(slug=slug).first():
                db.add(Subject(name=name, slug=slug, description=description, icon=icon, active=active, display_order=display_order))
        for name, slug, description, display_order, active in INITIAL_EDUCATION_LEVELS:
            if not db.query(EducationLevel).filter_by(slug=slug).first():
                db.add(EducationLevel(name=name, slug=slug, description=description, active=active, display_order=display_order))
        for name, slug, display_order, active in INITIAL_DIFFICULTY_LEVELS:
            if not db.query(DifficultyLevel).filter_by(slug=slug).first():
                db.add(DifficultyLevel(name=name, slug=slug, active=active, display_order=display_order))
        db.commit()
    return get_catalog_counts(engine)


def seed_subjects(connection) -> None:
    for name, slug, description, icon, active, display_order in INITIAL_SUBJECTS:
        connection.execute(
            text(
                """
                INSERT INTO subjects (name, slug, description, icon, active, display_order, created_at, updated_at)
                VALUES (:name, :slug, :description, :icon, :active, :display_order, NOW(), NOW())
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    icon = EXCLUDED.icon,
                    active = EXCLUDED.active,
                    display_order = EXCLUDED.display_order,
                    updated_at = NOW()
                """
            ),
            {"name": name, "slug": slug, "description": description, "icon": icon, "active": active, "display_order": display_order},
        )


def seed_education_levels(connection) -> None:
    for name, slug, description, display_order, active in INITIAL_EDUCATION_LEVELS:
        connection.execute(
            text(
                """
                INSERT INTO education_levels (name, slug, description, display_order, active, created_at, updated_at)
                VALUES (:name, :slug, :description, :display_order, :active, NOW(), NOW())
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    display_order = EXCLUDED.display_order,
                    active = EXCLUDED.active,
                    updated_at = NOW()
                """
            ),
            {"name": name, "slug": slug, "description": description, "display_order": display_order, "active": active},
        )


def seed_difficulty_levels(connection) -> None:
    for name, slug, display_order, active in INITIAL_DIFFICULTY_LEVELS:
        connection.execute(
            text(
                """
                INSERT INTO difficulty_levels (name, slug, display_order, active)
                VALUES (:name, :slug, :display_order, :active)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    display_order = EXCLUDED.display_order,
                    active = EXCLUDED.active
                """
            ),
            {"name": name, "slug": slug, "display_order": display_order, "active": active},
        )


def attach_existing_courses(connection) -> None:
    connection.execute(
        text(
            """
            UPDATE courses
            SET subject_id = (SELECT id FROM subjects WHERE slug = 'francais')
            WHERE subject_id IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE courses
            SET difficulty_level_id = (
                SELECT id FROM difficulty_levels
                WHERE slug = CASE
                    WHEN lower(level) LIKE '%debut%' THEN 'debutant'
                    WHEN lower(level) LIKE '%inter%' THEN 'intermediaire'
                    WHEN lower(level) LIKE '%avanc%' THEN 'avance'
                    ELSE NULL
                END
            )
            WHERE difficulty_level_id IS NULL
            """
        )
    )
    connection.execute(text("UPDATE courses SET estimated_duration = duration WHERE estimated_duration IS NULL"))


def get_columns(engine: Engine, table_name: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def add_column_if_missing(connection, columns: set[str], name: str, definition: str) -> None:
    if name not in columns:
        connection.execute(text(f"ALTER TABLE courses ADD COLUMN {name} {definition}"))
        columns.add(name)


def create_index_if_missing(connection, index_name: str, table_name: str, column_name: str) -> None:
    connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"))


def add_fk_if_missing(connection, constraint_name: str, table_name: str, column_name: str, target_table: str, target_column: str) -> None:
    connection.execute(
        text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{constraint_name}'
                ) THEN
                    ALTER TABLE {table_name}
                    ADD CONSTRAINT {constraint_name}
                    FOREIGN KEY ({column_name}) REFERENCES {target_table}({target_column});
                END IF;
            END $$;
            """
        )
    )


def get_catalog_counts(engine: Engine) -> dict[str, int | list[int]]:
    inspector = inspect(engine)
    course_columns = get_columns(engine, "courses")
    with engine.connect() as connection:
        subject_count = scalar_count(connection, "subjects") if inspector.has_table("subjects") else 0
        education_level_count = scalar_count(connection, "education_levels") if inspector.has_table("education_levels") else 0
        difficulty_count = scalar_count(connection, "difficulty_levels") if inspector.has_table("difficulty_levels") else 0
        course_count = scalar_count(connection, "courses") if inspector.has_table("courses") else 0
        if "subject_id" in course_columns and inspector.has_table("subjects"):
            courses_without_subject = connection.execute(text("SELECT COUNT(*) FROM courses WHERE subject_id IS NULL")).scalar_one()
            french_courses = connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM courses
                    WHERE subject_id = (SELECT id FROM subjects WHERE slug = 'francais')
                    """
                )
            ).scalar_one()
        else:
            courses_without_subject = course_count
            french_courses = 0
        course_ids = [row[0] for row in connection.execute(text("SELECT id FROM courses ORDER BY id")).all()]
    return {
        "subjects": int(subject_count),
        "education_levels": int(education_level_count),
        "difficulty_levels": int(difficulty_count),
        "courses": int(course_count),
        "courses_without_subject": int(courses_without_subject),
        "french_courses": int(french_courses),
        "course_ids": course_ids,
    }


def scalar_count(connection, table_name: str) -> int:
    return int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one())
