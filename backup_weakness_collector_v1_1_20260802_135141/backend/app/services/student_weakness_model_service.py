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
        "model_path": str(MODEL_PATH),
        "feature_names": (artifact or {}).get("feature_names", FEATURE_NAMES),
        "labels": (artifact or {}).get("labels", ["faible", "a_renforcer", "maitrise"]),
        "metrics": (artifact or {}).get("metrics", {}),
        "validation_status": "prototype_non_valide_sur_eleves_reels",
    }


def predict_student_weaknesses(db: Session, student: UserProfile) -> dict:
    events = collect_student_learning_events(db, student.id)
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
        "competencies": predictions,
        "weak_points": weak_points,
        "priority_recommendations": [row["recommendation"] for row in weak_rows[:3]],
        "overall": overall,
    }


def collect_student_learning_events(db: Session, student_id: int) -> list[dict]:
    events: list[dict] = []

    quiz_rows = list(db.scalars(
        select(QuizResult)
        .where(QuizResult.user_id == student_id)
        .order_by(QuizResult.created_at.asc(), QuizResult.id.asc())
    ))
    for row in quiz_rows:
        answers = row.answers if isinstance(row.answers, list) else []
        corrections = row.corrections if isinstance(row.corrections, list) else []
        answer = answers[0] if answers and isinstance(answers[0], dict) else {}
        correction = corrections[0] if corrections and isinstance(corrections[0], dict) else {}
        competence = canonical_competence(
            correction.get("competence") or answer.get("competence") or ""
        )
        if competence is None:
            continue
        max_points = float(correction.get("max_points") or 1)
        points = float(correction.get("points_awarded") or (row.score or 0) / 100 * max_points)
        events.append({
            "competence": competence,
            "score_ratio": clamp(points / max_points if max_points else 0),
            "correct": bool(correction.get("is_correct", row.correct > 0)),
            "time_seconds": None,
            "difficulty": difficulty_value(answer.get("level") or correction.get("level")),
            "attempt_number": int(correction.get("attempt_number") or answer.get("attempt_number") or 1),
            "timestamp": row.created_at,
            "source": "chapter_exercise",
        })

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
    for attempt in attempts:
        for answer in attempt.answers:
            question = answer.question
            if question is None:
                continue
            metadata = parse_json_object(question.adaptation_reason)
            competence = canonical_competence(
                metadata.get("competence") or (question.skill.name if question.skill else "")
            )
            if competence is None:
                continue
            max_points = float(question.points or 1)
            events.append({
                "competence": competence,
                "score_ratio": clamp(float(answer.points_awarded or 0) / max_points if max_points else 0),
                "correct": bool(answer.correct),
                "time_seconds": answer.time_spent_seconds or answer.response_time_seconds or None,
                "difficulty": difficulty_value(metadata.get("difficulty") or metadata.get("level")),
                "attempt_number": int(attempt.attempt_number or 1),
                "timestamp": attempt.submitted_at or attempt.started_at,
                "source": "regional_exam",
            })

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


def canonical_competence(value: Any) -> str | None:
    text = normalize_text(str(value or ""))
    if not text:
        return None
    if any(token in text for token in ("figure", "style", "metaphore", "comparaison", "personnification", "antithese")):
        return "Figures de style"
    if any(token in text for token in ("production", "ecriture", "redaction", "argument", "expression ecrite")):
        return "Production écrite"
    if any(token in text for token in ("method", "plan", "organisation", "consigne", "gestion du temps")):
        return "Méthodologie"
    if any(token in text for token in ("langue", "grammaire", "vocabulaire", "conjugaison", "syntaxe", "orthographe")):
        return "Langue"
    if any(token in text for token in ("comprehension", "theme", "personnage", "analyse", "oeuvre", "lecture")):
        return "Compréhension"
    return "Compréhension"


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
