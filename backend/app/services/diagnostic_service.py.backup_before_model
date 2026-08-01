from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import (
    Course,
    Classroom,
    ClassroomMembership,
    DiagnosticAnswer,
    DiagnosticQuestion,
    DiagnosticResult,
    DiagnosticSession,
    DifficultyLevel,
    EducationLevel,
    PedagogicalPackageImportJob,
    Subject,
    UserProfile,
)

DEFAULT_LIMIT = 20
MIN_TEST_QUESTIONS = 20
TARGET_DISTRIBUTION = {"debutant": 7, "intermediaire": 7, "avance": 6}

POSITIONING_COMPETENCES = [
    "comprehension",
    "langue_grammaire",
    "connaissance_oeuvres",
    "figures_procedes",
    "interpretation_justification",
]

# Chaque compétence fournit exactement 4 questions.
# Au total : 7 débutant, 7 intermédiaire et 6 avancé.
POSITIONING_QUOTAS_20 = [
    {"debutant": 2, "intermediaire": 1, "avance": 1},
    {"debutant": 2, "intermediaire": 1, "avance": 1},
    {"debutant": 1, "intermediaire": 2, "avance": 1},
    {"debutant": 1, "intermediaire": 2, "avance": 1},
    {"debutant": 1, "intermediaire": 1, "avance": 2},
]
LEVEL_RULES = [
    (40, "Débutant", "debutant"),
    (70, "Intermédiaire", "intermediaire"),
    (101, "Avancé", "avance"),
]


def get_question_set(
    db: Session,
    subject_id: int,
    education_level_id: int | None = None,
    limit: int = DEFAULT_LIMIT,
    student: UserProfile | None = None,
) -> dict[str, Any]:
    subject = require_active_subject(db, subject_id)
    validate_education_level(db, education_level_id)
    requested_limit = normalize_limit(limit)
    current_package = resolve_current_diagnostic_package(db, student, subject_id, education_level_id)
    if current_package is None and has_imported_diagnostic_context(db, student, subject_id, education_level_id):
        all_questions = []
    else:
        all_questions = fetch_active_questions(db, subject_id, education_level_id, current_package)
    if len(all_questions) < requested_limit:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Banque de questions insuffisante pour lancer le test",
                "available_count": len(all_questions),
                "questions_per_test": requested_limit,
                "missing_count": max(0, requested_limit - len(all_questions)),
            },
        )
    questions = balanced_pick(all_questions, requested_limit)
    return {
        "subject": serialize_subject(subject),
        "education_level_id": education_level_id,
        "total": len(questions),
        "available_count": len(all_questions),
        "active_package": serialize_current_package(current_package),
        "estimated_duration": f"{max(5, len(questions))} min",
        "objective": "Identifier votre niveau dans cette matiere et proposer les cours les plus adaptes.",
        "session_id": None,
        "questions": [serialize_public_question(question) for question in questions],
    }


def get_question_availability(
    db: Session,
    subject_id: int,
    education_level_id: int | None = None,
    limit: int = DEFAULT_LIMIT,
    student: UserProfile | None = None,
) -> dict[str, Any]:
    subject = require_active_subject(db, subject_id)
    validate_education_level(db, education_level_id)
    requested_limit = normalize_limit(limit)
    current_package = resolve_current_diagnostic_package(db, student, subject_id, education_level_id)
    if current_package is None and has_imported_diagnostic_context(db, student, subject_id, education_level_id):
        questions = []
    else:
        questions = fetch_active_questions(db, subject_id, education_level_id, current_package)
    counts = Counter(question.difficulty_level.slug if question.difficulty_level else "inconnu" for question in questions)
    missing_count = max(0, requested_limit - len(questions))
    return {
        "subject": serialize_subject(subject),
        "education_level_id": education_level_id,
        "available_count": len(questions),
        "questions_per_test": requested_limit,
        "active_package": serialize_current_package(current_package),
        "estimated_duration": f"{max(10, requested_limit // 2)} a {max(20, requested_limit)} min",
        "minimum_required": requested_limit,
        "missing_count": missing_count,
        "can_start": missing_count == 0,
        "by_difficulty": dict(counts),
    }


