from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import get_db
from app.models.persistence import DiagnosticQuestion, DifficultyLevel, Subject


SUBJECT_ID = 1534
SOURCE_FILE = Path(__file__).resolve().parent / "diagnostic_questions_francais_v2.json"
GENERATION_METHOD = "curated_positioning_v2"

COMPETENCE_LABELS = {
    "comprehension": "Compréhension",
    "langue_grammaire": "Langue et grammaire",
    "connaissance_oeuvres": "Connaissance des œuvres",
    "figures_procedes": "Figures de style et procédés",
    "interpretation_justification": "Interprétation et justification",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def main() -> None:
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {SOURCE_FILE}\n"
            "Place diagnostic_questions_francais_v2.json dans le dossier backend."
        )

    rows = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Le fichier JSON doit contenir une liste non vide de questions.")

    db = next(get_db())

    try:
        subject = db.get(Subject, SUBJECT_ID)
        if subject is None:
            raise ValueError(f"Matière introuvable : subject_id={SUBJECT_ID}")

        difficulties = {
            row.slug: row
            for row in db.scalars(
                select(DifficultyLevel).where(
                    DifficultyLevel.slug.in_(["debutant", "intermediaire", "avance"])
                )
            )
        }

        missing_difficulties = {
            slug for slug in ("debutant", "intermediaire", "avance")
            if slug not in difficulties
        }
        if missing_difficulties:
            raise ValueError(
                "Niveaux de difficulté manquants dans la base : "
                + ", ".join(sorted(missing_difficulties))
            )

        # Désactiver uniquement l'ancien lot généré automatiquement.
        old_questions = list(
            db.scalars(
                select(DiagnosticQuestion).where(
                    DiagnosticQuestion.subject_id == SUBJECT_ID,
                    DiagnosticQuestion.active.is_(True),
                    DiagnosticQuestion.generation_method == "deterministic_fallback",
                )
            )
        )
        for question in old_questions:
            question.active = False

        created = 0
        updated = 0

        for item in rows:
            code = str(item.get("code") or "").strip()
            if not code:
                raise ValueError("Chaque question doit avoir un champ 'code'.")

            difficulty_slug = str(item.get("difficulty") or "").strip()
            difficulty = difficulties.get(difficulty_slug)
            if difficulty is None:
                raise ValueError(
                    f"Difficulté invalide pour {code} : {difficulty_slug}"
                )

            choices = item.get("choices") or []
            correct_answer = str(item.get("correct_answer") or "").strip()
            question_text = str(item.get("question") or "").strip()

            if len(choices) != 4:
                raise ValueError(f"{code} doit contenir exactement 4 choix.")
            if correct_answer not in choices:
                raise ValueError(
                    f"La bonne réponse de {code} ne figure pas dans les choix."
                )
            if not question_text:
                raise ValueError(f"Question vide : {code}")

            existing = db.scalars(
                select(DiagnosticQuestion).where(
                    DiagnosticQuestion.subject_id == SUBJECT_ID,
                    DiagnosticQuestion.source_block_id == code,
                )
            ).first()

            competence_slug = str(item.get("competence") or "").strip()
            topic_label = COMPETENCE_LABELS.get(
                competence_slug,
                str(item.get("topic") or competence_slug or "Général").strip(),
            )

            source_snapshot = dict(item.get("source_snapshot") or {})
            source_snapshot.update({
                "positioning_code": code,
                "competence": competence_slug,
                "competence_label": topic_label,
                "original_topic": item.get("topic"),
                "work_id": item.get("work_id"),
                "work_title": item.get("work_title"),
                "education_level": item.get("education_level"),
            })

            values = {
                "subject_id": SUBJECT_ID,
                "education_level_id": None,
                "difficulty_level_id": difficulty.id,
                "topic": topic_label,
                "question": question_text,
                "choices": choices,
                "correct_answer": correct_answer,
                "explanation": str(item.get("explanation") or "").strip(),
                "active": bool(item.get("active", True)),
                "source_course_id": None,
                "source_chapter_id": None,
                "source_block_id": code,
                "generation_method": GENERATION_METHOD,
                "source_hash": sha256_text(
                    f"{item.get('work_id', '')}|{item.get('source_snapshot', {}).get('source_ref', '')}"
                ),
                "question_hash": sha256_text(question_text),
                "source_snapshot": source_snapshot,
            }

            if existing is None:
                db.add(DiagnosticQuestion(**values))
                created += 1
            else:
                for field, value in values.items():
                    setattr(existing, field, value)
                updated += 1

        db.commit()

        active_v2_count = len(
            list(
                db.scalars(
                    select(DiagnosticQuestion.id).where(
                        DiagnosticQuestion.subject_id == SUBJECT_ID,
                        DiagnosticQuestion.active.is_(True),
                        DiagnosticQuestion.generation_method == GENERATION_METHOD,
                    )
                )
            )
        )

        print("Import terminé avec succès.")
        print(f"Anciennes questions désactivées : {len(old_questions)}")
        print(f"Nouvelles questions créées      : {created}")
        print(f"Questions mises à jour          : {updated}")
        print(f"Questions V2 actives            : {active_v2_count}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
