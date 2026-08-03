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
            .where(
                StudyPath.active.is_(True),
                StudyPath.status == "active",
            )
            .options(
                selectinload(StudyPath.student),
                selectinload(StudyPath.course),
                selectinload(StudyPath.items),
            )
            .order_by(StudyPath.updated_at.desc(), StudyPath.id.desc())
        ).first()

        if path is None:
            raise SystemExit("Aucun parcours actif.")

        print("=== VÉRIFICATION OUVERTURE DU COURS ===")
        print("student:", path.student.email if path.student else path.student_id)
        print("course:", path.course.title if path.course else path.course_id)
        print("course_id:", path.course_id)
        print("published:", path.course.published if path.course else None)
        print("status:", path.course.status if path.course else None)

        for item in sorted(path.items, key=lambda row: row.order_index):
            if item.item_type in {"review_chapter", "exercise"}:
                print(
                    f"{item.order_index}. {item.item_type} "
                    f"[{item.status}] -> {item.route}"
                )


if __name__ == "__main__":
    main()
