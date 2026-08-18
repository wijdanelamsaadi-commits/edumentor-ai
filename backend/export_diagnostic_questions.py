import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.persistence import DiagnosticQuestion

db = next(get_db())

try:
    questions = list(
        db.scalars(
            select(DiagnosticQuestion)
            .options(selectinload(DiagnosticQuestion.difficulty_level))
            .where(
                DiagnosticQuestion.subject_id == 1534,
                DiagnosticQuestion.active.is_(True),
            )
            .order_by(DiagnosticQuestion.id)
        ).unique()
    )

    data = [
        {
            "id": question.id,
            "topic": question.topic,
            "difficulty": (
                question.difficulty_level.slug
                if question.difficulty_level
                else None
            ),
            "question": question.question,
            "choices": question.choices,
            "correct_answer": question.correct_answer,
            "explanation": question.explanation,
            "source_course_id": question.source_course_id,
            "source_chapter_id": question.source_chapter_id,
            "source_block_id": question.source_block_id,
            "generation_method": question.generation_method,
            "source_snapshot": question.source_snapshot,
        }
        for question in questions
    ]

    output_path = "diagnostic_questions_francais.json"

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(f"Export terminé : {len(data)} questions")
    print(f"Fichier : {output_path}")

finally:
    db.close()