def submit_positioning_test(db: Session, student: UserProfile, payload: dict[str, Any]) -> dict[str, Any]:
    subject_id = int(payload.get("subject_id") or 0)
    subject = require_active_subject(db, subject_id)
    education_level_id = payload.get("education_level_id")
    session_id = payload.get("session_id")
    raw_answers = payload.get("answers") or {}
    answers = normalize_answers(raw_answers)
    if not answers:
        raise HTTPException(status_code=400, detail="Aucune reponse envoyee")

    current_package = resolve_current_diagnostic_package(db, student, subject_id, education_level_id)
    session = get_or_create_session(db, student, subject_id, education_level_id, session_id, current_package)
    question_ids = [int(question_id) for question_id in answers.keys()]
    questions = list(db.scalars(
        select(DiagnosticQuestion)
        .options(selectinload(DiagnosticQuestion.difficulty_level))
        .where(
            DiagnosticQuestion.id.in_(question_ids),
            DiagnosticQuestion.subject_id == subject_id,
            DiagnosticQuestion.active.is_(True),
        )
    ).unique())
    if current_package is not None:
        questions = [question for question in questions if question.import_job_id == current_package.id]
    question_by_id = {question.id: question for question in questions}

    corrections = []
    correct_count = 0
    topic_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    difficulty_stats = defaultdict(lambda: {"correct": 0, "total": 0})

    session.answers.clear()
    for question_id, selected in answers.items():
        question = question_by_id.get(int(question_id))
        if question is None:
            continue
        selected_answer = selected_to_answer(question, selected)
        is_correct = selected_answer == question.correct_answer
        if is_correct:
            correct_count += 1
        topic = question.topic or "General"
        difficulty_slug = question.difficulty_level.slug if question.difficulty_level else "inconnu"
        topic_stats[topic]["total"] += 1
        difficulty_stats[difficulty_slug]["total"] += 1
        if is_correct:
            topic_stats[topic]["correct"] += 1
            difficulty_stats[difficulty_slug]["correct"] += 1
        session.answers.append(DiagnosticAnswer(
            question_id=question.id,
            selected_answer=selected_answer,
            correct=is_correct,
        ))
        corrections.append({
            "id": question.id,
            "theme": topic,
            "topic": topic,
            "question": question.question,
            "options": question.choices,
            "user_answer": selected,
            "selected_answer": selected_answer,
            "correct_answer": question.correct_answer,
            "is_correct": is_correct,
            "explanation": question.explanation,
        })

    total = len(corrections)
    if total == 0:
        raise HTTPException(status_code=400, detail="Aucune question valide pour cette matiere")
    score = round((correct_count / total) * 100)
    results_by_topic = format_stats(topic_stats)
    results_by_difficulty = format_stats(difficulty_stats)
    level, difficulty_slug = detect_level(score, results_by_difficulty)
    difficulty = db.scalars(select(DifficultyLevel).where(DifficultyLevel.slug == difficulty_slug)).first()
    recommendations = build_recommendations(db, subject_id, education_level_id, difficulty_slug, results_by_topic)
    strengths, gaps = split_strengths_and_gaps(results_by_topic)
    justification = build_justification(level, results_by_difficulty)

    session.score = score
    session.percentage = float(score)
    session.detected_difficulty_level_id = difficulty.id if difficulty else None
    session.import_job_id = current_package.id if current_package else None
    session.imported_package_hash = current_package.json_sha256 if current_package else None
    session.status = "completed"
    session.completed = True
    session.submitted_at = datetime.utcnow()

    diagnostic_result = DiagnosticResult(
        user_id=student.id,
        subject_id=subject_id,
        education_level_id=education_level_id,
        detected_difficulty_level_id=difficulty.id if difficulty else None,
        score=score,
        level=level,
        total=total,
        correct_count=correct_count,
        corrections=corrections,
        results_by_topic=results_by_topic,
        results_by_difficulty=results_by_difficulty,
        recommendations=recommendations,
        justification=justification,
    )
    db.add(diagnostic_result)
    db.commit()
    db.refresh(diagnostic_result)
    db.refresh(session)

    return serialize_result(diagnostic_result, subject, recommendations, strengths, gaps)


