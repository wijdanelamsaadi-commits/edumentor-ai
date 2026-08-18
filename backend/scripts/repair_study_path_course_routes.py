from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import StudyPath


def main() -> None:
    init_db()
    updated = 0

    with SessionLocal() as db:
        paths = db.scalars(
            select(StudyPath)
            .where(StudyPath.active.is_(True))
            .options(selectinload(StudyPath.items))
        ).all()

        for path in paths:
            for item in path.items:
                if item.item_type not in {"review_chapter", "exercise"}:
                    continue

                chapter_id = (
                    item.entity_id
                    or (item.metadata_json or {}).get("chapter_id")
                )
                if not chapter_id:
                    continue

                mode = "exercise" if item.item_type == "exercise" else "review"
                next_route = (
                    f"/courses/{path.course_id}"
                    f"?chapter_id={int(chapter_id)}&mode={mode}"
                )

                if item.route != next_route:
                    item.route = next_route
                    updated += 1

        db.commit()

    print(f"Routes de parcours actualisées : {updated}")


if __name__ == "__main__":
    main()
