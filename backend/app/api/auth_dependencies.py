from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.firebase_auth import verify_firebase_id_token
from app.models.persistence import UserProfile
from app.services.persistence_service import get_or_create_user_from_firebase

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserProfile:
    token = credentials.credentials
    decoded_token = verify_firebase_id_token(token)
    user = get_or_create_user_from_firebase(db, decoded_token)
    if user.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte desactive",
        )
    return user


def get_current_admin(current_user: UserProfile = Depends(get_current_user)) -> UserProfile:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs",
        )

    return current_user
