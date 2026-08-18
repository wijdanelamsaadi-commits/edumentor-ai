from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import StudyPath


def main() -> None:
    init_db()

    with SessionLocal() as db:
        paths = db.scalars(
            select(StudyPath)
            .where(
                StudyPath.active.is_(True),
                StudyPath.status.in_(["active", "completed"]),
            )
            .options(
                selectinload(StudyPath.student),
                selectinload(StudyPath.course),
                selectinload(StudyPath.items),
            )
            .order_by(StudyPath.updated_at.desc(), StudyPath.id.desc())
        ).all()

        print("=== ÉTAPES D'EXERCICES DU PARCOURS ===")
        for path in paths:
            exercise_items = [
                item
                for item in sorted(path.items, key=lambda row: row.order_index)
                if item.item_type == "exercise"
            ]
            if not exercise_items:
                continue

            print(
                f"\npath={path.id} | "
                f"student={path.student.email if path.student else path.student_id} | "
                f"course={path.course.title if path.course else path.course_id} | "
                f"progress={path.progress_percentage}%"
            )
            for item in exercise_items:
                print(
                    f"  {item.order_index}. chapter={item.entity_id} "
                    f"| status={item.status} | {item.title}"
                )


if __name__ == "__main__":
    main()
