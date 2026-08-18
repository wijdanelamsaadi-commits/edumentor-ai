from app.services.chapter_exercise_service import evaluate_exercise

correct_answer = """La Boîte à merveilles — Ahmed Sefrioui — roman autobiographique
Antigone — Jean Anouilh — tragédie moderne
Le Dernier Jour d’un condamné — Victor Hugo — roman à thèse"""

answer = """la Boîte à merveilles — Ahmed Sefrioui — roman autobiographique
Antigone — Jean Anouilh — tragédie moderne
Le Dernier Jour d’un condamné — Victor Hugo — roman à thèse"""

exercise = {
    "type": "response_short",
    "points": 1,
    "correct_answer": correct_answer,
    "expected_elements": [correct_answer],
    "correction": correct_answer,
    "explanation": "",
}

print(evaluate_exercise(exercise, answer))
