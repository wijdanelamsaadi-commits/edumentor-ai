from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import StudyPath
from app.services import chapter_exercise_service, study_path_service


def main() -> None:
    init_db()
    synchronized = 0

    with SessionLocal() as db:
        paths = db.scalars(
            select(StudyPath)
            .where(
                StudyPath.active.is_(True),
                StudyPath.status.in_(["active", "completed"]),
            )
            .options(
                selectinload(StudyPath.student),
                selectinload(StudyPath.items),
            )
        ).all()

        for path in paths:
            if path.student is None:
                continue

            for item in path.items:
                if item.item_type != "exercise":
                    continue
                if item.status == "locked":
                    continue

                chapter_id = int(
                    item.entity_id
                    or (item.metadata_json or {}).get("chapter_id")
                    or 0
                )
                if not chapter_id:
                    continue

                progress = chapter_exercise_service.get_chapter_exercise_progress(
                    db,
                    path.student,
                    path.course_id,
                    chapter_id,
                )
                sync = study_path_service.sync_chapter_exercise_item(
                    db,
                    path.student,
                    course_id=path.course_id,
                    chapter_id=chapter_id,
                    progress=progress,
                    minimum_score=60,
                )
                if sync:
                    synchronized += 1
                    print(
                        f"[OK] path={path.id} item={item.id} "
                        f"chapter={chapter_id} status={sync['item_status']} "
                        f"score={sync.get('mastery_score', 0)}"
                    )

        db.commit()

    print(f"\nÉtapes d'exercices synchronisées : {synchronized}")


if __name__ == "__main__":
    main()
