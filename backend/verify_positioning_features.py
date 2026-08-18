from __future__ import annotations

import json

from sqlalchemy import select

from app.core.database import get_db
from app.models.persistence import DiagnosticResult
from app.services.diagnostic_service import build_positioning_features


SUBJECT_ID = 1534


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
            print("Passe d'abord un test complet depuis l'interface.")
            return

        features = build_positioning_features(
            score=result.score,
            total=result.total,
            correct_count=result.correct_count,
            results_by_topic=result.results_by_topic,
            results_by_difficulty=result.results_by_difficulty,
        )

        output = {
            "diagnostic_result_id": result.id,
            "student_id": result.user_id,
            "level_actuel": result.level,
            "positioning_features": features,
        }

        print(json.dumps(output, ensure_ascii=False, indent=2))

    finally:
        db.close()


if __name__ == "__main__":
    main()
