from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.roles import UserRole
from app.models.persistence import (
    Assessment,
    AssessmentAttempt,
    AssessmentQuestion,
    ClassroomMembership,
    Course,
    CourseChapter,
    Notification,
    PersonalizedLesson,
    RemediationItem,
    RemediationPlan,
    Skill,
    StudyPath,
    StudyPathItem,
    UserProfile,
)

PATH_STATUSES = {"active", "paused", "completed", "archived"}
ITEM_TYPES = {
    "review_chapter",
    "personalized_lesson",
    "knowledge_check",
    "exercise",
    "ask_chatbot",
    "personalized_assessment",
    "view_comparison",
    "continue_course",
    "start_recommended_course",
}
ITEM_STATUSES = {"locked", "available", "in_progress", "completed", "skipped"}


def is_admin(user: UserProfile) -> bool:
    return user.role == UserRole.ADMIN.value


def create_or_refresh_for_plan(db: Session, plan: RemediationPlan) -> StudyPath:
    path = db.scalars(
        select(StudyPath)
        .where(StudyPath.remediation_plan_id == plan.id)
        .options(*path_options())
    ).first()
    if path is None:
        path = StudyPath(
            student_id=plan.student_id,
            subject_id=plan.subject_id,
            course_id=plan.course_id,
            remediation_plan_id=plan.id,
            source_attempt_id=plan.source_attempt_id,
            title=f"Parcours personnalise - {plan.course.title if plan.course else 'cours'}",
            reason="Parcours cree automatiquement a partir des competences a renforcer apres evaluation.",
            status="active",
            active=True,
        )
        db.add(path)
        db.flush()
        create_deduplicated_notification(
            db,
            plan.student_id,
            "study_path",
            "Parcours cree",
            "Votre parcours d'apprentissage personnalise est disponible.",
        )
    sync_path_items(db, path)
    apply_unlocking_rules(db, path)
    update_path_progress(path)
    db.flush()
    return path


def list_student_paths(db: Session, user: UserProfile) -> list[dict]:
    paths = db.scalars(
        select(StudyPath)
        .where(StudyPath.student_id == user.id, StudyPath.active.is_(True))
        .options(*path_options())
        .order_by(StudyPath.updated_at.desc(), StudyPath.id.desc())
    ).all()
    return [serialize_path(db, refresh_existing_path(db, path), detail=False) for path in paths]


def get_student_path(db: Session, user: UserProfile, path_id: int) -> dict:
    path = get_path_for_student(db, user, path_id)
    return serialize_path(db, refresh_existing_path(db, path), detail=True)


def start_item(db: Session, user: UserProfile, path_id: int, item_id: int) -> dict:
    path = get_path_for_student(db, user, path_id)
    refresh_existing_path(db, path)
    item = get_path_item(path, item_id)
    ensure_item_action_allowed(path, item, allow_available=True)
    if item.status == "available":
        item.status = "in_progress"
    apply_unlocking_rules(db, path)
    update_path_progress(path)
    db.commit()
    return serialize_path(db, path, detail=True)


def complete_item(db: Session, user: UserProfile, path_id: int, item_id: int) -> dict:
    path = get_path_for_student(db, user, path_id)
    refresh_existing_path(db, path)
    item = get_path_item(path, item_id)
    ensure_item_action_allowed(path, item, allow_available=True)
    item.status = "completed"
    item.completed_at = item.completed_at or datetime.utcnow()
    apply_unlocking_rules(db, path)
    update_path_progress(path)
    maybe_notify_available_item(db, path)
    db.commit()
    return serialize_path(db, path, detail=True)


def skip_item(db: Session, user: UserProfile, path_id: int, item_id: int) -> dict:
    path = get_path_for_student(db, user, path_id)
    refresh_existing_path(db, path)
    item = get_path_item(path, item_id)
    if item.required:
        raise HTTPException(status_code=422, detail="Une etape obligatoire ne peut pas etre ignoree")
    ensure_item_action_allowed(path, item, allow_available=True)
    item.status = "skipped"
    item.completed_at = item.completed_at or datetime.utcnow()
    apply_unlocking_rules(db, path)
    update_path_progress(path)
    db.commit()
    return serialize_path(db, path, detail=True)


