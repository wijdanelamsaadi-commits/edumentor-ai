from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.core.database import get_db
from app.models.persistence import DiagnosticResult


SUBJECT_ID = 1534
EXPECTED_TOTAL = 20

TOPIC_FEATURES = {
    "Compréhension": "score_comprehension",
    "Langue et grammaire": "score_langue_grammaire",
    "Connaissance des œuvres": "score_connaissance_oeuvres",
    "Figures de style et procédés": "score_figures_procedes",
    "Interprétation et justification": "score_interpretation_justification",
}

DIFFICULTY_FEATURES = {
    "debutant": "score_debutant",
    "intermediaire": "score_intermediaire",
    "avance": "score_avance",
}


def normalize_rows(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def build_positioning_features(result: DiagnosticResult) -> dict[str, Any]:
    topic_rows = normalize_rows(result.results_by_topic)
    difficulty_rows = normalize_rows(result.results_by_difficulty)

    topic_scores = {
        str(item.get("name") or "").strip(): int(item.get("percentage") or 0)
        for item in topic_rows
        if isinstance(item, dict)
    }

    difficulty_scores = {
        str(item.get("name") or "").strip().lower(): int(
            item.get("percentage") or 0
        )
        for item in difficulty_rows
        if isinstance(item, dict)
    }

    total = int(result.total or 0)
    correct_count = int(result.correct_count or 0)
    score = int(result.score or 0)

    features: dict[str, Any] = {
        "features_version": "positioning_features_v1",
        "score_global": score,
        "questions_repondues": total,
        "bonnes_reponses": correct_count,
        "taux_reponse": round((total / EXPECTED_TOTAL) * 100)
        if EXPECTED_TOTAL
        else 0,
    }

    for label, feature_name in TOPIC_FEATURES.items():
        features[feature_name] = topic_scores.get(label, 0)

    for slug, feature_name in DIFFICULTY_FEATURES.items():
        features[feature_name] = difficulty_scores.get(slug, 0)

    return features


def main() -> None:
    db = next(get_db())

    try:
        result = db.scalars(
            select(DiagnosticResult)
            .where(DiagnosticResult.subject_id == SUBJECT_ID)
            .order_by(DiagnosticResult.created_at.desc())
        ).first()

        if result is None:
            print("Aucun résultat de positionnement trouvé pour le Français.")
            return

        output = {
            "diagnostic_result_id": result.id,
            "student_id": result.user_id,
            "level_actuel": result.level,
            "score": result.score,
            "results_by_topic": result.results_by_topic or [],
            "results_by_difficulty": result.results_by_difficulty or [],
            "positioning_features": build_positioning_features(result),
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))

    finally:
        db.close()


if __name__ == "__main__":
    main()
