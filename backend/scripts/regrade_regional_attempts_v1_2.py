from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload, sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import regional_auto_grader_service as grader


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


def parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_regional(assessment: Any) -> bool:
    for raw in (getattr(assessment, "description", None), getattr(assessment, "instructions", None)):
        data = parse_json(raw)
        metadata = data.get("regional_exam") if isinstance(data.get("regional_exam"), dict) else data
        if metadata.get("is_regional_exam") is True or metadata.get("exam_kind") == "regional":
            return True
    text = " ".join([str(getattr(assessment, "title", "") or ""), str(getattr(assessment, "description", "") or "")]).lower()
    return "regional" in text or "régional" in text


def patch_question_metadata(question: Any) -> bool:
    data = parse_json(getattr(question, "adaptation_reason", None))
    qtype = str(data.get("question_type") or "")
    if qtype not in {"response_long", "production_ecrite"}:
        return False
    changed = data.get("requires_teacher_validation") is not False or data.get("scoring_mode") != "automatic_hybrid"
    data["requires_teacher_validation"] = False
    data["scoring_mode"] = "automatic_hybrid"
    if changed:
        question.adaptation_reason = json.dumps(data, ensure_ascii=False)
    return changed


def patch_dataset() -> int:
    path = BACKEND / "data" / "regional_exams_v1" / "regional_assessment_payloads_v1.json"
    if not path.exists():
        return 0
    payloads = json.loads(path.read_text(encoding="utf-8-sig"))
    changed = 0
    for exam in payloads:
        for question in exam.get("questions", []):
            data = parse_json(question.get("adaptation_reason"))
            if data.get("question_type") not in {"response_long", "production_ecrite"}:
                continue
            if data.get("requires_teacher_validation") is not False or data.get("scoring_mode") != "automatic_hybrid":
                data["requires_teacher_validation"] = False
                data["scoring_mode"] = "automatic_hybrid"
                question["adaptation_reason"] = json.dumps(data, ensure_ascii=False)
                changed += 1
    if changed:
        path.write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-id", type=int)
    parser.add_argument("--all-students", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    persistence = importlib.import_module("app.models.persistence")
    AssessmentAttempt = persistence.AssessmentAttempt
    Assessment = persistence.Assessment
    AssessmentAnswer = persistence.AssessmentAnswer
    AssessmentQuestion = persistence.AssessmentQuestion

    factory = get_session_factory()
    db = factory()
    attempts_updated = 0
    answers_updated = 0
    metadata_updated = 0
    try:
        query = (
            select(AssessmentAttempt)
            .where(AssessmentAttempt.completed.is_(True))
            .options(
                selectinload(AssessmentAttempt.assessment).selectinload(Assessment.questions),
                selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question),
            )
            .order_by(AssessmentAttempt.id)
        )
        if args.student_id is not None:
            query = query.where(AssessmentAttempt.student_id == args.student_id)
        attempts = list(db.scalars(query))
        attempts = [attempt for attempt in attempts if attempt.assessment and is_regional(attempt.assessment)]

        for attempt in attempts:
            questions = sorted(
                [q for q in attempt.assessment.questions if getattr(q, "active", True)],
                key=lambda q: (getattr(q, "order_index", 0), getattr(q, "id", 0)),
            )
            answer_by_question = {answer.question_id: answer for answer in attempt.answers}
            answer_payload = {str(q.id): str(getattr(answer_by_question.get(q.id), "selected_answer", "") or "") for q in questions}
            evaluations = grader.grade_exam_answers(questions, answer_payload)
            total = 0.0
            awarded = 0.0
            stored: dict[str, dict[str, Any]] = {}
            for question in questions:
                metadata_updated += int(patch_question_metadata(question))
                answer = answer_by_question.get(question.id)
                evaluation = evaluations.get(question.id)
                points = float(getattr(question, "points", 1) or 1)
                total += points
                if answer is None or evaluation is None:
                    continue
                answer.points_awarded = evaluation["points_awarded"]
                answer.correct = evaluation["correct"]
                awarded += float(evaluation["points_awarded"])
                stored[str(question.id)] = evaluation
                answers_updated += 1
            attempt.score = round(awarded, 2)
            attempt.percentage = round((awarded / total) * 100, 2) if total else 0
            attempts_updated += 1
            if not args.dry_run:
                db.flush()
                grader.save_attempt_feedback(attempt.id, stored)

        if args.dry_run:
            db.rollback()
        else:
            db.commit()
            dataset_updated = patch_dataset()
        print(json.dumps({
            "grader_version": grader.AUTO_GRADER_VERSION,
            "provider": grader.DEFAULT_PROVIDER,
            "model": grader.OLLAMA_MODEL if grader.DEFAULT_PROVIDER == "ollama" else None,
            "attempts_updated": attempts_updated,
            "answers_updated": answers_updated,
            "database_metadata_updated": metadata_updated,
            "dataset_metadata_updated": 0 if args.dry_run else dataset_updated,
            "dry_run": args.dry_run,
        }, ensure_ascii=False, indent=2))
        print("DRY-RUN V1.2 REUSSI" if args.dry_run else "RE-CORRECTION AUTOMATIQUE V1.2 REUSSIE")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