def refresh_student_path(db: Session, user: UserProfile, path_id: int) -> dict:
    path = get_path_for_student(db, user, path_id)
    refresh_existing_path(db, path)
    db.commit()
    return serialize_path(db, path, detail=True)


def list_professor_paths(db: Session, user: UserProfile, filters: dict) -> list[dict]:
    query = select(StudyPath).join(AssessmentAttempt, AssessmentAttempt.id == StudyPath.source_attempt_id).join(Assessment, Assessment.id == AssessmentAttempt.assessment_id).options(*path_options())
    if not is_admin(user):
        query = query.where(Assessment.professor_id == user.id)
    if filters.get("classroom_id"):
        query = query.where(Assessment.classroom_id == int(filters["classroom_id"]))
    if filters.get("course_id"):
        query = query.where(StudyPath.course_id == int(filters["course_id"]))
    if filters.get("student_id"):
        query = query.where(StudyPath.student_id == int(filters["student_id"]))
    if filters.get("status"):
        query = query.where(StudyPath.status == str(filters["status"]))
    paths = db.scalars(query.order_by(StudyPath.updated_at.desc(), StudyPath.id.desc())).all()
    return [serialize_path(db, refresh_existing_path(db, path), detail=False, professor_view=True) for path in paths]


def get_professor_path(db: Session, user: UserProfile, path_id: int) -> dict:
    path = get_path_for_professor(db, user, path_id)
    return serialize_path(db, refresh_existing_path(db, path), detail=True, professor_view=True)


def update_professor_item(db: Session, user: UserProfile, path_id: int, item_id: int, payload: dict) -> dict:
    path = get_path_for_professor(db, user, path_id)
    item = get_path_item(path, item_id)
    for field in ["title", "description", "reason"]:
        if field in payload:
            setattr(item, field, str(payload[field] or "").strip())
    if "required" in payload:
        item.required = payload["required"] is not False
    if "order_index" in payload:
        new_order = int(payload["order_index"])
        if new_order < 1:
            raise HTTPException(status_code=422, detail="Ordre invalide")
        item.order_index = new_order
    path.updated_at = datetime.utcnow()
    apply_unlocking_rules(db, path)
    update_path_progress(path)
    db.commit()
    return serialize_path(db, path, detail=True, professor_view=True)


def get_active_path_summary(db: Session, user: UserProfile) -> dict | None:
    path = db.scalars(
        select(StudyPath)
        .where(StudyPath.student_id == user.id, StudyPath.status == "active", StudyPath.active.is_(True))
        .options(*path_options())
        .order_by(StudyPath.updated_at.desc(), StudyPath.id.desc())
    ).first()
    return serialize_path(db, refresh_existing_path(db, path), detail=False) if path else None


def professor_dashboard_stats(db: Session, user: UserProfile) -> dict:
    paths = list_professor_paths(db, user, {})
    active_paths = [path for path in paths if path["status"] == "active"]
    completed_paths = [path for path in paths if path["status"] == "completed"]
    average_progress = round(sum(path["progress_percentage"] for path in active_paths) / len(active_paths), 2) if active_paths else 0
    blocked = [path for path in active_paths if path["progress"]["blocked_reason"]]
    lesson_done_no_test = [
        path for path in active_paths
        if any(item["item_type"] == "personalized_lesson" and item["status"] == "completed" for item in path["items"])
        and any(item["item_type"] == "personalized_assessment" and item["status"] != "completed" for item in path["items"])
    ]
    not_started = [path for path in active_paths if not any(item["status"] in {"in_progress", "completed", "skipped"} for item in path["items"])]
    return {
        "study_path_active_count": len(active_paths),
        "study_path_completed_count": len(completed_paths),
        "study_path_average_progress": average_progress,
        "study_path_blocked_students": len(blocked),
        "study_path_lessons_done_without_test": len(lesson_done_no_test),
        "study_path_not_started_students": len(not_started),
        "recent_study_paths": active_paths[:5],
    }


