from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    PROFESSOR = "professor"
    STUDENT = "student"
    PARENT = "parent"


VALID_ROLES = {role.value for role in UserRole}
DEFAULT_ROLE = UserRole.STUDENT.value


def normalize_role(role: str | None) -> str:
    clean_role = str(role or "").strip().lower()
    if clean_role == "user":
        return UserRole.STUDENT.value
    if clean_role in VALID_ROLES:
        return clean_role
    return DEFAULT_ROLE
