from pathlib import Path
import sqlite3
import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings
from app.core.catalog_migration import apply_catalog_migration
from app.core.assessment_migration import apply_assessment_migration
from app.core.automatic_generation_migration import apply_automatic_generation_migration
from app.core.professor_migration import apply_professor_migration
from app.core.positioning_path_migration import apply_positioning_path_migration
from app.core.rag_migration import apply_rag_migration
from app.core.role_migration import apply_role_migration

DB_PATH = Path(__file__).resolve().parents[2] / "edumentor.db"
SQLALCHEMY_SQLITE_URL = f"sqlite:///{DB_PATH.as_posix()}"


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    database_url = get_settings().get("database_url") or ""
    if not database_url:
        return SQLALCHEMY_SQLITE_URL
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


DATABASE_URL = get_database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    log_database_target()

    if engine.dialect.name == "sqlite":
        with get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learners (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    level TEXT NOT NULL,
                    progress INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY,
                    learner_id INTEGER NOT NULL,
                    course_id INTEGER NOT NULL,
                    score INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO learners (id, name, email, level, progress)
                VALUES (1, 'Wijdane Lamsadi', 'wijdane@edumentor.ai', 'Intermediaire', 41)
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO scores (id, learner_id, course_id, score)
                VALUES (1, 1, 1, 76)
                """
            )

    import app.models.persistence as persistence_models  # noqa: F401

    migrate_persistence_schema()
    Base.metadata.create_all(bind=engine)
    apply_positioning_path_migration(engine)
    apply_catalog_migration(engine)
    apply_professor_migration(engine)
    apply_rag_migration(engine)
    apply_assessment_migration(engine)
    apply_automatic_generation_migration(engine)


def log_database_target() -> None:
    url = make_url(DATABASE_URL)
    logger.warning(
        "SQLAlchemy database target: dialect=%s database=%s url=%s",
        engine.dialect.name,
        url.database,
        url.render_as_string(hide_password=True),
    )


def migrate_persistence_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("user_profiles"):
        return

    columns = {column["name"] for column in inspector.get_columns("user_profiles")}
    with engine.begin() as connection:
        if "firebase_uid" not in columns:
            connection.execute(text("ALTER TABLE user_profiles ADD COLUMN firebase_uid VARCHAR(160)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_user_profiles_firebase_uid ON user_profiles (firebase_uid)"))
        if "status" not in columns:
            connection.execute(text("ALTER TABLE user_profiles ADD COLUMN status VARCHAR(40) DEFAULT 'active'"))

        connection.execute(text("UPDATE user_profiles SET status = 'active' WHERE status IS NULL OR status NOT IN ('active', 'disabled')"))
        if engine.dialect.name == "postgresql":
            connection.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence('user_profiles', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM user_profiles), 1), "
                    "true"
                    ")"
                )
            )
    apply_role_migration(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