def complete_matching_knowledge_check(db: Session, lesson: PersonalizedLesson) -> None:
    path = db.scalars(
        select(StudyPath)
        .where(StudyPath.remediation_plan_id == lesson.remediation_plan_id, StudyPath.student_id == lesson.student_id)
        .options(*path_options())
    ).first()
    if path is None:
        return
    refresh_existing_path(db, path)
    item = next((row for row in path.items if row.item_type == "knowledge_check" and row.entity_id == lesson.id), None)
    if item and item.status in {"available", "in_progress"}:
        item.status = "completed"
        item.completed_at = item.completed_at or datetime.utcnow()
    apply_unlocking_rules(db, path)
    update_path_progress(path)


def refresh_existing_path(db: Session, path: StudyPath | None) -> StudyPath:
    if path is None:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    sync_path_items(db, path)
    apply_unlocking_rules(db, path)
    update_path_progress(path)
    db.flush()
    return path


def sync_path_items(db: Session, path: StudyPath) -> None:
    plan = db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.id == path.remediation_plan_id)
        .options(
            selectinload(RemediationPlan.items).selectinload(RemediationItem.chapter),
            selectinload(RemediationPlan.items).selectinload(RemediationItem.skill),
            selectinload(RemediationPlan.personalized_lessons).selectinload(PersonalizedLesson.skill),
            selectinload(RemediationPlan.personalized_lessons).selectinload(PersonalizedLesson.chapter),
            selectinload(RemediationPlan.course),
        )
    ).first() if path.remediation_plan_id else None
    if plan is None:
        return
    specs = build_item_specs(db, path, plan)
    existing = {(item.item_type, item.entity_id, metadata_key(item)): item for item in path.items}
    for spec in specs:
        key = (spec["item_type"], spec.get("entity_id"), spec["metadata_json"].get("dedupe_key"))
        item = existing.get(key)
        if item is None:
            item = StudyPathItem(study_path_id=path.id, status=spec.get("status", "locked"))
            path.items.append(item)
        item.order_index = spec["order_index"]
        item.item_type = spec["item_type"]
        item.entity_id = spec.get("entity_id")
        item.title = spec["title"]
        item.description = spec.get("description", "")
        item.reason = spec.get("reason", "")
        item.route = spec.get("route", "")
        item.required = spec.get("required", True) is not False
        item.metadata_json = spec.get("metadata_json") or {}
    path.updated_at = datetime.utcnow()