def get_latest_results_by_subject(db: Session, student: UserProfile) -> list[dict[str, Any]]:
    rows = list(db.scalars(
        select(DiagnosticResult)
        .options(selectinload(DiagnosticResult.subject), selectinload(DiagnosticResult.detected_difficulty_level))
        .where(DiagnosticResult.user_id == student.id)
        .order_by(DiagnosticResult.created_at.desc())
    ).unique())
    latest = {}
    for row in rows:
        key = row.subject_id or 0
        if key not in latest:
            latest[key] = serialize_saved_result(row)
    return list(latest.values())


def list_admin_questions(
    db: Session,
    subject_id: int | None = None,
    education_level_id: int | None = None,
    source_course_id: int | None = None,
    difficulty_level_id: int | None = None,
    active: bool | None = None,
    generation_method: str | None = None,
) -> list[dict[str, Any]]:
    query = (
        select(DiagnosticQuestion)
        .options(
            selectinload(DiagnosticQuestion.subject),
            selectinload(DiagnosticQuestion.education_level),
            selectinload(DiagnosticQuestion.difficulty_level),
            selectinload(DiagnosticQuestion.source_course),
        )
        .order_by(DiagnosticQuestion.subject_id, DiagnosticQuestion.id)
    )
    if subject_id:
        query = query.where(DiagnosticQuestion.subject_id == subject_id)
    if education_level_id:
        query = query.where(DiagnosticQuestion.education_level_id == education_level_id)
    if source_course_id:
        query = query.where(DiagnosticQuestion.source_course_id == source_course_id)
    if difficulty_level_id:
        query = query.where(DiagnosticQuestion.difficulty_level_id == difficulty_level_id)
    if active is not None:
        query = query.where(DiagnosticQuestion.active.is_(active))
    if generation_method:
        query = query.where(DiagnosticQuestion.generation_method == generation_method)
    return [serialize_admin_question(question) for question in db.scalars(query).unique()]


