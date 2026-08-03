from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.models.persistence import Course

COURSE_IDS = [12, 13, 17, 18, 19, 20, 22, 23]

with SessionLocal() as db:
    courses = db.scalars(
        select(Course)
        .where(Course.id.in_(COURSE_IDS))
        .options(
            selectinload(Course.chapters),
            selectinload(Course.quiz),
        )
        .order_by(Course.id)
    ).all()

    for course in courses:
        content_chars = sum(len(ch.content or "") for ch in course.chapters)
        structured_count = sum(1 for ch in course.chapters if ch.structured_content)
        exercises_count = sum(
            len(ch.structured_content.get("exercises", []))
            if isinstance(ch.structured_content, dict)
            else 0
            for ch in course.chapters
        )

        print("\n" + "=" * 90)
        print("ID:", course.id)
        print("Titre:", course.title)
        print("Publié:", course.published)
        print("Créé:", course.created_at)
        print("Modifié:", course.updated_at)
        print("PDF:", course.pdf_url or "Aucun")
        print("Import:", course.content_import_status)
        print("Résumé caractères:", len(course.summary or ""))
        print("Description caractères:", len(course.description or ""))
        print("Chapitres:", len(course.chapters))
        print("Contenu total caractères:", content_chars)
        print("Chapitres structurés:", structured_count)
        print("Exercices structurés:", exercises_count)
        print("Quiz présent:", bool(course.quiz))

        print("Titres des chapitres:")
        for chapter in sorted(course.chapters, key=lambda row: row.position):
            print(
                f"  - {chapter.position}: {chapter.title} "
                f"| contenu={len(chapter.content or '')} "
                f"| structuré={bool(chapter.structured_content)}"
            )
