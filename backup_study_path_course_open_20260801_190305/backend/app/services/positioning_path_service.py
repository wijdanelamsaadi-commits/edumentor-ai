from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import (
    Course,
    CourseChapter,
    DiagnosticResult,
    Notification,
    StudyPath,
    StudyPathItem,
    UserProfile,
)

COMPETENCE_LABELS = {
    "comprehension": "Compréhension",
    "langue_grammaire": "Langue et grammaire",
    "connaissance_oeuvres": "Connaissance des œuvres",
    "figures_procedes": "Figures de style et procédés",
    "interpretation_justification": "Interprétation et justification",
}

COMPETENCE_KEYWORDS = {
    "comprehension": ["comprehension", "lecture", "texte", "analyse", "sens"],
    "langue_grammaire": ["langue", "grammaire", "conjugaison", "vocabulaire", "syntaxe"],
    "connaissance_oeuvres": ["oeuvre", "roman", "antigone", "merveilles", "condamne", "auteur"],
    "figures_procedes": ["figure", "style", "procede", "metaphore", "comparaison", "personnification"],
    "interpretation_justification": ["interpretation", "justification", "argument", "analyse", "preuve"],
}


def create_or_refresh_from_diagnostic(
    db: Session,
    student: UserProfile,
    diagnostic_result: DiagnosticResult,
    recommendations: list[dict[str, Any]] | None = None,
    results_by_topic: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not diagnostic_result.subject_id:
        return None
    if not is_french_subject(diagnostic_result.subject):
        return None

    recommendations = recommendations or list(diagnostic_result.recommendations or [])
    results_by_topic = results_by_topic or list(diagnostic_result.results_by_topic or [])
    course = choose_course(
        db,
        diagnostic_result.subject_id,
        diagnostic_result.education_level_id,
        recommendations,
    )
    if course is None:
        return None

    weakest = weakest_topic(results_by_topic)
    weakest_key = weakest.get("name") or "comprehension"
    weakest_label = competence_label(weakest_key)
    weakest_percentage = int(weakest.get("percentage") or 0)

    path = db.scalars(
        select(StudyPath)
        .where(StudyPath.source_diagnostic_result_id == diagnostic_result.id)
        .options(selectinload(StudyPath.items))
    ).first()

    if path is None:
        previous_paths = db.scalars(
            select(StudyPath).where(
                StudyPath.student_id == student.id,
                StudyPath.subject_id == diagnostic_result.subject_id,
                StudyPath.source_diagnostic_result_id.is_not(None),
                StudyPath.active.is_(True),
            )
        ).all()
        for previous in previous_paths:
            previous.active = False
            if previous.status == "active":
                previous.status = "archived"
            previous.updated_at = datetime.utcnow()

        path = StudyPath(
            student_id=student.id,
            subject_id=diagnostic_result.subject_id,
            course_id=course.id,
            remediation_plan_id=None,
            source_attempt_id=None,
            source_diagnostic_result_id=diagnostic_result.id,
            title=f"Parcours personnalisé — {course.title}",
            reason=(
                f"Créé après le test de positionnement. Priorité : "
                f"{weakest_label} ({weakest_percentage} %)."
            ),
            status="active",
            progress_percentage=0,
            active=True,
        )
        db.add(path)
        db.flush()
    else:
        path.course_id = course.id
        path.title = f"Parcours personnalisé — {course.title}"
        path.reason = (
            f"Créé après le test de positionnement. Priorité : "
            f"{weakest_label} ({weakest_percentage} %)."
        )
        path.status = "active"
        path.active = True
        path.completed_at = None
        path.updated_at = datetime.utcnow()
        path.items.clear()
        db.flush()

    specs = build_item_specs(
        course,
        weakest_key=weakest_key,
        weakest_label=weakest_label,
        diagnostic_result_id=diagnostic_result.id,
        recommendations=recommendations,
    )

    for index, spec in enumerate(specs, start=1):
        path.items.append(
            StudyPathItem(
                order_index=index,
                item_type=spec["item_type"],
                entity_id=spec.get("entity_id"),
                title=spec["title"],
                description=spec.get("description", ""),
                reason=spec.get("reason", ""),
                route=spec.get("route", ""),
                required=spec.get("required", True) is not False,
                status="available" if index == 1 else "locked",
                metadata_json=spec.get("metadata") or {},
            )
        )

    path.progress_percentage = 0
    path.updated_at = datetime.utcnow()
    create_notification_once(
        db,
        student.id,
        "study_path",
        "Parcours personnalisé disponible",
        f"Votre parcours prioritaire en {weakest_label} est prêt.",
    )
    db.flush()

    return serialize_path_summary(path, weakest_label, weakest_percentage)


def is_french_subject(subject) -> bool:
    if subject is None:
        return False
    value = f"{getattr(subject, 'slug', '')} {getattr(subject, 'name', '')}"
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).lower()
    return "francais" in normalized


