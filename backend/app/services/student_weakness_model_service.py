from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import (
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    QuizResult,
    UserProfile,
)

MODEL_VERSION = "student-weakness-v1-20260802"
DATASET_VERSION = "synthetic-controlled-v1-20260802"
COLLECTOR_VERSION = "weakness-event-collector-v1.2-20260802"
MODEL_PATH = Path(__file__).resolve().parents[1] / "nlp_runtime" / "models" / "student_weakness_predictor_v1.joblib"
FEATURE_NAMES = [
    "average_score",
    "correct_rate",
    "average_time_norm",
    "attempts_norm",
    "difficulty_mean",
    "trend",
    "retry_rate",
    "coverage",
]
CANONICAL_COMPETENCIES = [
    "Compréhension",
    "Langue",
    "Figures de style",
    "Production écrite",
    "Méthodologie",
]
MIN_EVENTS_FOR_PREDICTION = 2


@lru_cache(maxsize=1)
def load_model_artifact() -> dict | None:
    if not MODEL_PATH.exists():
        return None
    try:
        artifact = joblib.load(MODEL_PATH)
    except Exception:
        return None
    return artifact if isinstance(artifact, dict) else None


def get_model_debug() -> dict:
    artifact = load_model_artifact()
    return {
        "loaded": artifact is not None,
        "version": (artifact or {}).get("version", MODEL_VERSION),
        "dataset_version": (artifact or {}).get("dataset_version", DATASET_VERSION),
        "dataset_type": "synthetic_controlled",
        "collector_version": COLLECTOR_VERSION,
        "model_path": str(MODEL_PATH),
        "feature_names": (artifact or {}).get("feature_names", FEATURE_NAMES),
        "labels": (artifact or {}).get("labels", ["faible", "a_renforcer", "maitrise"]),
        "metrics": (artifact or {}).get("metrics", {}),
        "validation_status": "prototype_non_valide_sur_eleves_reels",
    }


def predict_student_weaknesses(db: Session, student: UserProfile) -> dict:
    events, collection_diagnostics = collect_student_learning_events(db, student.id, with_diagnostics=True)
    aggregates = aggregate_by_competence(events)
    predictions = []

    for competence in CANONICAL_COMPETENCIES:
        features = aggregates.get(competence)
        if not features:
            predictions.append(non_evaluated_row(competence))
            continue
        predictions.append(predict_competence(competence, features))

    evaluated = [row for row in predictions if row["status"] != "non_evalue"]
    ranked = sorted(
        evaluated,
        key=lambda row: (
            -status_priority(row["status"]),
            -float(row.get("risk_score") or 0),
        ),
    )
    weak_rows = [row for row in ranked if row["status"] in {"faible", "a_renforcer"}]
    weak_points = [
        {
            "assessment_id": f"model-{slugify(row['competence'])}",
            "score": row["score_percentage"],
            "message": row["recommendation"],
            "competence": row["competence"],
            "status": row["status"],
            "confidence": row["confidence"],
            "source": "student_weakness_predictor_v1",
        }
        for row in weak_rows[:5]
    ]

    overall = build_overall_summary(predictions, len(events))
    return {
        "model": get_model_debug(),
        "dataset_disclaimer": (
            "Prototype entraîné sur un dataset synthétique contrôlé ; "
            "validation sur des réponses réelles nécessaire."
        ),
        "events_used": len(events),
        "collection_diagnostics": collection_diagnostics,
        "competencies": predictions,
        "weak_points": weak_points,
        "priority_recommendations": [row["recommendation"] for row in weak_rows[:3]],
        "overall": overall,
    }


