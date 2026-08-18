from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import DATABASE_URL, engine
from app.core.role_migration import apply_role_migration


def main() -> None:
    print(f"Database dialect: {engine.dialect.name}")
    print(f"Database URL: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")

    inspector = inspect(engine)
    if inspector.has_table("user_profiles"):
        for column in inspector.get_columns("user_profiles"):
            if column["name"] == "role":
                print(f"role column type: {column['type']}")
                print(f"role nullable: {column.get('nullable')}")
                print(f"role default: {column.get('default')}")
                break

    counts = apply_role_migration(engine)
    print("Role counts after migration:")
    print(f"admin={counts['admin']}")
    print(f"professor={counts['professor']}")
    print(f"student={counts['student']}")
    print(f"invalid={counts['invalid']}")


if __name__ == "__main__":
    main()
