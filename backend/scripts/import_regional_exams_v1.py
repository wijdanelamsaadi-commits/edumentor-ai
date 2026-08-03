from __future__ import annotations

import argparse
from datetime import datetime
import importlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Iterable

from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.orm import Session, sessionmaker

DATASET_VERSION = "regional-exams-v1-20260802"
IMPORTER_VERSION = "regional-exams-importer-v2-20260802"
DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data" / "regional_exams_v1" / "regional_assessment_payloads_v1.json"


def normalize(value: Any) -> str:
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    ).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def slugify(value: Any) -> str:
    return normalize(value).replace(" ", "-")


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def mapped_keys(model: type) -> set[str]:
    return {prop.key for prop in sa_inspect(model).mapper.attrs}


def column_keys(model: type) -> set[str]:
    return {column.key for column in sa_inspect(model).mapper.columns}


def supported_kwargs(model: type, values: dict[str, Any]) -> dict[str, Any]:
    keys = mapped_keys(model)
    return {key: value for key, value in values.items() if key in keys}


def required_unset_columns(model: type, values: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for column in sa_inspect(model).mapper.columns:
        if column.primary_key and (column.autoincrement is True or column.autoincrement == "auto"):
            continue
        if column.nullable or column.default is not None or column.server_default is not None:
            continue
        if column.key not in values or values.get(column.key) is None:
            missing.append(column.key)
    return missing


def create_instance(model: type, values: dict[str, Any], label: str):
    clean = supported_kwargs(model, values)
    missing = required_unset_columns(model, clean)
    if missing:
        raise RuntimeError(
            f"Impossible de créer {label}: colonnes obligatoires non renseignées: {', '.join(missing)}. "
            "Envoyez backend/app/models/persistence.py pour adapter l'importeur."
        )
    return model(**clean)


def set_supported(instance: Any, values: dict[str, Any]) -> None:
    keys = mapped_keys(type(instance))
    for key, value in values.items():
        if key in keys:
            setattr(instance, key, value)


def get_session_factory():
    database = importlib.import_module("app.core.database")
    for name in ("SessionLocal", "SessionFactory", "session_factory"):
        factory = getattr(database, name, None)
        if factory is not None and callable(factory):
            return factory
    engine = getattr(database, "engine", None)
    if engine is not None:
        return sessionmaker(bind=engine, autoflush=False, autocommit=False)
    raise RuntimeError("Session SQLAlchemy introuvable dans app.core.database")


def load_models() -> dict[str, type]:
    persistence = importlib.import_module("app.models.persistence")
    required = [
        "Assessment",
        "AssessmentQuestion",
        "AssessmentAssignment",
        "UserProfile",
        "LiteraryWork",
        "Course",
        "Subject",
    ]
    models: dict[str, type] = {}
    for name in required:
        model = getattr(persistence, name, None)
        if model is None:
            raise RuntimeError(f"Modèle absent: app.models.persistence.{name}")
        models[name] = model
    for optional in ("Skill", "AssessmentAttempt", "AssessmentAnswer"):
        model = getattr(persistence, optional, None)
        if model is not None:
            models[optional] = model
    return models


def load_payloads(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset introuvable: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or not data:
        raise RuntimeError("Le dataset doit contenir une liste non vide d'examens.")
    for index, payload in enumerate(data, start=1):
        if not isinstance(payload, dict) or not payload.get("external_exam_id") or not payload.get("questions"):
            raise RuntimeError(f"Payload invalide à la position {index}")
    return data


def scalar_attr(row: Any, *names: str) -> Any:
    for name in names:
        if hasattr(row, name):
            value = getattr(row, name)
            if value is not None:
                return value
    return None


def list_students(db: Session, UserProfile: type) -> list[Any]:
    return list(db.scalars(select(UserProfile)))


def student_display(row: Any) -> str:
    name = scalar_attr(row, "full_name", "name", "display_name")
    if not name:
        first = scalar_attr(row, "first_name", "firstname") or ""
        last = scalar_attr(row, "last_name", "lastname") or ""
        name = f"{first} {last}".strip()
    return str(name or f"profil-{getattr(row, 'id', '?')}")


def looks_like_student(row: Any) -> bool:
    role_values = [scalar_attr(row, key) for key in ("role", "user_type", "profile_type", "account_type")]
    present = [normalize(value) for value in role_values if value not in (None, "")]
    if not present:
        return True
    return any(any(token in value for token in ("student", "eleve", "apprenant")) for value in present)


def resolve_students(
    db: Session,
    UserProfile: type,
    student_id: int | None,
    student_name: str | None,
    all_students: bool,
) -> list[Any]:
    rows = list_students(db, UserProfile)
    if student_id is not None:
        selected = [row for row in rows if int(getattr(row, "id")) == int(student_id)]
    elif all_students:
        selected = [row for row in rows if looks_like_student(row)]
    else:
        needle = normalize(student_name or "Malika")
        exact = [row for row in rows if normalize(student_display(row)) == needle]
        selected = exact or [row for row in rows if needle and needle in normalize(student_display(row))]
    if selected:
        return selected
    available = ", ".join(f"{getattr(row, 'id', '?')}:{student_display(row)}" for row in rows[:25]) or "aucun profil"
    raise RuntimeError(
        f"Élève introuvable. Profils disponibles: {available}. "
        "Relancez avec -StudentId <id> ou -StudentName '<nom>'."
    )


def work_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    description = parse_json_object(payload.get("description"))
    metadata = description.get("regional_exam") if isinstance(description.get("regional_exam"), dict) else description
    return dict(metadata or {})


def find_course(db: Session, models: dict[str, type], work_title: str):
    LiteraryWork = models["LiteraryWork"]
    Course = models["Course"]
    works = list(db.scalars(select(LiteraryWork)))
    needle = normalize(work_title)
    exact = [row for row in works if normalize(scalar_attr(row, "title", "name")) == needle]
    candidates = exact or [
        row for row in works
        if needle in normalize(scalar_attr(row, "title", "name"))
        or normalize(scalar_attr(row, "title", "name")) in needle
    ]
    for row in candidates:
        course_id = scalar_attr(row, "course_id")
        if course_id is not None:
            course = db.get(Course, int(course_id))
            if course is not None:
                return course
    courses = list(db.scalars(select(Course)))
    aliases = {needle, "preparation au regional de francais", "regional francais", "francais"}
    exact_courses = [
        row for row in courses
        if normalize(scalar_attr(row, "title", "name")) in aliases
    ]
    fuzzy_courses = exact_courses or [
        row for row in courses
        if needle in normalize(scalar_attr(row, "title", "name"))
        or "regional" in normalize(scalar_attr(row, "title", "name"))
    ]
    if fuzzy_courses:
        return fuzzy_courses[0]
    available = ", ".join(str(scalar_attr(row, "title", "name")) for row in works[:20])
    raise RuntimeError(f"Oeuvre/cours introuvable pour '{work_title}'. Oeuvres disponibles: {available}")


def find_subject(db: Session, models: dict[str, type], course: Any):
    Subject = models["Subject"]
    subject_id = scalar_attr(course, "subject_id")
    if subject_id is not None:
        subject = db.get(Subject, int(subject_id))
        if subject is not None:
            return subject, False
    rows = list(db.scalars(select(Subject)))
    preferred = {"francais", "langue francaise", "french"}
    for row in rows:
        if normalize(scalar_attr(row, "name", "title", "slug")) in preferred:
            return row, False
    values = {
        "name": "Français",
        "slug": "francais",
        "description": "Matière de préparation à l'examen régional de français.",
        "icon": "book-open",
        "active": True,
        "display_order": 0,
    }
    subject = create_instance(Subject, values, "la matière Français")
    db.add(subject)
    db.flush()
    return subject, True


def user_role(row: Any) -> str:
    return normalize(scalar_attr(row, "role", "user_type", "profile_type", "account_type"))


def find_professor(db: Session, models: dict[str, type], course: Any, students: list[Any]):
    UserProfile = models["UserProfile"]
    professor_id = scalar_attr(course, "professor_id")
    if professor_id is not None:
        professor = db.get(UserProfile, int(professor_id))
        if professor is not None:
            return professor, "course.professor_id"
    rows = list(db.scalars(select(UserProfile)))
    student_ids = {int(getattr(row, "id")) for row in students}
    teachers = [row for row in rows if any(token in user_role(row) for token in ("professor", "enseignant", "teacher"))]
    if teachers:
        return teachers[0], "role_professor"
    admins = [row for row in rows if "admin" in user_role(row)]
    if admins:
        return admins[0], "role_admin"
    others = [row for row in rows if int(getattr(row, "id")) not in student_ids]
    if others:
        return others[0], "first_non_student"
    if rows:
        return rows[0], "first_profile"
    raise RuntimeError("Aucun profil disponible pour renseigner professor_id.")


def find_existing_assessment(db: Session, Assessment: type, external_exam_id: str, title: str, course_id: Any):
    rows = list(db.scalars(select(Assessment)))
    for row in rows:
        description = parse_json_object(getattr(row, "description", None))
        metadata = description.get("regional_exam") if isinstance(description.get("regional_exam"), dict) else description
        if metadata.get("external_exam_id") == external_exam_id:
            return row
    for row in rows:
        if normalize(getattr(row, "title", "")) == normalize(title) and getattr(row, "course_id", None) == course_id:
            return row
    return None


def prepare_description(payload: dict[str, Any]) -> str:
    raw = parse_json_object(payload.get("description"))
    if isinstance(raw.get("regional_exam"), dict):
        raw["regional_exam"]["external_exam_id"] = payload["external_exam_id"]
        raw["regional_exam"]["dataset_version"] = DATASET_VERSION
    else:
        raw["external_exam_id"] = payload["external_exam_id"]
        raw["dataset_version"] = DATASET_VERSION
    return json.dumps(raw, ensure_ascii=False)


def assessment_values(
    payload: dict[str, Any],
    course_id: Any,
    professor_id: Any,
    subject_id: Any,
) -> dict[str, Any]:
    total_points = round(sum(float(q.get("points") or 0) for q in payload.get("questions") or []), 2)
    now = datetime.utcnow()
    return {
        "course_id": course_id,
        "professor_id": professor_id,
        "subject_id": subject_id,
        "title": payload.get("title"),
        "description": prepare_description(payload),
        "instructions": payload.get("instructions"),
        "time_limit_minutes": int(payload.get("time_limit_minutes") or 120),
        "max_attempts": int(payload.get("max_attempts") or 3),
        "status": payload.get("status") or "published",
        "passing_score": 50,
        "total_points": total_points,
        "assessment_type": "regional_exam",
        "type": "regional_exam",
        "exam_type": "regional",
        "active": True,
        "is_active": True,
        "published": True,
        "adaptive": False,
        "publication_at": now,
        "available_from": now,
    }


def find_skill(db: Session, models: dict[str, type], competence: str, course_id: Any):
    Skill = models.get("Skill")
    if Skill is None:
        return None
    rows = list(db.scalars(select(Skill)))
    needle = normalize(competence)
    matched = [row for row in rows if normalize(scalar_attr(row, "name", "title", "label")) == needle]
    if course_id is not None:
        same_course = [row for row in matched if getattr(row, "course_id", course_id) == course_id]
        if same_course:
            return same_course[0]
    return matched[0] if matched else None


def create_skill_if_required(db: Session, models: dict[str, type], competence: str, course_id: Any):
    Skill = models.get("Skill")
    AssessmentQuestion = models["AssessmentQuestion"]
    if Skill is None or "skill_id" not in column_keys(AssessmentQuestion):
        return None
    skill_column = next(column for column in sa_inspect(AssessmentQuestion).mapper.columns if column.key == "skill_id")
    if skill_column.nullable:
        return None
    values = {
        "name": competence,
        "title": competence,
        "label": competence,
        "slug": slugify(competence),
        "code": slugify(competence),
        "description": f"Compétence régionale: {competence}",
        "course_id": course_id,
        "active": True,
        "is_active": True,
    }
    skill = create_instance(Skill, values, f"la compétence {competence}")
    db.add(skill)
    db.flush()
    return skill


def question_external_id(question: Any) -> str | None:
    metadata = parse_json_object(getattr(question, "adaptation_reason", None))
    value = metadata.get("question_id")
    return str(value) if value else None


def sync_questions(db: Session, models: dict[str, type], assessment: Any, payload: dict[str, Any], course_id: Any) -> tuple[int, int]:
    AssessmentQuestion = models["AssessmentQuestion"]
    existing_questions = list(getattr(assessment, "questions", []) or [])
    by_external = {question_external_id(row): row for row in existing_questions if question_external_id(row)}
    imported_ids: set[str] = set()
    created = 0
    updated = 0
    skill_cache: dict[str, Any] = {}
    for item in payload.get("questions") or []:
        metadata = parse_json_object(item.get("adaptation_reason"))
        external_id = str(metadata.get("question_id") or f"order-{item.get('order_index')}")
        imported_ids.add(external_id)
        competence = str(metadata.get("competence") or "")
        skill = skill_cache.get(competence)
        if competence and competence not in skill_cache:
            skill = find_skill(db, models, competence, course_id)
            if skill is None:
                skill = create_skill_if_required(db, models, competence, course_id)
            skill_cache[competence] = skill
        values = {
            "assessment_id": getattr(assessment, "id"),
            "skill_id": getattr(skill, "id", None) if skill is not None else None,
            "question": item.get("question"),
            "prompt": item.get("question"),
            "choices": item.get("choices") or [],
            "correct_answer": item.get("correct_answer") or "",
            "explanation": item.get("explanation") or "",
            "points": float(item.get("points") or 0),
            "order_index": int(item.get("order_index") or 0),
            "active": bool(item.get("active", True)),
            "is_active": bool(item.get("active", True)),
            "generation_method": "regional_dataset_import",
            "adaptation_reason": item.get("adaptation_reason") or "{}",
            "question_type": metadata.get("question_type") or "response_short",
            "difficulty": metadata.get("difficulty") or "intermediate",
        }
        row = by_external.get(external_id)
        if row is None:
            row = create_instance(AssessmentQuestion, values, f"la question {external_id}")
            db.add(row)
            created += 1
        else:
            set_supported(row, values)
            updated += 1
    for row in existing_questions:
        ext_id = question_external_id(row)
        if ext_id and ext_id not in imported_ids and hasattr(row, "active"):
            row.active = False
    db.flush()
    return created, updated


def find_assignment(db: Session, AssessmentAssignment: type, assessment_id: int, student_id: int):
    return db.scalars(
        select(AssessmentAssignment).where(
            AssessmentAssignment.assessment_id == assessment_id,
            AssessmentAssignment.student_id == student_id,
        )
    ).first()


def assignment_values(assessment_id: int, student_id: int) -> dict[str, Any]:
    return {
        "assessment_id": assessment_id,
        "student_id": student_id,
        "status": "assigned",
        "assigned_at": datetime.utcnow(),
        "active": True,
        "is_active": True,
    }


def import_dataset(
    db: Session,
    models: dict[str, type],
    payloads: list[dict[str, Any]],
    students: list[Any],
) -> dict[str, int]:
    Assessment = models["Assessment"]
    AssessmentAssignment = models["AssessmentAssignment"]
    stats = {
        "exams_created": 0,
        "exams_updated": 0,
        "questions_created": 0,
        "questions_updated": 0,
        "assignments_created": 0,
        "assignments_existing": 0,
    }
    for payload in payloads:
        metadata = work_metadata(payload)
        work_title = str(metadata.get("work_title") or "").strip()
        if not work_title:
            raise RuntimeError(f"work_title absent pour {payload.get('external_exam_id')}")
        course = find_course(db, models, work_title)
        course_id = int(getattr(course, "id"))
        subject, subject_created = find_subject(db, models, course)
        professor, professor_source = find_professor(db, models, course, students)
        subject_id = int(getattr(subject, "id"))
        professor_id = int(getattr(professor, "id"))
        context_key = (course_id, subject_id, professor_id)
        if context_key not in stats.setdefault("contexts_seen", set()):
            stats["contexts_seen"].add(context_key)
            print(
                "Contexte:",
                f"course={course_id}:{scalar_attr(course, 'title', 'name')}",
                f"subject={subject_id}:{scalar_attr(subject, 'name', 'title')}" + (" (cree)" if subject_created else ""),
                f"professor={professor_id}:{student_display(professor)} ({professor_source})",
            )
        assessment = find_existing_assessment(
            db,
            Assessment,
            str(payload["external_exam_id"]),
            str(payload.get("title") or ""),
            course_id,
        )
        values = assessment_values(payload, course_id, professor_id, subject_id)
        if assessment is None:
            assessment = create_instance(Assessment, values, f"l'examen {payload['external_exam_id']}")
            db.add(assessment)
            db.flush()
            stats["exams_created"] += 1
        else:
            set_supported(assessment, values)
            db.flush()
            stats["exams_updated"] += 1
        created, updated = sync_questions(db, models, assessment, payload, course_id)
        stats["questions_created"] += created
        stats["questions_updated"] += updated
        for student in students:
            student_id = int(getattr(student, "id"))
            assignment = find_assignment(db, AssessmentAssignment, int(getattr(assessment, "id")), student_id)
            if assignment is None:
                assignment = create_instance(
                    AssessmentAssignment,
                    assignment_values(int(getattr(assessment, "id")), student_id),
                    f"l'affectation examen={assessment.id}, élève={student_id}",
                )
                db.add(assignment)
                stats["assignments_created"] += 1
            else:
                stats["assignments_existing"] += 1
    db.flush()
    stats.pop("contexts_seen", None)
    return stats


def verify_dataset(db: Session, models: dict[str, type], payloads: list[dict[str, Any]], students: list[Any]) -> dict[str, Any]:
    Assessment = models["Assessment"]
    AssessmentAssignment = models["AssessmentAssignment"]
    ids = {str(payload["external_exam_id"]) for payload in payloads}
    expected_questions = sum(len(payload.get("questions") or []) for payload in payloads)
    imported = []
    for row in db.scalars(select(Assessment)):
        metadata = work_metadata({"description": getattr(row, "description", None)})
        if metadata.get("external_exam_id") in ids:
            imported.append(row)
    imported_ids = {int(getattr(row, "id")) for row in imported}
    AssessmentQuestion = models["AssessmentQuestion"]
    actual_questions = (
        db.scalar(
            select(func.count(AssessmentQuestion.id)).where(AssessmentQuestion.assessment_id.in_(imported_ids))
        )
        if imported_ids
        else 0
    ) or 0
    student_ids = {int(getattr(row, "id")) for row in students}
    assignments = list(db.scalars(select(AssessmentAssignment)))
    actual_assignments = sum(
        1 for row in assignments
        if int(getattr(row, "assessment_id")) in imported_ids and int(getattr(row, "student_id")) in student_ids
    )
    expected_assignments = len(imported) * len(students)
    return {
        "exams": len(imported),
        "expected_exams": len(payloads),
        "questions": actual_questions,
        "expected_questions": expected_questions,
        "assignments": actual_assignments,
        "expected_assignments": expected_assignments,
        "ok": (
            len(imported) == len(payloads)
            and actual_questions >= expected_questions
            and actual_assignments == expected_assignments
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Importer les examens régionaux EduMentor dans SQLAlchemy.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--student-id", type=int)
    parser.add_argument("--student-name", default="Malika")
    parser.add_argument("--all-students", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    payloads = load_payloads(args.dataset.resolve())
    models = load_models()
    SessionFactory = get_session_factory()
    db: Session = SessionFactory()
    try:
        students = resolve_students(db, models["UserProfile"], args.student_id, args.student_name, args.all_students)
        print("Élève(s):", ", ".join(f"{row.id}:{student_display(row)}" for row in students))
        stats = import_dataset(db, models, payloads, students)
        verification = verify_dataset(db, models, payloads, students)
        if args.dry_run:
            db.rollback()
            print("DRY-RUN RÉUSSI — aucune modification enregistrée.")
        else:
            if not verification["ok"]:
                raise RuntimeError(f"Vérification incomplète avant commit: {verification}")
            db.commit()
            print("IMPORT RÉUSSI")
        print(json.dumps({"dataset_version": DATASET_VERSION, "importer_version": IMPORTER_VERSION, **stats, "verification": verification}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERREUR IMPORT: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
