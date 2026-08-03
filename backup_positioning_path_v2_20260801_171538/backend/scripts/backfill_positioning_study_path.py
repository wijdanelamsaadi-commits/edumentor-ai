from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import DiagnosticResult
from app.services.positioning_path_service import create_or_refresh_from_diagnostic


def main() -> None:
    init_db()
    created_or_refreshed = 0
    seen: set[tuple[int, int | None]] = set()

    with SessionLocal() as db:
        results = db.scalars(
            select(DiagnosticResult)
            .options(selectinload(DiagnosticResult.user))
            .order_by(DiagnosticResult.created_at.desc(), DiagnosticResult.id.desc())
        ).all()

        for result in results:
            key = (result.user_id, result.subject_id)
            if key in seen:
                continue
            seen.add(key)
            if result.user is None or result.user.role != "student":
                continue

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
                    f"[OK] user={result.user.email} diagnostic={result.id} "
                    f"path={summary['id']} course={summary['course_id']}"
                )

        db.commit()

    print(f"\nParcours créés ou actualisés : {created_or_refreshed}")


if __name__ == "__main__":
    main()