def collect_student_learning_events(
    db: Session,
    student_id: int,
    with_diagnostics: bool = False,
) -> list[dict] | tuple[list[dict], dict]:
    """Collect real learning events without forcing unknown data into Compréhension.

    V1.2 changes:
    - reads every answer/correction stored in a QuizResult, not only index 0;
    - uses explicit competence fields first, then question context;
    - ignores truly unclassified items instead of labelling them Compréhension;
    - recognizes more methodology wording (respecter la consigne, gérer le temps);
    - exposes non-sensitive collection diagnostics for debugging.
    """
    events: list[dict] = []
    diagnostics = {
        "collector_version": COLLECTOR_VERSION,
        "quiz_result_rows": 0,
        "regional_attempts": 0,
        "items_seen": 0,
        "ignored_unclassified": 0,
        "events_by_source": {},
        "events_by_competence": {},
    }

    quiz_rows = list(db.scalars(
        select(QuizResult)
        .where(QuizResult.user_id == student_id)
        .order_by(QuizResult.created_at.asc(), QuizResult.id.asc())
    ))
    diagnostics["quiz_result_rows"] = len(quiz_rows)

    for row in quiz_rows:
        answers = record_list(row.answers)
        corrections = record_list(row.corrections)
        item_count = max(len(answers), len(corrections), 1)
        for index in range(item_count):
            diagnostics["items_seen"] += 1
            answer = answers[index] if index < len(answers) else {}
            correction = corrections[index] if index < len(corrections) else {}

            competence = infer_competence(correction, answer)
            if competence is None:
                competence = infer_competence_from_values(
                    getattr(row, "competence", None),
                    getattr(row, "skill", None),
                    getattr(row, "category", None),
                    getattr(row, "question_type", None),
                    getattr(row, "title", None),
                )
            if competence is None:
                diagnostics["ignored_unclassified"] += 1
                continue

            max_points = positive_float(
                correction.get("max_points"),
                correction.get("question_points"),
                correction.get("points"),
                answer.get("max_points"),
                default=1.0,
            )
            explicit_points = first_present(
                correction.get("points_awarded"),
                correction.get("awarded_points"),
                answer.get("points_awarded"),
            )
            if explicit_points is None:
                points = percentage_to_ratio(getattr(row, "score", 0)) * max_points
            else:
                points = safe_float(explicit_points, 0.0)

            correct_value = first_present(
                correction.get("is_correct"),
                correction.get("correct"),
                answer.get("is_correct"),
                answer.get("correct"),
            )
            if correct_value is None:
                correct_value = bool(getattr(row, "correct", 0) > 0)

            event = {
                "competence": competence,
                "score_ratio": clamp(points / max_points if max_points else 0),
                "correct": bool(correct_value),
                "time_seconds": optional_float(first_present(
                    correction.get("time_spent_seconds"),
                    correction.get("response_time_seconds"),
                    answer.get("time_spent_seconds"),
                    answer.get("response_time_seconds"),
                )),
                "difficulty": difficulty_value(first_present(
                    answer.get("level"),
                    answer.get("difficulty"),
                    correction.get("level"),
                    correction.get("difficulty"),
                )),
                "attempt_number": max(1, int(safe_float(first_present(
                    correction.get("attempt_number"),
                    answer.get("attempt_number"),
                ), 1))),
                "timestamp": row.created_at,
                "source": "chapter_exercise",
            }
            events.append(event)

    attempts = list(db.scalars(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.student_id == student_id,
            AssessmentAttempt.completed.is_(True),
        )
        .options(
            selectinload(AssessmentAttempt.answers)
            .selectinload(AssessmentAnswer.question)
            .selectinload(AssessmentQuestion.skill)
        )
        .order_by(AssessmentAttempt.submitted_at.asc(), AssessmentAttempt.id.asc())
    ))
    diagnostics["regional_attempts"] = len(attempts)

    for attempt in attempts:
        for answer in attempt.answers:
            diagnostics["items_seen"] += 1
            question = answer.question
            if question is None:
                diagnostics["ignored_unclassified"] += 1
                continue
            metadata = parse_json_object(question.adaptation_reason)
            competence = infer_competence(
                metadata,
                {
                    "competence": question.skill.name if question.skill else None,
                    "question": getattr(question, "question", None),
                    "explanation": getattr(question, "explanation", None),
                    "question_type": metadata.get("question_type"),
                    "section": metadata.get("section"),
                },
            )
            if competence is None:
                diagnostics["ignored_unclassified"] += 1
                continue
            max_points = positive_float(question.points, default=1.0)
            events.append({
                "competence": competence,
                "score_ratio": clamp(safe_float(answer.points_awarded, 0.0) / max_points if max_points else 0),
                "correct": bool(answer.correct),
                "time_seconds": optional_float(answer.time_spent_seconds or answer.response_time_seconds),
                "difficulty": difficulty_value(metadata.get("difficulty") or metadata.get("level")),
                "attempt_number": max(1, int(attempt.attempt_number or 1)),
                "timestamp": attempt.submitted_at or attempt.started_at,
                "source": "regional_exam",
            })

    source_counts: dict[str, int] = defaultdict(int)
    competence_counts: dict[str, int] = defaultdict(int)
    for event in events:
        source_counts[str(event.get("source") or "unknown")] += 1
        competence_counts[str(event.get("competence") or "unknown")] += 1
    diagnostics["events_by_source"] = dict(sorted(source_counts.items()))
    diagnostics["events_by_competence"] = {
        competence: int(competence_counts.get(competence, 0))
        for competence in CANONICAL_COMPETENCIES
    }
    diagnostics["events_collected"] = len(events)

    if with_diagnostics:
        return events, diagnostics
    return events


