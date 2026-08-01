from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import get_db
from app.models.persistence import DiagnosticResult
from app.services import diagnostic_service


SUBJECT_ID = 1534


def normalize_rows(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def fallback_features(result: DiagnosticResult) -> dict[str, int]:
    topic_map = {
        "Compréhension": "score_comprehension",
        "Langue et grammaire": "score_langue_grammaire",
        "Connaissance des œuvres": "score_connaissance_oeuvres",
        "Figures de style et procédés": "score_figures_procedes",
        "Interprétation et justification": "score_interpretation_justification",
    }
    difficulty_map = {
        "debutant": "score_debutant",
        "intermediaire": "score_intermediaire",
        "avance": "score_avance",
    }

    topic_scores = {
        str(row.get("name") or "").strip(): int(row.get("percentage") or 0)
        for row in normalize_rows(result.results_by_topic)
        if isinstance(row, dict)
    }
    difficulty_scores = {
        str(row.get("name") or "").strip().lower(): int(row.get("percentage") or 0)
        for row in normalize_rows(result.results_by_difficulty)
        if isinstance(row, dict)
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

    for label, key in topic_map.items():
        features[key] = topic_scores.get(label, 0)

    for slug, key in difficulty_map.items():
        features[key] = difficulty_scores.get(slug, 0)

    return features


def main() -> None:
    source_path = Path(diagnostic_service.__file__).resolve()

    integration_checks = {
        "diagnostic_service_path": str(source_path),
        "has_build_positioning_features": hasattr(
            diagnostic_service,
            "build_positioning_features",
        ),
        "has_predict_positioning_level": hasattr(
            diagnostic_service,
            "predict_positioning_level",
        ),
        "has_model_path_constant": hasattr(
            diagnostic_service,
            "POSITIONING_MODEL_PATH",
        ),
    }

    model_path = getattr(
        diagnostic_service,
        "POSITIONING_MODEL_PATH",
        None,
    )
    integration_checks["model_path"] = (
        str(model_path) if model_path is not None else None
    )
    integration_checks["model_file_exists"] = (
        bool(model_path and Path(model_path).exists())
    )

    db = next(get_db())

    try:
        result = db.scalars(
            select(DiagnosticResult)
            .where(DiagnosticResult.subject_id == SUBJECT_ID)
            .order_by(DiagnosticResult.created_at.desc())
        ).first()

        if result is None:
            output = {
                "integration_checks": integration_checks,
                "latest_result": None,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return

        if hasattr(diagnostic_service, "build_positioning_features"):
            features = diagnostic_service.build_positioning_features(
                score=result.score,
                total=result.total,
                correct_count=result.correct_count,
                results_by_topic=result.results_by_topic,
                results_by_difficulty=result.results_by_difficulty,
            )
        else:
            features = fallback_features(result)

        model_detection = None
        if hasattr(diagnostic_service, "predict_positioning_level"):
            model_detection = diagnostic_service.predict_positioning_level(
                features
            )

        output = {
            "integration_checks": integration_checks,
            "latest_result": {
                "id": result.id,
                "score": result.score,
                "stored_level": result.level,
                "stored_justification": result.justification,
                "features": features,
                "model_detection_now": model_detection,
            },
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))

    finally:
        db.close()


if __name__ == "__main__":
    main()
