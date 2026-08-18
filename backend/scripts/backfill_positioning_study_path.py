from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import DiagnosticResult, StudyPath
from app.services.positioning_path_service import (
    create_or_refresh_from_diagnostic,
    is_french_subject,
)


def main() -> None:
    init_db()
    created_or_refreshed = 0
    archived = 0
    seen_users: set[int] = set()

    with SessionLocal() as db:
        existing_paths = db.scalars(
            select(StudyPath)
            .where(
                StudyPath.source_diagnostic_result_id.is_not(None),
                StudyPath.active.is_(True),
            )
            .options(selectinload(StudyPath.subject))
        ).all()

        for path in existing_paths:
            if not is_french_subject(path.subject):
                path.active = False
                if path.status == "active":
                    path.status = "archived"
                path.updated_at = datetime.utcnow()
                archived += 1

        results = db.scalars(
            select(DiagnosticResult)
            .options(
                selectinload(DiagnosticResult.user),
                selectinload(DiagnosticResult.subject),
            )
            .order_by(
                DiagnosticResult.created_at.desc(),
                DiagnosticResult.id.desc(),
            )
        ).all()

        for result in results:
            if result.user is None or not is_french_subject(result.subject):
                continue
            if result.user_id in seen_users:
                continue

            seen_users.add(result.user_id)
            summary = create_or_refresh_from_diagnostic(
                db,
                result.user,
                result,
                recommendations=list(result.recommendations or []),
                results_by_topic=list(result.results_by_topic or []),
            )
            if summary:
                created_or_refreshed += 1
                print(
                    f"[OK] user={result.user.email} "
                    f"diagnostic={result.id} path={summary['id']} "
                    f"course={summary['course_id']}"
                )
            else:
                print(
                    f"[SKIP] user={result.user.email} diagnostic={result.id} "
                    "aucun cours français compatible"
                )

        db.commit()

    print(f"\nAnciens parcours non français archivés : {archived}")
    print(f"Parcours français créés ou actualisés : {created_or_refreshed}")


if __name__ == "__main__":
    main()