def aggregate_by_competence(events: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["competence"]].append(event)

    aggregates = {}
    for competence, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: row.get("timestamp") or datetime.min)
        scores = [float(row["score_ratio"]) for row in ordered]
        corrects = [1.0 if row.get("correct") else 0.0 for row in ordered]
        known_times = [float(row["time_seconds"]) for row in ordered if row.get("time_seconds") not in (None, 0)]
        difficulties = [float(row.get("difficulty") or 0.5) for row in ordered]
        attempts = [int(row.get("attempt_number") or 1) for row in ordered]
        split = max(1, len(scores) // 2)
        first_mean = mean(scores[:split])
        second_mean = mean(scores[split:]) if scores[split:] else first_mean
        trend = clamp(second_mean - first_mean, -1, 1)
        aggregates[competence] = {
            "average_score": mean(scores),
            "correct_rate": mean(corrects),
            "average_time_norm": clamp(mean(known_times) / 180.0) if known_times else 0.35,
            "attempts_norm": min(len(rows) / 20.0, 1.0),
            "difficulty_mean": mean(difficulties) if difficulties else 0.5,
            "trend": trend,
            "retry_rate": mean([1.0 if value > 1 else 0.0 for value in attempts]),
            "coverage": min(len(rows) / 10.0, 1.0),
            "events_count": len(rows),
            "sources": sorted({str(row.get("source") or "") for row in rows}),
        }
    return aggregates


def predict_competence(competence: str, features: dict) -> dict:
    if int(features.get("events_count") or 0) < MIN_EVENTS_FOR_PREDICTION:
        return {
            "competence": competence,
            "status": "donnees_insuffisantes",
            "label": "Données insuffisantes",
            "confidence": 0.0,
            "risk_score": 0.0,
            "score_percentage": round(float(features.get("average_score") or 0) * 100, 2),
            "events_count": int(features.get("events_count") or 0),
            "trend_percentage": round(float(features.get("trend") or 0) * 100, 2),
            "recommendation": f"Répondre à davantage de questions en {competence.lower()}.",
            "method": "insufficient_data",
            "features": public_features(features),
        }

    artifact = load_model_artifact()
    vector = np.array([[float(features.get(name) or 0) for name in FEATURE_NAMES]], dtype=float)
    if artifact and artifact.get("model") is not None:
        model = artifact["model"]
        label = str(model.predict(vector)[0])
        probabilities = model.predict_proba(vector)[0]
        classes = list(model.classes_)
        probability_map = {str(name): float(probabilities[index]) for index, name in enumerate(classes)}
        confidence = max(probability_map.values()) if probability_map else 0.0
        method = "logistic_regression"
    else:
        label = rule_fallback_label(features)
        probability_map = {label: 1.0}
        confidence = 0.45
        method = "rules_fallback"

    risk_score = float(probability_map.get("faible", 0)) + 0.5 * float(probability_map.get("a_renforcer", 0))
    return {
        "competence": competence,
        "status": label,
        "label": status_label(label),
        "confidence": round(confidence, 4),
        "risk_score": round(risk_score, 4),
        "probabilities": {key: round(value, 4) for key, value in probability_map.items()},
        "score_percentage": round(float(features.get("average_score") or 0) * 100, 2),
        "correct_rate_percentage": round(float(features.get("correct_rate") or 0) * 100, 2),
        "trend_percentage": round(float(features.get("trend") or 0) * 100, 2),
        "events_count": int(features.get("events_count") or 0),
        "recommendation": recommendation_for(competence, label),
        "method": method,
        "features": public_features(features),
    }


def build_overall_summary(predictions: list[dict], events_count: int) -> dict:
    evaluated = [row for row in predictions if row["status"] in {"faible", "a_renforcer", "maitrise"}]
    if not evaluated:
        return {
            "status": "donnees_insuffisantes",
            "label": "Données insuffisantes",
            "events_count": events_count,
            "priority_competence": None,
        }
    priority = sorted(evaluated, key=lambda row: (-status_priority(row["status"]), -float(row.get("risk_score") or 0)))[0]
    return {
        "status": "analyse_disponible",
        "label": "Analyse personnalisée disponible",
        "events_count": events_count,
        "priority_competence": priority["competence"] if priority["status"] != "maitrise" else None,
        "priority_status": priority["status"],
        "mastered_count": sum(1 for row in evaluated if row["status"] == "maitrise"),
        "reinforce_count": sum(1 for row in evaluated if row["status"] == "a_renforcer"),
        "weak_count": sum(1 for row in evaluated if row["status"] == "faible"),
    }


def non_evaluated_row(competence: str) -> dict:
    return {
        "competence": competence,
        "status": "non_evalue",
        "label": "Non évalué",
        "confidence": 0.0,
        "risk_score": 0.0,
        "score_percentage": None,
        "events_count": 0,
        "trend_percentage": 0.0,
        "recommendation": f"Effectuer des exercices de {competence.lower()} pour lancer l'analyse.",
        "method": "no_data",
    }


def public_features(features: dict) -> dict:
    return {
        "average_score": round(float(features.get("average_score") or 0), 4),
        "correct_rate": round(float(features.get("correct_rate") or 0), 4),
        "average_time_norm": round(float(features.get("average_time_norm") or 0), 4),
        "attempts_norm": round(float(features.get("attempts_norm") or 0), 4),
        "difficulty_mean": round(float(features.get("difficulty_mean") or 0), 4),
        "trend": round(float(features.get("trend") or 0), 4),
        "retry_rate": round(float(features.get("retry_rate") or 0), 4),
        "coverage": round(float(features.get("coverage") or 0), 4),
        "sources": features.get("sources", []),
    }


def recommendation_for(competence: str, label: str) -> str:
    actions = {
        "Compréhension": "Relire le texte, repérer les personnages, les événements et les idées principales, puis refaire 5 questions ciblées.",
        "Langue": "Réviser la règle concernée et refaire des exercices gradués de grammaire, vocabulaire et conjugaison.",
        "Figures de style": "Réviser comparaison, métaphore, personnification et antithèse, puis identifier la figure et son effet.",
        "Production écrite": "Travailler le plan, les arguments, les connecteurs et une rédaction courte avec correction détaillée.",
        "Méthodologie": "S'entraîner à lire la consigne, répartir le temps et construire une réponse selon le barème.",
    }
    base = actions.get(competence, f"Refaire des exercices ciblés de {competence.lower()}.")
    if label == "faible":
        return f"Priorité élevée : {base}"
    if label == "a_renforcer":
        return f"À renforcer : {base}"
    return f"Compétence maîtrisée : maintenir le niveau avec un exercice avancé de {competence.lower()}."


EXPLICIT_COMPETENCE_KEYS = (
    "competence",
    "competency",
    "skill",
    "skill_name",
    "category",
    "domain",
    "learning_objective",
)
CONTEXT_KEYS = (
    "question_type",
    "type",
    "section",
    "title",
    "question",
    "prompt",
    "instruction",
    "consigne",
    "explanation",
    "tags",
)


def infer_competence(*records: dict) -> str | None:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in EXPLICIT_COMPETENCE_KEYS:
            competence = canonical_competence(record.get(key))
            if competence is not None:
                return competence
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in CONTEXT_KEYS:
            competence = canonical_competence(record.get(key))
            if competence is not None:
                return competence
    return None


def infer_competence_from_values(*values: Any) -> str | None:
    for value in values:
        competence = canonical_competence(value)
        if competence is not None:
            return competence
    return None


def canonical_competence(value: Any) -> str | None:
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item) for item in value)
    text = normalize_text(str(value or ""))
    if not text:
        return None

    if any(token in text for token in (
        "figure de style", "figure stylistique", "metaphore", "comparaison",
        "personnification", "antithese", "hyperbole", "anaphore", "oxymore",
        "litote", "euphemisme", "gradation", "enumeration", "ironie",
    )):
        return "Figures de style"
    if any(token in text for token in (
        "production ecrite", "expression ecrite", "redaction", "rediger",
        "argumentation", "texte argumentatif", "sujet de production",
        "ecrire une", "ecrire un", "lettre ouverte",
    )):
        return "Production écrite"
    if any(token in text for token in (
        "methodologie", "methode", "gestion du temps", "gestion temps",
        "gerer le temps", "organisation du temps", "repartir le temps",
        "temps imparti", "lire la consigne", "respect de la consigne",
        "respecter la consigne", "respecter les consignes", "suivre la consigne",
        "repondre selon la consigne", "bareme", "brouillon",
        "organiser la reponse", "plan de reponse",
    )):
        return "Méthodologie"
    if any(token in text for token in (
        "langue", "grammaire", "vocabulaire", "conjugaison", "syntaxe",
        "orthographe", "lexique", "champ lexical", "temps verbal",
        "discours direct", "discours indirect", "nature grammaticale",
        "fonction grammaticale", "pronom", "adjectif", "verbe",
    )):
        return "Langue"
    if any(token in text for token in (
        "comprehension", "comprendre le texte", "lecture", "personnage",
        "evenement", "idee principale", "narrateur", "theme", "contexte",
        "oeuvre", "auteur", "extrait", "situation du passage",
    )):
        return "Compréhension"
    return None


