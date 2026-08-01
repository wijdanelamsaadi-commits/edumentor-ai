from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from app.core.roles import DEFAULT_ROLE


ROLE_CHECK_NAME = "ck_user_profiles_role_valid"
VALID_ROLE_SQL = "'admin', 'professor', 'student', 'parent'"
VALID_ROLE_LIST = "('admin', 'professor', 'student', 'parent')"


def apply_role_migration(engine: Engine) -> dict[str, int]:
    inspector = inspect(engine)
    if not inspector.has_table("user_profiles"):
        return {"admin": 0, "professor": 0, "student": 0, "parent": 0, "invalid": 0}

    with engine.begin() as connection:
        connection.execute(text("UPDATE user_profiles SET role = 'student' WHERE role = 'user'"))
        connection.execute(text("UPDATE user_profiles SET role = :default_role WHERE role IS NULL"), {"default_role": DEFAULT_ROLE})

        if engine.dialect.name == "postgresql":
            connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'ck_user_profiles_role_valid'
                        ) THEN
                            ALTER TABLE user_profiles
                            ADD CONSTRAINT ck_user_profiles_role_valid
                            CHECK (role IN ('admin', 'professor', 'student', 'parent'));
                        ELSE
                            ALTER TABLE user_profiles
                            DROP CONSTRAINT ck_user_profiles_role_valid;
                            ALTER TABLE user_profiles
                            ADD CONSTRAINT ck_user_profiles_role_valid
                            CHECK (role IN ('admin', 'professor', 'student', 'parent'));
                        END IF;
                    END $$;
                    """
                )
            )
        else:
            invalid_count = connection.execute(
                text(f"SELECT COUNT(*) FROM user_profiles WHERE role NOT IN {VALID_ROLE_LIST}")
            ).scalar_one()
            if invalid_count:
                connection.execute(
                    text(f"UPDATE user_profiles SET role = :default_role WHERE role NOT IN {VALID_ROLE_LIST}"),
                    {"default_role": DEFAULT_ROLE},
                )

    return get_role_counts(engine)


def get_role_counts(engine: Engine) -> dict[str, int]:
    inspector = inspect(engine)
    if not inspector.has_table("user_profiles"):
        return {"admin": 0, "professor": 0, "student": 0, "parent": 0, "invalid": 0}

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT role, COUNT(*) FROM user_profiles GROUP BY role")
        ).all()
        counts = {"admin": 0, "professor": 0, "student": 0, "parent": 0}
        for role, count in rows:
            if role in counts:
                counts[role] = int(count)

        invalid = connection.execute(
            text(f"SELECT COUNT(*) FROM user_profiles WHERE role NOT IN {VALID_ROLE_LIST}")
        ).scalar_one()
        counts["invalid"] = int(invalid)
        return counts
