from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sqlalchemy import select

from app.core.database import get_db
from app.models.persistence import DiagnosticResult


SUBJECT_ID = 1534

BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = (
    BASE_DIR
    / "positioning_model_artifacts"
    / "model"
    / "positioning_level_model_v1.joblib"
)

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

LEVEL_LABELS = {
    "debutant": "Débutant",
    "intermediaire": "Intermédiaire",
    "avance": "Avancé",
}


def normalize_rows(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def build_features(result: DiagnosticResult) -> dict[str, int]:
    topic_rows = normalize_rows(result.results_by_topic)
    difficulty_rows = normalize_rows(result.results_by_difficulty)

    topic_scores = {
        str(item.get("name") or "").strip(): int(
            item.get("percentage") or 0
        )
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

    features = {
        "score_global": int(result.score or 0),
        "score_comprehension": 0,
        "score_langue_grammaire": 0,
        "score_connaissance_oeuvres": 0,
        "score_figures_procedes": 0,
        "score_interpretation_justification": 0,
        "score_debutant": 0,
        "score_intermediaire": 0,
        "score_avance": 0,
    }

    for topic_label, feature_name in TOPIC_FEATURES.items():
        features[feature_name] = topic_scores.get(topic_label, 0)

    for difficulty_slug, feature_name in DIFFICULTY_FEATURES.items():
        features[feature_name] = difficulty_scores.get(
            difficulty_slug,
            0,
        )

    return features


def main() -> None:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Modèle introuvable : {MODEL_PATH}"
        )

    bundle = joblib.load(MODEL_PATH)

    model = bundle["model"]
    feature_columns = list(bundle["feature_columns"])
    model_name = str(bundle.get("model_name") or "inconnu")
    model_version = str(
        bundle.get("model_version")
        or "positioning_level_model_v1"
    )

    db = next(get_db())

    try:
        result = db.scalars(
            select(DiagnosticResult)
            .where(DiagnosticResult.subject_id == SUBJECT_ID)
            .order_by(DiagnosticResult.created_at.desc())
        ).first()

        if result is None:
            print(
                "Aucun résultat de positionnement trouvé "
                "pour le Français."
            )
            return

        features = build_features(result)

        input_frame = pd.DataFrame(
            [[features[column] for column in feature_columns]],
            columns=feature_columns,
        )

        predicted_slug = str(model.predict(input_frame)[0])
        predicted_label = LEVEL_LABELS.get(
            predicted_slug,
            predicted_slug,
        )

        probabilities: dict[str, float] = {}
        confidence = None

        if hasattr(model, "predict_proba"):
            raw_probabilities = model.predict_proba(input_frame)[0]
            classes = list(model.classes_)

            probabilities = {
                LEVEL_LABELS.get(
                    str(class_name),
                    str(class_name),
                ): round(float(probability), 4)
                for class_name, probability in zip(
                    classes,
                    raw_probabilities,
                )
            }
            confidence = round(
                float(max(raw_probabilities)),
                4,
            )

        output = {
            "diagnostic_result_id": result.id,
            "student_id": result.user_id,
            "rule_level": result.level,
            "model_prediction": predicted_label,
            "model_prediction_slug": predicted_slug,
            "confidence": confidence,
            "probabilities": probabilities,
            "model_name": model_name,
            "model_version": model_version,
            "features": features,
            "scientific_status": (
                "Prédiction de prototype basée sur un modèle "
                "entraîné avec un dataset synthétique contrôlé."
            ),
        }

        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            )
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