def record_list(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nested = [item for item in value.values() if isinstance(item, dict)]
        return nested if nested else [value]
    return []


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def optional_float(value: Any) -> float | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def positive_float(*values: Any, default: float = 1.0) -> float:
    for value in values:
        number = safe_float(value, 0.0)
        if number > 0:
            return number
    return float(default)


def percentage_to_ratio(value: Any) -> float:
    number = safe_float(value, 0.0)
    if number > 1:
        number /= 100.0
    return clamp(number)


def difficulty_value(value: Any) -> float:
    text = normalize_text(str(value or ""))
    if "avance" in text or "difficile" in text:
        return 0.85
    if "intermediaire" in text or "moyen" in text:
        return 0.55
    if "debutant" in text or "facile" in text:
        return 0.25
    return 0.50


def parse_json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip().startswith("{"):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def rule_fallback_label(features: dict) -> str:
    score = 0.55 * float(features.get("average_score") or 0) + 0.30 * float(features.get("correct_rate") or 0) + 0.15 * max(0, float(features.get("trend") or 0))
    if score < 0.45:
        return "faible"
    if score < 0.72:
        return "a_renforcer"
    return "maitrise"


def status_priority(status: str) -> int:
    return {"faible": 3, "a_renforcer": 2, "maitrise": 1}.get(status, 0)


def status_label(status: str) -> str:
    return {
        "faible": "Faible",
        "a_renforcer": "À renforcer",
        "maitrise": "Maîtrisé",
    }.get(status, status)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def normalize_text(value: str) -> str:
    clean = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    ).lower()
    return re.sub(r"\s+", " ", clean).strip()


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_text(value)).strip("-")