def build_item_specs(db: Session, path: StudyPath, plan: RemediationPlan) -> list[dict]:
    specs = []
    order = 1
    grouped = group_remediation_items(plan.items)
    lessons_by_key = {(lesson.chapter_id, lesson.skill_id): lesson for lesson in plan.personalized_lessons if lesson.active}
    for key, rows in grouped:
        chapter_id, skill_id = key
        chapter = rows[0].chapter if rows and rows[0].chapter else db.get(CourseChapter, chapter_id) if chapter_id else None
        skill = rows[0].skill if rows and rows[0].skill else db.get(Skill, skill_id) if skill_id else None
        label = skill.name if skill else chapter.title if chapter else "Notion ciblee"
        if chapter:
            specs.append(item_spec(order, "review_chapter", chapter.id, f"Revoir : {chapter.title}", "Reprendre le chapitre qui a pose difficulte.", rows[0].reason, f"/courses/{plan.course_id}", True, {"chapter_id": chapter_id, "skill_id": skill_id}))
            order += 1
        lesson = lessons_by_key.get(key)
        if lesson:
            specs.append(item_spec(order, "personalized_lesson", lesson.id, lesson.title, lesson.objective, lesson.reason, f"/personalized-lessons/{lesson.id}", True, {"chapter_id": chapter_id, "skill_id": skill_id}))
            order += 1
            specs.append(item_spec(order, "knowledge_check", lesson.id, f"Valider : {label}", "Repondre au knowledge check du mini-cours.", "Verifier la comprehension avant de continuer.", f"/personalized-lessons/{lesson.id}", True, {"chapter_id": chapter_id, "skill_id": skill_id}))
            order += 1
        specs.append(item_spec(order, "exercise", None, f"Exercice cible : {label}", "Refaire un exercice court sur la notion faible.", "Consolider par la pratique.", f"/courses/{plan.course_id}", True, {"chapter_id": chapter_id, "skill_id": skill_id, "dedupe_key": f"exercise:{chapter_id}:{skill_id}"}))
        order += 1
        specs.append(item_spec(order, "ask_chatbot", None, f"Question au chatbot : {label}", "Demander une explication contextualisee si besoin.", "Etape facultative pour clarifier la notion.", chatbot_route(plan, chapter_id, skill_id), False, {"chapter_id": chapter_id, "skill_id": skill_id, "dedupe_key": f"chatbot:{chapter_id}:{skill_id}"}))
        order += 1

    personalized = latest_personalized_assessment(db, plan)
    specs.append(item_spec(order, "personalized_assessment", personalized.id if personalized else None, "Passer le test personnalise", "Evaluation finale ciblee sur les competences faibles.", "Disponible apres les etapes obligatoires.", f"/assessments/{personalized.id}" if personalized else f"/remediation/{plan.id}", True, {"dedupe_key": "personalized_assessment"}))
    order += 1
    specs.append(item_spec(order, "view_comparison", plan.id, "Voir la comparaison avant / apres", "Analyser les progres apres le test personnalise.", "Disponible apres soumission du test final.", f"/remediation/{plan.id}/comparison", False, {"dedupe_key": "comparison"}))
    order += 1
    next_course = find_next_course(db, plan)
    if next_course:
        specs.append(item_spec(order, "continue_course", next_course.id, f"Continuer : {next_course.title}", next_course.summary or "", "Cours publie recommande dans la meme matiere.", f"/courses/{next_course.id}", False, {"dedupe_key": f"course:{next_course.id}"}))
    else:
        specs.append(item_spec(order, "continue_course", None, "Aucun cours suivant disponible", "Aucun cours suivant n'est encore disponible pour cette matiere et ce niveau.", "Aucun cours publie compatible trouve.", "/courses", False, {"dedupe_key": "course:none", "empty_state": True}))
    return specs


def item_spec(order, item_type, entity_id, title, description, reason, route, required, metadata):
    metadata = metadata or {}
    metadata.setdefault("dedupe_key", f"{item_type}:{entity_id}")
    return {
        "order_index": order,
        "item_type": item_type,
        "entity_id": entity_id,
        "title": title,
        "description": description,
        "reason": reason,
        "route": route,
        "required": required,
        "metadata_json": metadata,
    }


def group_remediation_items(items: list[RemediationItem]) -> list[tuple[tuple[int | None, int | None], list[RemediationItem]]]:
    grouped: dict[tuple[int | None, int | None], list[RemediationItem]] = {}
    for item in sorted(items, key=lambda row: row.order_index):
        if item.completed and item.item_type not in {"chapter", "revision"}:
            pass
        key = (item.chapter_id, item.skill_id)
        grouped.setdefault(key, []).append(item)
    return list(grouped.items())


def apply_unlocking_rules(db: Session, path: StudyPath) -> None:
    ordered = sorted(path.items, key=lambda item: (item.order_index, item.id or 0))
    previous_required_blocking = False
    for item in ordered:
        if item.status in {"completed", "skipped"}:
            continue
        if previous_required_blocking:
            item.status = "locked"
        else:
            item.status = status_from_external_state(db, path, item)
        if item.required and item.status not in {"completed", "skipped"}:
            previous_required_blocking = True
    if path.status == "completed":
        return
    if ordered and all(not item.required or item.status == "completed" for item in ordered):
        path.status = "completed"
        path.completed_at = path.completed_at or datetime.utcnow()
        create_deduplicated_notification(db, path.student_id, "study_path", "Parcours termine", f"{path.title} est termine.")


