from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.catalog_migration import apply_catalog_migration, get_catalog_counts
from app.core.database import DATABASE_URL, engine
from sqlalchemy import inspect


def main() -> None:
    print(f"Database dialect: {engine.dialect.name}")
    print(f"Database URL: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    inspector = inspect(engine)
    before = get_catalog_counts(engine) if inspector.has_table("subjects") else {}
    print(f"Before: {before}")
    after = apply_catalog_migration(engine)
    print(f"After: {after}")


if __name__ == "__main__":
    main()
