from __future__ import annotations

import random
from collections import Counter

from sqlalchemy import select

from app.core.database import get_db
from app.models.persistence import DiagnosticQuestion


SUBJECT_ID = 1534
GENERATION_METHOD = "curated_positioning_v2"


def main() -> None:
    db = next(get_db())

    try:
        questions = list(
            db.scalars(
                select(DiagnosticQuestion)
                .where(
                    DiagnosticQuestion.subject_id == SUBJECT_ID,
                    DiagnosticQuestion.active.is_(True),
                    DiagnosticQuestion.generation_method == GENERATION_METHOD,
                )
                .order_by(DiagnosticQuestion.id)
            )
        )

        if not questions:
            raise RuntimeError("Aucune question V2 active n'a été trouvée.")

        position_counts: Counter[int] = Counter()

        for index, question in enumerate(questions):
            choices = [str(choice).strip() for choice in (question.choices or [])]
            correct_answer = str(question.correct_answer or "").strip()

            if len(choices) != 4:
                raise ValueError(
                    f"La question {question.id} ne contient pas exactement 4 choix."
                )
            if correct_answer not in choices:
                raise ValueError(
                    f"La bonne réponse de la question {question.id} "
                    "ne figure pas dans ses choix."
                )
            if len(set(choices)) != 4:
                raise ValueError(
                    f"La question {question.id} contient des choix dupliqués."
                )

            # Répartition équilibrée des bonnes réponses :
            # position 1, 2, 3, 4, puis on recommence.
            target_position = index % 4

            distractors = [
                choice for choice in choices
                if choice != correct_answer
            ]

            # Mélange déterministe : le script peut être relancé sans
            # produire un ordre différent à chaque exécution.
            stable_seed = f"edumentor-positioning-v2-{question.id}"
            random.Random(stable_seed).shuffle(distractors)

            reordered = distractors.copy()
            reordered.insert(target_position, correct_answer)

            question.choices = reordered
            position_counts[target_position + 1] += 1

        db.commit()

        print("Réorganisation terminée avec succès.")
        print(f"Questions mises à jour : {len(questions)}")
        for position in range(1, 5):
            print(
                f"Bonne réponse en position {position} : "
                f"{position_counts[position]}"
            )

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
