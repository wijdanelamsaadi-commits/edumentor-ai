from __future__ import annotations

from app.services.chapter_exercise_service import evaluate_exercise


def main() -> None:
    expected = (
        "La Boîte à merveilles — Ahmed Sefrioui — roman autobiographique\n"
        "Antigone — Jean Anouilh — tragédie moderne\n"
        "Le Dernier Jour d’un condamné — Victor Hugo — roman à thèse"
    )

    answer = (
        "La Boîte à merveilles - Ahmed Sefrioui - roman autobiographique. "
        "Antigone - Jean Anouilh - tragédie moderne. "
        "Le Dernier Jour d'un condamné - Victor Hugo - roman à thèse."
    )

    exercise = {
        "type": "response_short",
        "points": 1,
        "correct_answer": expected,
        "expected_elements": expected.splitlines(),
        "correction": expected,
        "explanation": "",
    }

    result = evaluate_exercise(exercise, answer)

    print("correct:", result["correct"])
    print("percentage:", result["percentage"])
    print("points_awarded:", result["points_awarded"])

    if result["correct"] is not True or result["percentage"] < 99:
        raise SystemExit("Le test de tolérance a échoué.")

    print("Test réussi : la réponse équivalente est acceptée.")


if __name__ == "__main__":
    main()