def status_from_external_state(db: Session, path: StudyPath, item: StudyPathItem) -> str:
    if item.item_type in {"review_chapter", "exercise"} and remediation_group_completed(path, item):
        return "completed"
    if item.item_type == "personalized_lesson" and item.entity_id:
        lesson = db.get(PersonalizedLesson, item.entity_id)
        if lesson and lesson.status == "completed":
            return "completed"
    if item.item_type == "knowledge_check" and item.entity_id:
        previous_lesson_item = first_item(path, "personalized_lesson", item.entity_id)
        if previous_lesson_item and previous_lesson_item.status in {"in_progress", "completed"}:
            return item.status if item.status in {"in_progress", "completed"} else "available"
        return "locked"
    if item.item_type == "personalized_assessment":
        assessment = db.get(Assessment, item.entity_id) if item.entity_id else latest_personalized_assessment(db, path.remediation_plan)
        if not assessment or assessment.status != "published":
            return "locked"
        if completed_attempt_for_assessment(db, path.student_id, assessment.id):
            return "completed"
        return "available"
    if item.item_type == "view_comparison":
        return "available" if has_completed_personalized_attempt(db, path) else "locked"
    if item.item_type == "continue_course":
        return "available" if has_completed_personalized_attempt(db, path) else "locked"
    return item.status if item.status in {"in_progress", "completed"} else "available"


def remediation_group_completed(path: StudyPath, item: StudyPathItem) -> bool:
    plan = path.remediation_plan
    metadata = item.metadata_json or {}
    if plan is None:
        return False
    chapter_id = metadata.get("chapter_id")
    skill_id = metadata.get("skill_id")
    related = [
        row
        for row in plan.items
        if row.chapter_id == chapter_id and row.skill_id == skill_id and row.item_type in {"chapter", "revision", "exercise"}
    ]
    return bool(related) and all(row.completed for row in related)


def update_path_progress(path: StudyPath) -> None:
    required = [item for item in path.items if item.required]
    completed = [item for item in required if item.status == "completed"]
    path.progress_percentage = round((len(completed) / len(required)) * 100, 2) if required else 0
    path.updated_at = datetime.utcnow()


def serialize_path(db: Session, path: StudyPath, detail: bool = True, professor_view: bool = False) -> dict:
    progress = path_progress(path)
    data = {
        "id": path.id,
        "student_id": path.student_id,
        "student_name": path.student.full_name if path.student else "Etudiant",
        "student_email": path.student.email if path.student else "",
        "subject_id": path.subject_id,
        "subject_name": path.subject.name if path.subject else "",
        "course_id": path.course_id,
        "course_title": path.course.title if path.course else "",
        "remediation_plan_id": path.remediation_plan_id,
        "source_attempt_id": path.source_attempt_id,
        "title": path.title,
        "reason": path.reason,
        "status": path.status,
        "progress_percentage": path.progress_percentage,
        "created_at": path.created_at.isoformat() if path.created_at else None,
        "updated_at": path.updated_at.isoformat() if path.updated_at else None,
        "completed_at": path.completed_at.isoformat() if path.completed_at else None,
        "active": path.active,
        "progress": progress,
        "current_item": progress["current_item"],
        "next_item": progress["next_item"],
        "next_action": next_action_from_item(progress["current_item"] or progress["next_item"], path),
    }
    if detail or professor_view:
        data["items"] = [serialize_item(item) for item in sorted(path.items, key=lambda row: (row.order_index, row.id or 0))]
        data["weak_skills"] = weak_skills_for_path(db, path)
        data["personalized_assessment"] = serialize_assessment_summary(latest_personalized_assessment(db, path.remediation_plan)) if path.remediation_plan else None
        data["comparison_available"] = has_completed_personalized_attempt(db, path)
    return data


