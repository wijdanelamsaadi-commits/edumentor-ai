from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import StudyPath
from app.services.positioning_path_service import is_french_subject


def main() -> None:
    init_db()

    with SessionLocal() as db:
        paths = db.scalars(
            select(StudyPath)
            .where(
                StudyPath.source_diagnostic_result_id.is_not(None),
                StudyPath.active.is_(True),
                StudyPath.status == "active",
            )
            .options(
                selectinload(StudyPath.student),
                selectinload(StudyPath.subject),
                selectinload(StudyPath.course),
                selectinload(StudyPath.items),
            )
            .order_by(StudyPath.updated_at.desc(), StudyPath.id.desc())
        ).all()

        french_paths = [path for path in paths if is_french_subject(path.subject)]

        if not french_paths:
            raise SystemExit(
                "Aucun parcours français actif issu du test de positionnement."
            )

        for path in french_paths:
            print("\n=== PARCOURS PERSONNALISÉ FRANÇAIS ===")
            print("id:", path.id)
            print("student_id:", path.student_id)
            print("student:", path.student.email if path.student else path.student_id)
            print("subject:", path.subject.name if path.subject else path.subject_id)
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