def create_admin_question(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    question = DiagnosticQuestion(**clean_question_payload(db, payload))
    db.add(question)
    db.commit()
    db.refresh(question)
    return serialize_admin_question(question)


def update_admin_question(db: Session, question_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    question = db.get(DiagnosticQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable")
    for field, value in clean_question_payload(db, payload, partial=True).items():
        setattr(question, field, value)
    question.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(question)
    return serialize_admin_question(question)


def deactivate_admin_question(db: Session, question_id: int) -> dict[str, Any]:
    question = db.get(DiagnosticQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question introuvable")
    question.active = False
    question.updated_at = datetime.utcnow()
    db.commit()
    return {"id": question_id, "active": False}


def clean_question_payload(db: Session, payload: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    data = {}
    required = [] if partial else ["subject_id", "difficulty_level_id", "question", "choices", "correct_answer"]
    for field in required:
        if payload.get(field) in (None, "", []):
            raise HTTPException(status_code=400, detail=f"Champ obligatoire: {field}")

    if "subject_id" in payload:
        require_active_subject(db, int(payload["subject_id"]))
        data["subject_id"] = int(payload["subject_id"])
    if "education_level_id" in payload:
        data["education_level_id"] = int(payload["education_level_id"]) if payload["education_level_id"] else None
    if "difficulty_level_id" in payload:
        difficulty = db.get(DifficultyLevel, int(payload["difficulty_level_id"]))
        if difficulty is None:
            raise HTTPException(status_code=404, detail="Difficulte introuvable")
        data["difficulty_level_id"] = difficulty.id
    if "topic" in payload:
        data["topic"] = str(payload.get("topic") or "").strip() or None
    if "question" in payload:
        data["question"] = str(payload.get("question") or "").strip()
    if "choices" in payload:
        choices = payload.get("choices") or []
        if not isinstance(choices, list) or len([choice for choice in choices if str(choice).strip()]) < 2:
            raise HTTPException(status_code=400, detail="Au moins deux choix sont obligatoires")
        data["choices"] = [str(choice).strip() for choice in choices if str(choice).strip()]
    if "correct_answer" in payload:
        correct = str(payload.get("correct_answer") or "").strip()
        choices = data.get("choices") or payload.get("choices") or []
        if choices and correct not in choices:
            raise HTTPException(status_code=400, detail="La bonne reponse doit faire partie des choix")
        data["correct_answer"] = correct
    if "explanation" in payload:
        data["explanation"] = str(payload.get("explanation") or "").strip()
    if "active" in payload:
        data["active"] = payload.get("active") is not False
    return data


def require_active_subject(db: Session, subject_id: int) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None or not subject.active:
        raise HTTPException(status_code=404, detail="Matiere introuvable")
    return subject


def validate_education_level(db: Session, education_level_id: int | None) -> None:
    if education_level_id is None:
        return
    education_level = db.get(EducationLevel, education_level_id)
    if education_level is None or not education_level.active:
        raise HTTPException(status_code=404, detail="Niveau d'etudes introuvable")


def normalize_limit(limit: int | None) -> int:
    return max(1, min(int(limit or DEFAULT_LIMIT), 30))


def fetch_active_questions(
    db: Session,
    subject_id: int,
    education_level_id: int | None,
    current_package: PedagogicalPackageImportJob | None = None,
) -> list[DiagnosticQuestion]:
    query = (
        select(DiagnosticQuestion)
        .options(selectinload(DiagnosticQuestion.difficulty_level))
        .where(DiagnosticQuestion.subject_id == subject_id, DiagnosticQuestion.active.is_(True))
        .order_by(DiagnosticQuestion.id)
    )
    if education_level_id is not None:
        query = query.where(
            (DiagnosticQuestion.education_level_id == education_level_id)
            | (DiagnosticQuestion.education_level_id.is_(None))
        )
    if current_package is not None:
        query = query.where(DiagnosticQuestion.import_job_id == current_package.id)
    return list(db.scalars(query).unique())


def resolve_current_diagnostic_package(
    db: Session,
    student: UserProfile | None,
    subject_id: int,
    education_level_id: int | None,
) -> PedagogicalPackageImportJob | None:
    if student is None or student.role != "student":
        return None

    classroom_ids = list(db.scalars(
        select(ClassroomMembership.classroom_id)
        .join(Classroom, Classroom.id == ClassroomMembership.classroom_id)
        .where(
            ClassroomMembership.student_id == student.id,
            ClassroomMembership.active.is_(True),
            Classroom.active.is_(True),
        )
    ))
    if not classroom_ids:
        return None

    query = (
        select(PedagogicalPackageImportJob)
        .where(
            PedagogicalPackageImportJob.classroom_id.in_(classroom_ids),
            PedagogicalPackageImportJob.subject_id == subject_id,
            PedagogicalPackageImportJob.status == "completed",
            PedagogicalPackageImportJob.is_current.is_(True),
        )
        .order_by(PedagogicalPackageImportJob.completed_at.desc(), PedagogicalPackageImportJob.id.desc())
    )
    if education_level_id is not None:
        query = query.where(PedagogicalPackageImportJob.education_level_id == education_level_id)
    return db.scalars(query).first()


def has_imported_diagnostic_context(
    db: Session,
    student: UserProfile | None,
    subject_id: int,
    education_level_id: int | None,
) -> bool:
    if student is None or student.role != "student":
        return False
    classroom_ids = list(db.scalars(
        select(ClassroomMembership.classroom_id)
        .join(Classroom, Classroom.id == ClassroomMembership.classroom_id)
        .where(
            ClassroomMembership.student_id == student.id,
            ClassroomMembership.active.is_(True),
            Classroom.active.is_(True),
        )
    ))
    if not classroom_ids:
        return False
    query = select(PedagogicalPackageImportJob.id).where(
        PedagogicalPackageImportJob.classroom_id.in_(classroom_ids),
        PedagogicalPackageImportJob.subject_id == subject_id,
        PedagogicalPackageImportJob.status == "completed",
    )
    if education_level_id is not None:
        query = query.where(PedagogicalPackageImportJob.education_level_id == education_level_id)
    return db.scalars(query).first() is not None


def serialize_current_package(job: PedagogicalPackageImportJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    source_summary = job.source_summary or {}
    target = source_summary.get("target") if isinstance(source_summary, dict) else {}
    works = source_summary.get("works") if isinstance(source_summary, dict) else []
    return {
        "id": job.id,
        "course_id": job.course_id,
        "classroom_id": job.classroom_id,
        "subject_id": job.subject_id,
        "education_level_id": job.education_level_id,
        "academic_year": job.academic_year,
        "title": source_summary.get("course_title") if isinstance(source_summary, dict) else job.course.title if job.course else "",
        "works": works if isinstance(works, list) else [],
        "target": target or {},
        "json_sha256": job.json_sha256,
    }


def balanced_pick(
    questions: list[DiagnosticQuestion],
    limit: int,
) -> list[DiagnosticQuestion]:
    """
    Sélectionne un test équilibré.

    Pour le test standard de 20 questions, la sélection contient :
    - 4 questions pour chacune des 5 compétences ;
    - 7 questions débutant ;
    - 7 questions intermédiaire ;
    - 6 questions avancé.

    Si les métadonnées de compétence ne sont pas disponibles, la fonction
    revient automatiquement à l'ancien équilibrage par difficulté.
    """
    if limit == DEFAULT_LIMIT:
        positioning_questions = balanced_positioning_pick(questions)
        if positioning_questions is not None:
            return positioning_questions

    return balanced_pick_by_difficulty(questions, limit)


def balanced_positioning_pick(
    questions: list[DiagnosticQuestion],
) -> list[DiagnosticQuestion] | None:
    by_competence: dict[str, list[DiagnosticQuestion]] = defaultdict(list)

    for question in questions:
        snapshot = (
            question.source_snapshot
            if isinstance(question.source_snapshot, dict)
            else {}
        )
        competence = str(snapshot.get("competence") or "").strip()

        if competence in POSITIONING_COMPETENCES:
            by_competence[competence].append(question)

    # Ce mode nécessite les cinq compétences du nouveau banco V2.
    if not all(
        competence in by_competence
        for competence in POSITIONING_COMPETENCES
    ):
        return None

    # On change l'association compétence/quota à chaque test tout en gardant
    # exactement 4 questions par compétence et 7/7/6 par difficulté.
    competences = POSITIONING_COMPETENCES.copy()
    quotas = [dict(item) for item in POSITIONING_QUOTAS_20]
    random.shuffle(competences)
    random.shuffle(quotas)

    selected: list[DiagnosticQuestion] = []

    for competence, competence_quotas in zip(competences, quotas):
        by_difficulty: dict[str, list[DiagnosticQuestion]] = defaultdict(list)

        for question in by_competence[competence]:
            difficulty_slug = (
                question.difficulty_level.slug
                if question.difficulty_level
                else "inconnu"
            )
            by_difficulty[difficulty_slug].append(question)

        for rows in by_difficulty.values():
            random.shuffle(rows)

        for difficulty_slug, required_count in competence_quotas.items():
            available = by_difficulty.get(difficulty_slug, [])

            if len(available) < required_count:
                return None

            selected.extend(available[:required_count])

    if len(selected) != DEFAULT_LIMIT:
        return None

    random.shuffle(selected)
    return selected


def balanced_pick_by_difficulty(
    questions: list[DiagnosticQuestion],
    limit: int,
) -> list[DiagnosticQuestion]:
    by_difficulty: dict[str, list[DiagnosticQuestion]] = defaultdict(list)

    for question in questions:
        difficulty_slug = (
            question.difficulty_level.slug
            if question.difficulty_level
            else "inconnu"
        )
        by_difficulty[difficulty_slug].append(question)

    for rows in by_difficulty.values():
        random.shuffle(rows)

    selected: list[DiagnosticQuestion] = []
    targets = target_distribution(limit)

    for slug in ["debutant", "intermediaire", "avance"]:
        for question in by_difficulty.get(slug, [])[:targets.get(slug, 0)]:
            if len(selected) < limit:
                selected.append(question)

    remaining = [
        question
        for question in questions
        if question not in selected
    ]
    random.shuffle(remaining)

    selected.extend(
        remaining[:max(0, limit - len(selected))]
    )

    random.shuffle(selected)
    return selected[:limit]

def target_distribution(limit: int) -> dict[str, int]:
    if limit == DEFAULT_LIMIT:
        return dict(TARGET_DISTRIBUTION)
    base = {slug: max(1, round(limit * count / DEFAULT_LIMIT)) for slug, count in TARGET_DISTRIBUTION.items()}
    while sum(base.values()) > limit:
        slug = max(base, key=base.get)
        base[slug] -= 1
    while sum(base.values()) < limit:
        slug = min(base, key=base.get)
        base[slug] += 1
    return base


def normalize_answers(raw_answers: Any) -> dict[int, Any]:
    if isinstance(raw_answers, dict):
        return {int(key): value for key, value in raw_answers.items()}
    if isinstance(raw_answers, list):
        return {int(item.get("question_id")): item.get("answer") for item in raw_answers if item.get("question_id")}
    return {}


def get_or_create_session(
    db: Session,
    student: UserProfile,
    subject_id: int,
    education_level_id: int | None,
    session_id: int | str | None,
    current_package: PedagogicalPackageImportJob | None = None,
) -> DiagnosticSession:
    if session_id:
        session = db.get(DiagnosticSession, int(session_id))
        if session is None or session.student_id != student.id or session.subject_id != subject_id:
            raise HTTPException(status_code=404, detail="Session de positionnement introuvable")
        if current_package is not None and session.import_job_id not in (None, current_package.id) and not session.completed:
            session.status = "abandoned"
            session.completed = False
            session = DiagnosticSession(
                student_id=student.id,
                subject_id=subject_id,
                education_level_id=int(education_level_id) if education_level_id else None,
                import_job_id=current_package.id,
                imported_package_hash=current_package.json_sha256,
                status="started",
                completed=False,
            )
            db.add(session)
            db.flush()
        return session

    session = DiagnosticSession(
        student_id=student.id,
        subject_id=subject_id,
        education_level_id=int(education_level_id) if education_level_id else None,
        import_job_id=current_package.id if current_package else None,
        imported_package_hash=current_package.json_sha256 if current_package else None,
        status="started",
        completed=False,
    )
    db.add(session)
    db.flush()
    return session


def selected_to_answer(question: DiagnosticQuestion, selected: Any) -> str:
    choices = question.choices or []
    if isinstance(selected, int) or (isinstance(selected, str) and selected.isdigit()):
        index = int(selected)
        if 0 <= index < len(choices):
            return str(choices[index])
    return str(selected or "")


def format_stats(stats: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    rows = []
    for name, values in stats.items():
        total = values["total"]
        correct = values["correct"]
        rows.append({
            "name": name,
            "correct": correct,
            "total": total,
            "percentage": round((correct / total) * 100) if total else 0,
        })
    return sorted(rows, key=lambda item: item["name"])


def detect_level(score: int, results_by_difficulty: list[dict[str, Any]]) -> tuple[str, str]:
    difficulty_scores = {item["name"]: item["percentage"] for item in results_by_difficulty}
    if score < 40:
        return "Débutant", "debutant"
    if score < 70:
        return "Intermédiaire", "intermediaire"
    if difficulty_scores.get("avance", 100) < 50:
        return "Intermédiaire", "intermediaire"
    return "Avancé", "avance"


def build_justification(level: str, results_by_difficulty: list[dict[str, Any]]) -> str:
    advanced = next((item for item in results_by_difficulty if item["name"] == "avance"), None)
    if level == "Débutant":
        return "Niveau débutant détecté : les bases doivent être consolidées avant de passer aux notions plus complexes."
    if level == "Intermédiaire" and advanced and advanced["percentage"] < 50:
        return "Niveau intermédiaire détecté : les notions fondamentales sont acquises, mais les questions avancées nécessitent encore du travail."
    if level == "Intermédiaire":
        return "Niveau intermédiaire détecté : vous maîtrisez une partie des bases et pouvez progresser avec des exercices guidés."
    return "Niveau avancé détecté : vous réussissez les bases et une partie significative des questions difficiles."


def split_strengths_and_gaps(results_by_topic: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    strengths = [item["name"] for item in results_by_topic if item["percentage"] >= 70]
    gaps = [item["name"] for item in results_by_topic if item["percentage"] < 70]
    return strengths, gaps


def build_recommendations(
    db: Session,
    subject_id: int,
    education_level_id: int | None,
    difficulty_slug: str,
    results_by_topic: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    difficulty_order = {"debutant": 1, "intermediaire": 2, "avance": 3}
    max_order = difficulty_order.get(difficulty_slug, 1)
    query = (
        select(Course)
        .options(selectinload(Course.difficulty_level))
        .where(Course.subject_id == subject_id, Course.published.is_(True))
        .order_by(Course.display_order, Course.id)
    )
    if education_level_id:
        query = query.where((Course.education_level_id == education_level_id) | (Course.education_level_id.is_(None)))
    courses = []
    for course in db.scalars(query).unique():
        course_order = difficulty_order.get(course.difficulty_level.slug if course.difficulty_level else "", max_order)
        if course_order <= max_order or not courses:
            courses.append(course)

    weakest = sorted(results_by_topic, key=lambda item: item["percentage"])[0]["name"] if results_by_topic else "les bases"
    return [
        {
            "course_id": course.id,
            "title": course.title,
            "level": course.level,
            "reason": f"Recommandé car vous devez renforcer {weakest}.",
            "path": f"/courses/{course.id}",
        }
        for course in courses[:3]
    ]


def serialize_public_question(question: DiagnosticQuestion) -> dict[str, Any]:
    return {
        "id": question.id,
        "subject_id": question.subject_id,
        "education_level_id": question.education_level_id,
        "difficulty_level_id": question.difficulty_level_id,
        "difficulty": question.difficulty_level.name if question.difficulty_level else "",
        "topic": question.topic,
        "theme": question.topic,
        "question": question.question,
        "options": question.choices,
        "choices": question.choices,
    }


def serialize_subject(subject: Subject) -> dict[str, Any]:
    return {"id": subject.id, "name": subject.name, "slug": subject.slug}


def serialize_result(
    result: DiagnosticResult,
    subject: Subject,
    recommendations: list[dict[str, Any]],
    strengths: list[str],
    gaps: list[str],
) -> dict[str, Any]:
    payload = serialize_saved_result(result)
    payload.update({
        "subject": serialize_subject(subject),
        "recommendations": recommendations,
        "strengths": strengths,
        "gaps": gaps,
    })
    return payload


def serialize_saved_result(result: DiagnosticResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "user_id": result.user_id,
        "subject_id": result.subject_id,
        "subject": serialize_subject(result.subject) if result.subject else None,
        "education_level_id": result.education_level_id,
        "detected_difficulty_level_id": result.detected_difficulty_level_id,
        "score": result.score,
        "percentage": result.score,
        "level": result.level,
        "total": result.total,
        "correct_count": result.correct_count,
        "corrections": result.corrections,
        "results_by_topic": result.results_by_topic or [],
        "results_by_difficulty": result.results_by_difficulty or [],
        "recommendations": result.recommendations or [],
        "justification": result.justification or "",
        "date": result.created_at.isoformat() if result.created_at else None,
        "created_at": result.created_at,
    }


def serialize_admin_question(question: DiagnosticQuestion) -> dict[str, Any]:
    return {
        "id": question.id,
        "subject_id": question.subject_id,
        "subject": serialize_subject(question.subject) if question.subject else None,
        "education_level_id": question.education_level_id,
        "education_level": {
            "id": question.education_level.id,
            "name": question.education_level.name,
        } if question.education_level else None,
        "difficulty_level_id": question.difficulty_level_id,
        "difficulty_level": {
            "id": question.difficulty_level.id,
            "name": question.difficulty_level.name,
            "slug": question.difficulty_level.slug,
        } if question.difficulty_level else None,
        "topic": question.topic,
        "question": question.question,
        "choices": question.choices,
        "correct_answer": question.correct_answer,
        "explanation": question.explanation,
        "active": question.active,
        "source_course_id": question.source_course_id,
        "source_course": {
            "id": question.source_course.id,
            "title": question.source_course.title,
        } if question.source_course else None,
        "source_chapter_id": question.source_chapter_id,
        "source_block_id": question.source_block_id,
        "generation_method": question.generation_method,
        "source_hash": question.source_hash,
        "question_hash": question.question_hash,
        "imported_package_hash": question.imported_package_hash,
        "source_snapshot": question.source_snapshot,
        "created_at": question.created_at,
        "updated_at": question.updated_at,
    }