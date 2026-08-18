from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, init_db
from app.models.persistence import Course, DiagnosticResult, StudyPath
from app.services.positioning_path_service import (
    create_or_refresh_from_diagnostic,
    is_french_subject,
)

GENERAL_COURSE_ID = 12
WORK_COURSE_ID = 23

ARCHIVE_COURSE_IDS = {
    10,  # démonstration
    11,  # démonstration dupliquée
    13,  # version courte du cours régional
    15,  # prototype
    16,  # ancienne version
    17,  # ancienne version corrigée
    18,  # ancienne variante
    19,  # ancienne variante PDF
    20,  # ancienne variante LaTeX
    22,  # variante quiz dupliquant le contenu
}

COMPETENCE_LABELS = {
    "comprehension": "Compréhension",
    "langue_grammaire": "Langue et grammaire",
    "connaissance_oeuvres": "Connaissance des œuvres",
    "figures_procedes": "Figures de style et procédés",
    "interpretation_justification": "Interprétation et justification",
}


def weakest_competence(result: DiagnosticResult) -> str:
    rows = [
        row
        for row in (result.results_by_topic or [])
        if isinstance(row, dict) and row.get("name")
    ]
    if not rows:
        return "comprehension"
    weakest = min(rows, key=lambda row: float(row.get("percentage") or 0))
    return str(weakest.get("name") or "comprehension")


def build_recommendations(
    result: DiagnosticResult,
    general_course: Course,
    work_course: Course,
) -> list[dict]:
    weakest = weakest_competence(result)
    weakest_label = COMPETENCE_LABELS.get(
        weakest,
        weakest.replace("_", " ").title(),
    )

    if weakest == "connaissance_oeuvres":
        ordered_courses = [work_course, general_course]
    else:
        ordered_courses = [general_course, work_course]

    recommendations = []
    for course in ordered_courses:
        recommendations.append({
            "course_id": course.id,
            "title": course.title,
            "level": course.level,
            "reason": f"Recommandé pour renforcer : {weakest_label}.",
            "path": f"/courses/{course.id}",
        })
    return recommendations


def main() -> None:
    init_db()

    with SessionLocal() as db:
        courses = {
            course.id: course
            for course in db.scalars(
                select(Course)
                .where(Course.id.in_(
                    {GENERAL_COURSE_ID, WORK_COURSE_ID, *ARCHIVE_COURSE_IDS}
                ))
                .options(selectinload(Course.subject))
            ).all()
        }

        general_course = courses.get(GENERAL_COURSE_ID)
        work_course = courses.get(WORK_COURSE_ID)

        if general_course is None:
            raise SystemExit(f"Cours principal introuvable : ID {GENERAL_COURSE_ID}")
        if work_course is None:
            raise SystemExit(f"Cours de l'œuvre introuvable : ID {WORK_COURSE_ID}")
        if not is_french_subject(general_course.subject):
            raise SystemExit("Le cours principal ID 12 n'est pas rattaché au Français.")
        if not is_french_subject(work_course.subject):
            raise SystemExit("Le cours ID 23 n'est pas rattaché au Français.")

        # Conserver deux cours propres et compréhensibles côté élève.
        general_course.title = "Français 1ère Bac — Préparation complète au régional"
        general_course.display_order = 1
        general_course.published = True
        general_course.status = "published"
        general_course.updated_at = datetime.utcnow()

        work_course.title = "La Boîte à Merveilles — Parcours complet et adaptatif"
        work_course.display_order = 2
        work_course.published = True
        work_course.status = "published"
        work_course.updated_at = datetime.utcnow()

        archived = 0
        for course_id in sorted(ARCHIVE_COURSE_IDS):
            course = courses.get(course_id)
            if course is None:
                continue
            course.published = False
            course.status = "archived"
            course.display_order = 900 + course.id
            course.updated_at = datetime.utcnow()
            archived += 1

        # Actualiser les recommandations sauvegardées.
        diagnostics = db.scalars(
            select(DiagnosticResult)
            .options(
                selectinload(DiagnosticResult.subject),
                selectinload(DiagnosticResult.user),
            )
            .order_by(
                DiagnosticResult.created_at.desc(),
                DiagnosticResult.id.desc(),
            )
        ).all()

        latest_by_user: dict[int, DiagnosticResult] = {}
        updated_diagnostics = 0

        for result in diagnostics:
            if not is_french_subject(result.subject):
                continue

            result.recommendations = build_recommendations(
                result,
                general_course,
                work_course,
            )
            updated_diagnostics += 1
            latest_by_user.setdefault(result.user_id, result)

        # Archiver les parcours actifs qui pointent encore vers un ancien cours.
        old_paths = db.scalars(
            select(StudyPath).where(
                StudyPath.source_diagnostic_result_id.is_not(None),
                StudyPath.active.is_(True),
                StudyPath.course_id.in_(ARCHIVE_COURSE_IDS),
            )
        ).all()

        for path in old_paths:
            path.active = False
            path.status = "archived"
            path.updated_at = datetime.utcnow()

        db.flush()

        # Recréer un parcours propre depuis le dernier diagnostic français.
        refreshed_paths = 0
        for result in latest_by_user.values():
            if result.user is None:
                continue

            summary = create_or_refresh_from_diagnostic(
                db,
                result.user,
                result,
                recommendations=list(result.recommendations or []),
                results_by_topic=list(result.results_by_topic or []),
            )
            if summary:
                refreshed_paths += 1
                print(
                    f"[OK] {result.user.email} | diagnostic={result.id} "
                    f"| parcours={summary['id']} | cours={summary['course_id']}"
                )

        db.commit()

        print("\n=== NETTOYAGE TERMINÉ ===")
        print("Cours conservés :")
        print(f"  {general_course.id} | {general_course.title}")
        print(f"  {work_course.id} | {work_course.title}")
        print(f"Cours archivés : {archived}")
        print(f"Diagnostics actualisés : {updated_diagnostics}")
        print(f"Parcours actualisés : {refreshed_paths}")


if __name__ == "__main__":
    main()
