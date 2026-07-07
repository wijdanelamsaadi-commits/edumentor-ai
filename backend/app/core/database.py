from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parents[2] / "edumentor.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
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
