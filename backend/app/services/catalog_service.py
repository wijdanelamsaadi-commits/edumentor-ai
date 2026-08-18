from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.persistence import Course, DifficultyLevel, EducationLevel, Subject


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def list_subjects(db: Session, active_only: bool = True) -> list[dict[str, Any]]:
    query = select(Subject).order_by(Subject.display_order, Subject.name)
    if active_only:
        query = query.where(Subject.active.is_(True))
    subjects = list(db.scalars(query))
    course_counts = {
        subject_id: count
        for subject_id, count in db.execute(
            select(Course.subject_id, func.count(Course.id)).group_by(Course.subject_id)
        )
    }
    return [serialize_subject(subject, course_counts.get(subject.id, 0)) for subject in subjects]


def list_education_levels(db: Session, active_only: bool = True) -> list[dict[str, Any]]:
    query = select(EducationLevel).order_by(EducationLevel.display_order, EducationLevel.name)
    if active_only:
        query = query.where(EducationLevel.active.is_(True))
    return [serialize_education_level(item) for item in db.scalars(query)]


def list_difficulty_levels(db: Session, active_only: bool = True) -> list[dict[str, Any]]:
    query = select(DifficultyLevel).order_by(DifficultyLevel.display_order, DifficultyLevel.name)
    if active_only:
        query = query.where(DifficultyLevel.active.is_(True))
    return [serialize_difficulty_level(item) for item in db.scalars(query)]


def create_subject(db: Session, payload: dict) -> dict[str, Any]:
    name = clean_required(payload.get("name"), "Le nom de la matiere est obligatoire")
    slug = clean_slug(payload.get("slug") or slugify(name))
    ensure_unique_subject(db, name, slug)

    subject = Subject(
        name=name,
        slug=slug,
        description=str(payload.get("description") or ""),
        icon=payload.get("icon") or None,
        active=payload.get("active", True) is not False,
        display_order=int(payload.get("display_order", 0) or 0),
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return serialize_subject(subject, 0)


def update_subject(db: Session, subject_id: int, payload: dict) -> dict[str, Any]:
    subject = get_subject_or_404(db, subject_id)
    next_name = clean_required(payload.get("name", subject.name), "Le nom de la matiere est obligatoire")
    next_slug = clean_slug(payload.get("slug", subject.slug) or slugify(next_name))
    ensure_unique_subject(db, next_name, next_slug, excluded_id=subject.id)

    subject.name = next_name
    subject.slug = next_slug
    subject.description = str(payload.get("description", subject.description) or "")
    subject.icon = payload.get("icon", subject.icon)
    subject.active = payload.get("active", subject.active) is not False
    subject.display_order = int(payload.get("display_order", subject.display_order) or 0)
    db.commit()
    db.refresh(subject)
    count = db.scalar(select(func.count(Course.id)).where(Course.subject_id == subject.id)) or 0
    return serialize_subject(subject, int(count))


def delete_subject(db: Session, subject_id: int) -> dict[str, Any]:
    subject = get_subject_or_404(db, subject_id)
    course_count = db.scalar(select(func.count(Course.id)).where(Course.subject_id == subject.id)) or 0
    if course_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible de supprimer une matiere contenant des cours. Desactivez-la a la place.",
        )
    db.delete(subject)
    db.commit()
    return {"deleted": True, "subject_id": subject_id}


def get_subject_or_404(db: Session, subject_id: int) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Matiere introuvable")
    return subject


def ensure_unique_subject(db: Session, name: str, slug: str, excluded_id: int | None = None) -> None:
    query = select(Subject).where((Subject.name == name) | (Subject.slug == slug))
    if excluded_id is not None:
        query = query.where(Subject.id != excluded_id)
    if db.scalars(query).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Une matiere avec ce nom ou slug existe deja")


def clean_required(value: Any, message: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail=message)
    return clean


def clean_slug(value: Any) -> str:
    slug = slugify(str(value or ""))
    if not slug:
        raise HTTPException(status_code=400, detail="Le slug de la matiere est obligatoire")
    return slug


def serialize_subject(subject: Subject, course_count: int = 0) -> dict[str, Any]:
    return {
        "id": subject.id,
        "name": subject.name,
        "slug": subject.slug,
        "description": subject.description,
        "icon": subject.icon,
        "active": subject.active,
        "display_order": subject.display_order,
        "course_count": course_count,
        "created_at": subject.created_at,
        "updated_at": subject.updated_at,
    }


def serialize_education_level(level: EducationLevel) -> dict[str, Any]:
    return {
        "id": level.id,
        "name": level.name,
        "slug": level.slug,
        "description": level.description,
        "display_order": level.display_order,
        "active": level.active,
    }


def serialize_difficulty_level(level: DifficultyLevel) -> dict[str, Any]:
    return {
        "id": level.id,
        "name": level.name,
        "slug": level.slug,
        "display_order": level.display_order,
        "active": level.active,
    }