def choose_course(
    db: Session,
    subject_id: int,
    education_level_id: int | None,
    recommendations: list[dict[str, Any]],
) -> Course | None:
    recommendation_ids = [
        int(item["course_id"])
        for item in recommendations
        if isinstance(item, dict) and item.get("course_id")
    ]
    for course_id in recommendation_ids:
        course = db.scalars(
            select(Course)
            .where(
                Course.id == course_id,
                Course.subject_id == subject_id,
                Course.published.is_(True),
            )
            .options(selectinload(Course.chapters))
        ).first()
        if course is not None:
            return course

    query = (
        select(Course)
        .where(
            Course.subject_id == subject_id,
            Course.published.is_(True),
        )
        .options(selectinload(Course.chapters))
        .order_by(Course.display_order.asc(), Course.id.asc())
    )
    if education_level_id:
        query = query.where(
            (Course.education_level_id == education_level_id)
            | (Course.education_level_id.is_(None))
        )
    return db.scalars(query).first()


def build_item_specs(
    course: Course,
    *,
    weakest_key: str,
    weakest_label: str,
    diagnostic_result_id: int,
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    chapters = select_priority_chapters(course, weakest_key, limit=3)

    if chapters:
        for chapter in chapters:
            specs.append({
                "item_type": "review_chapter",
                "entity_id": chapter.id,
                "title": f"Revoir : {chapter.title}",
                "description": "Relisez le cours et notez les idées essentielles.",
                "reason": f"Étape prioritaire pour renforcer {weakest_label}.",
                "route": f"/courses/{course.id}",
                "required": True,
                "metadata": {
                    "chapter_id": chapter.id,
                    "competence": weakest_key,
                    "diagnostic_result_id": diagnostic_result_id,
                    "dedupe_key": f"diagnostic-review:{diagnostic_result_id}:{chapter.id}",
                },
            })
            specs.append({
                "item_type": "exercise",
                "entity_id": chapter.id,
                "title": f"S'entraîner : {chapter.title}",
                "description": "Réalisez les exercices interactifs du chapitre.",
                "reason": "La pratique permet de vérifier et consolider la compréhension.",
                "route": f"/courses/{course.id}",
                "required": True,
                "metadata": {
                    "chapter_id": chapter.id,
                    "competence": weakest_key,
                    "diagnostic_result_id": diagnostic_result_id,
                    "dedupe_key": f"diagnostic-exercise:{diagnostic_result_id}:{chapter.id}",
                },
            })
    else:
        specs.append({
            "item_type": "start_recommended_course",
            "entity_id": course.id,
            "title": f"Commencer : {course.title}",
            "description": course.summary or "Commencez le cours recommandé pour votre niveau.",
            "reason": f"Cours choisi pour renforcer {weakest_label}.",
            "route": f"/courses/{course.id}",
            "required": True,
            "metadata": {
                "course_id": course.id,
                "competence": weakest_key,
                "diagnostic_result_id": diagnostic_result_id,
                "dedupe_key": f"diagnostic-course:{diagnostic_result_id}:{course.id}",
            },
        })

    specs.append({
        "item_type": "ask_chatbot",
        "entity_id": course.id,
        "title": f"Demander une explication sur {weakest_label}",
        "description": "Utilisez le chatbot pédagogique pour clarifier une notion difficile.",
        "reason": "Étape facultative d'accompagnement.",
        "route": (
            f"/chatbot?course_id={course.id}"
            f"&subject_id={course.subject_id or ''}"
            f"&diagnostic_result_id={diagnostic_result_id}"
        ),
        "required": False,
        "metadata": {
            "course_id": course.id,
            "competence": weakest_key,
            "diagnostic_result_id": diagnostic_result_id,
            "dedupe_key": f"diagnostic-chatbot:{diagnostic_result_id}:{course.id}",
        },
    })

    seen = {course.id}
    for recommendation in recommendations:
        if not isinstance(recommendation, dict) or not recommendation.get("course_id"):
            continue
        course_id = int(recommendation["course_id"])
        if course_id in seen:
            continue
        seen.add(course_id)
        specs.append({
            "item_type": "start_recommended_course",
            "entity_id": course_id,
            "title": f"Découvrir : {recommendation.get('title') or 'Cours recommandé'}",
            "description": "Cours complémentaire adapté au niveau détecté.",
            "reason": recommendation.get("reason") or "Recommandation issue du test.",
            "route": recommendation.get("path") or f"/courses/{course_id}",
            "required": False,
            "metadata": {
                "course_id": course_id,
                "diagnostic_result_id": diagnostic_result_id,
                "dedupe_key": f"diagnostic-recommendation:{diagnostic_result_id}:{course_id}",
            },
        })
        if len(seen) >= 3:
            break

    return specs


def select_priority_chapters(
    course: Course,
    weakest_key: str,
    limit: int = 3,
) -> list[CourseChapter]:
    chapters = [chapter for chapter in (course.chapters or []) if chapter.active]
    if not chapters:
        return []

    keywords = COMPETENCE_KEYWORDS.get(weakest_key, [])
    scored = []
    for chapter in chapters:
        searchable = normalize_text(
            " ".join([
                chapter.title or "",
                chapter.content or "",
                json.dumps(chapter.structured_content or {}, ensure_ascii=False),
            ])
        )
        score = sum(1 for keyword in keywords if normalize_text(keyword) in searchable)
        scored.append((score, chapter.position, chapter.id, chapter))

    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [row[3] for row in scored[:limit]]


def weakest_topic(results_by_topic: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        item for item in results_by_topic
        if isinstance(item, dict) and item.get("name") is not None
    ]
    if not valid:
        return {"name": "comprehension", "percentage": 0}
    return min(valid, key=lambda item: float(item.get("percentage") or 0))


def competence_label(value: str) -> str:
    return COMPETENCE_LABELS.get(value, str(value or "Compétence prioritaire").replace("_", " ").title())


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_accents = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", without_accents.lower()).strip()


def create_notification_once(
    db: Session,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
) -> None:
    exists = db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == notification_type,
            Notification.title == title,
            Notification.message == message,
        )
    ).first()
    if exists is None:
        db.add(Notification(
            id=str(uuid4()),
            user_id=user_id,
            type=notification_type,
            title=title,
            message=message,
            read=False,
        ))


def serialize_path_summary(
    path: StudyPath,
    weakest_label: str,
    weakest_percentage: int,
) -> dict[str, Any]:
    first_item = sorted(path.items, key=lambda item: item.order_index)[0] if path.items else None
    return {
        "id": path.id,
        "title": path.title,
        "course_id": path.course_id,
        "subject_id": path.subject_id,
        "source_diagnostic_result_id": path.source_diagnostic_result_id,
        "progress_percentage": path.progress_percentage,
        "weakest_competence": {
            "name": weakest_label,
            "percentage": weakest_percentage,
        },
        "next_action": {
            "label": first_item.title if first_item else "Ouvrir le parcours",
            "route": first_item.route if first_item else f"/study-paths/{path.id}",
        },
    }
