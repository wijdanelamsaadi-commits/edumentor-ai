from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.firebase_auth import verify_firebase_id_token
from app.core.roles import UserRole
from app.models.persistence import UserProfile
from app.services.persistence_service import get_or_create_user_from_firebase

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserProfile:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant",
        )

    decoded_token = verify_firebase_id_token(credentials.credentials)
    user = get_or_create_user_from_firebase(db, decoded_token)
    if user.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte desactive",
        )
    return user


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserProfile | None:
    if credentials is None or not credentials.credentials:
        return None
    return get_current_authenticated_user(credentials, db)


def require_roles(*allowed_roles: str | UserRole) -> Callable[[UserProfile], UserProfile]:
    allowed = {role.value if isinstance(role, UserRole) else str(role) for role in allowed_roles}

    def dependency(current_user: UserProfile = Depends(get_current_authenticated_user)) -> UserProfile:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Role non autorise pour cette ressource",
            )
        return current_user

    return dependency


get_current_user = get_current_authenticated_user
get_current_student = require_roles(UserRole.STUDENT)
get_current_professor = require_roles(UserRole.PROFESSOR)
get_current_parent = require_roles(UserRole.PARENT)
get_current_admin = require_roles(UserRole.ADMIN)
get_current_professor_or_admin = require_roles(UserRole.PROFESSOR, UserRole.ADMIN)
