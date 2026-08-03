from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import Course, StudyPath
from app.services.positioning_path_service import is_french_subject


def main() -> None:
    init_db()

    with SessionLocal() as db:
        published_courses = db.scalars(
            select(Course)
            .where(Course.published.is_(True))
            .options(selectinload(Course.subject))
            .order_by(Course.display_order, Course.id)
        ).all()
        french_courses = [
            course for course in published_courses
            if is_french_subject(course.subject)
        ]

        print("=== COURS FRANÇAIS PUBLIÉS ===")
        for course in french_courses:
            print(
                f"{course.id} | ordre={course.display_order} "
                f"| {course.title}"
            )

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

        print("\n=== PARCOURS FRANÇAIS ACTIFS ===")
        for path in french_paths:
            print(
                f"path={path.id} | student={path.student.email if path.student else path.student_id} "
                f"| course={path.course.title if path.course else path.course_id} "
                f"| items={len(path.items)}"
            )


if __name__ == "__main__":
    main()