def path_progress(path: StudyPath) -> dict:
    ordered = sorted(path.items, key=lambda item: (item.order_index, item.id or 0))
    required = [item for item in ordered if item.required]
    completed_required = [item for item in required if item.status == "completed"]
    current = next((item for item in ordered if item.status in {"available", "in_progress"}), None)
    next_item = next((item for item in ordered if item.status == "locked"), None)
    blocked_reason = None
    if next_item and current and current.required:
        blocked_reason = f"Terminez d'abord : {current.title}"
    return {
        "total_items": len(ordered),
        "required_items": len(required),
        "completed_items": len(completed_required),
        "progress_percentage": path.progress_percentage,
        "current_item": serialize_item(current) if current else None,
        "next_item": serialize_item(next_item) if next_item else None,
        "blocked_reason": blocked_reason,
        "estimated_remaining_steps": len([item for item in required if item.status != "completed"]),
    }


def serialize_item(item: StudyPathItem | None) -> dict | None:
    if item is None:
        return None
    return {
        "id": item.id,
        "study_path_id": item.study_path_id,
        "order_index": item.order_index,
        "item_type": item.item_type,
        "entity_id": item.entity_id,
        "title": item.title,
        "description": item.description,
        "reason": item.reason,
        "route": item.route,
        "required": item.required,
        "status": item.status,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "metadata": item.metadata_json or {},
    }


def next_action_from_item(item: dict | None, path: StudyPath) -> dict:
    if item is None:
        return {"type": "continue_course", "label": "Continuer vers le cours suivant", "reason": "Parcours termine ou aucune etape disponible.", "route": "/courses", "path": "/courses", "entity_id": path.course_id}
    return {"type": item["item_type"], "label": item["title"], "reason": item["reason"], "route": item["route"], "path": item["route"], "entity_id": item["entity_id"], "study_path_item_id": item["id"]}


def get_path_for_student(db: Session, user: UserProfile, path_id: int) -> StudyPath:
    path = db.scalars(select(StudyPath).where(StudyPath.id == path_id).options(*path_options())).first()
    if path is None or not path.active:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    if not is_admin(user) and path.student_id != user.id:
        raise HTTPException(status_code=403, detail="Parcours non autorise")
    return path


def get_path_for_professor(db: Session, user: UserProfile, path_id: int) -> StudyPath:
    path = db.scalars(select(StudyPath).where(StudyPath.id == path_id).options(*path_options(), selectinload(StudyPath.source_attempt).selectinload(AssessmentAttempt.assessment))).first()
    if path is None or not path.active:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    assessment = path.source_attempt.assessment if path.source_attempt else None
    if not is_admin(user) and (assessment is None or assessment.professor_id != user.id):
        raise HTTPException(status_code=403, detail="Parcours non autorise")
    return path


def get_path_item(path: StudyPath, item_id: int) -> StudyPathItem:
    item = next((row for row in path.items if row.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Etape introuvable")
    return item


def ensure_item_action_allowed(path: StudyPath, item: StudyPathItem, allow_available: bool) -> None:
    if item.status == "locked":
        raise HTTPException(status_code=409, detail="Etape verrouillee")
    if item.status == "completed":
        return
    allowed = {"in_progress"}
    if allow_available:
        allowed.add("available")
    if item.status not in allowed:
        raise HTTPException(status_code=409, detail="Etape non disponible")


def latest_personalized_assessment(db: Session, plan: RemediationPlan | None) -> Assessment | None:
    if plan is None:
        return None
    return db.scalars(
        select(Assessment)
        .where(Assessment.course_id == plan.course_id, Assessment.assessment_type == "personalized")
        .join(AssessmentQuestion, AssessmentQuestion.assessment_id == Assessment.id)
        .where(AssessmentQuestion.source_attempt_id == plan.source_attempt_id)
        .options(selectinload(Assessment.questions), selectinload(Assessment.course))
        .order_by(Assessment.created_at.desc())
    ).first()


def completed_attempt_for_assessment(db: Session, student_id: int, assessment_id: int) -> AssessmentAttempt | None:
    return db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.student_id == student_id, AssessmentAttempt.assessment_id == assessment_id, AssessmentAttempt.completed.is_(True)).order_by(AssessmentAttempt.submitted_at.desc())).first()


