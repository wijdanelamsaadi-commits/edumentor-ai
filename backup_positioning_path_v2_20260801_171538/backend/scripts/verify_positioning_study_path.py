from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import StudyPath


def main() -> None:
    init_db()

    with SessionLocal() as db:
        path = db.scalars(
            select(StudyPath)
            .where(StudyPath.source_diagnostic_result_id.is_not(None))
            .options(
                selectinload(StudyPath.student),
                selectinload(StudyPath.course),
                selectinload(StudyPath.items),
            )
            .order_by(StudyPath.updated_at.desc(), StudyPath.id.desc())
        ).first()

        if path is None:
            raise SystemExit(
                "Aucun parcours issu du test de positionnement. "
                "Exécutez d'abord scripts/backfill_positioning_study_path.py "
                "ou repassez le test."
            )

        print("=== PARCOURS PERSONNALISÉ ===")
        print("id:", path.id)
        print("student:", path.student.email if path.student else path.student_id)
        print("course:", path.course.title if path.course else path.course_id)
        print("diagnostic_result_id:", path.source_diagnostic_result_id)
        print("source_attempt_id:", path.source_attempt_id)
        print("status:", path.status)
        print("progress:", path.progress_percentage)
        print("items:", len(path.items))
        for item in sorted(path.items, key=lambda row: row.order_index):
            print(
                f"  {item.order_index}. [{item.status}] "
                f"{item.item_type} - {item.title}"
            )


if __name__ == "__main__":
    main()
