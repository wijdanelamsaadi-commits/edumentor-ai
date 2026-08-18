from __future__ import annotations

from collections import Counter

from app.services.chapter_exercise_service import (
    EXERCISE_BANK_VERSION,
    balance_choice_position,
    load_exercise_bank,
    normalize_text,
)


def main() -> None:
    questions = load_exercise_bank()
    choice_questions = [
        item
        for item in questions
        if len(item.get("choices") or []) >= 2 and item.get("correct_answer")
    ]

    positions = Counter()
    per_chapter_position = Counter()

    chapter_positions: dict[int, int] = {}
    examples = []

    for item in choice_questions:
        chapter_id = int(item.get("chapter_id") or 0)
        chapter_positions[chapter_id] = chapter_positions.get(chapter_id, 0) + 1
        position = chapter_positions[chapter_id]

        choices = [str(value).strip() for value in item.get("choices", []) if str(value).strip()]
        correct_answer = str(item.get("correct_answer") or "").strip()
        reordered = balance_choice_position(
            choices,
            correct_answer,
            chapter_id=chapter_id,
            position=position,
        )

        correct_index = next(
            index
            for index, choice in enumerate(reordered)
            if normalize_text(choice) == normalize_text(correct_answer)
        )
        label = chr(ord("A") + correct_index)
        positions[label] += 1
        per_chapter_position[(chapter_id, label)] += 1

        if len(examples) < 12:
            examples.append(
                (item.get("id"), chapter_id, label, correct_answer, reordered)
            )

    print("=== VÉRIFICATION DES POSITIONS ===")
    print("Version :", EXERCISE_BANK_VERSION)
    print("Questions à choix :", len(choice_questions))
    print("Répartition globale :", dict(sorted(positions.items())))

    for question_id, chapter_id, label, correct_answer, reordered in examples:
        print(
            f"{question_id} | chapitre={chapter_id} | bonne position={label} "
            f"| réponse={correct_answer} | choix={reordered}"
        )

    if len(positions) < 2:
        raise SystemExit("Échec : la bonne réponse reste toujours à la même position.")

    first_ratio = positions.get("A", 0) / max(1, len(choice_questions))
    if first_ratio > 0.45:
        raise SystemExit(
            f"Échec : trop de bonnes réponses restent en A ({first_ratio:.1%})."
        )

    print("\nTest réussi : les bonnes réponses sont réparties entre A/B/C/D.")


if __name__ == "__main__":
    main()