def has_completed_personalized_attempt(db: Session, path: StudyPath) -> bool:
    assessment = latest_personalized_assessment(db, path.remediation_plan)
    return bool(assessment and completed_attempt_for_assessment(db, path.student_id, assessment.id))


def first_item(path: StudyPath, item_type: str, entity_id: int | None) -> StudyPathItem | None:
    return next((item for item in path.items if item.item_type == item_type and item.entity_id == entity_id), None)


def metadata_key(item: StudyPathItem) -> str:
    metadata = item.metadata_json or {}
    return str(metadata.get("dedupe_key") or f"{item.item_type}:{item.entity_id}")


def chatbot_route(plan: RemediationPlan, chapter_id: int | None, skill_id: int | None) -> str:
    return f"/chatbot?course_id={plan.course_id}&subject_id={plan.subject_id}&chapter_id={chapter_id or ''}&skill_id={skill_id or ''}&remediation_plan_id={plan.id}"


def find_next_course(db: Session, plan: RemediationPlan) -> Course | None:
    current = db.get(Course, plan.course_id)
    if current is None:
        return None
    query = select(Course).where(Course.published.is_(True), Course.status == "published", Course.id != current.id)
    if current.subject_id:
        query = query.where(Course.subject_id == current.subject_id)
    if current.education_level_id:
        query = query.where(Course.education_level_id == current.education_level_id)
    if current.difficulty_level_id:
        query = query.where(Course.difficulty_level_id == current.difficulty_level_id)
    return db.scalars(query.order_by(Course.display_order.asc(), Course.id.asc())).first()


def weak_skills_for_path(db: Session, path: StudyPath) -> list[dict]:
    skill_ids = {
        int((item.metadata_json or {}).get("skill_id"))
        for item in path.items
        if (item.metadata_json or {}).get("skill_id")
    }
    if not skill_ids:
        return []
    skills = db.scalars(select(Skill).where(Skill.id.in_(skill_ids))).all()
    return [{"id": skill.id, "name": skill.name, "description": skill.description} for skill in skills]


def serialize_assessment_summary(assessment: Assessment | None) -> dict | None:
    if assessment is None:
        return None
    return {
        "id": assessment.id,
        "title": assessment.title,
        "status": assessment.status,
        "question_count": len([question for question in assessment.questions if question.active]),
    }


def maybe_notify_available_item(db: Session, path: StudyPath) -> None:
    current = path_progress(path)["current_item"]
    if current:
        create_deduplicated_notification(db, path.student_id, "study_path", "Nouvelle etape disponible", current["title"])
    if current and current["item_type"] == "personalized_assessment":
        create_deduplicated_notification(db, path.student_id, "assessment", "Test personnalise debloque", current["title"])
    if current and current["item_type"] == "view_comparison":
        create_deduplicated_notification(db, path.student_id, "study_path", "Comparaison disponible", "Votre comparaison avant / apres est disponible.")


def create_deduplicated_notification(db: Session, user_id: int, notification_type: str, title: str, message: str) -> None:
    exists = db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == notification_type,
            Notification.title == title,
            Notification.message == message,
        )
    ).first()
    if exists:
        return
    from uuid import uuid4

    db.add(Notification(id=str(uuid4()), user_id=user_id, type=notification_type, title=title, message=message, read=False))


def path_options():
    return [
        selectinload(StudyPath.student),
        selectinload(StudyPath.subject),
        selectinload(StudyPath.course),
        selectinload(StudyPath.remediation_plan).selectinload(RemediationPlan.items).selectinload(RemediationItem.chapter),
        selectinload(StudyPath.remediation_plan).selectinload(RemediationPlan.items).selectinload(RemediationItem.skill),
        selectinload(StudyPath.remediation_plan).selectinload(RemediationPlan.personalized_lessons),
        selectinload(StudyPath.items),
    ]
