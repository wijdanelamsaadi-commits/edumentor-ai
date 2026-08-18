from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from app.services import answer_quality_model_service
from app.services.chapter_exercise_service import (
    EVALUATOR_VERSION,
    EXERCISE_BANK_VERSION,
    evaluate_exercise,
    load_exercise_bank,
    select_adaptive_bank_questions,
)


EXPECTED_COUNTS = {94: 15, 95: 20, 96: 20, 97: 20, 98: 20, 99: 15}


def main() -> None:
    questions = load_exercise_bank()
    counts = Counter(int(item["chapter_id"]) for item in questions)

    assert len(questions) == 110, f"110 questions attendues, obtenu: {len(questions)}"
    assert dict(sorted(counts.items())) == EXPECTED_COUNTS, counts
    assert len({item["id"] for item in questions}) == 110, "Identifiants dupliqués"

    for item in questions:
        assert item.get("question"), f"Question vide: {item.get('id')}"
        assert item.get("correct_answer"), f"Réponse vide: {item.get('id')}"
        choices = item.get("choices") or []
        if choices:
            assert item["correct_answer"] in choices, (
                f"Réponse absente des choix: {item['id']} -> {item['correct_answer']}"
            )

    for chapter_id in EXPECTED_COUNTS:
        for level in ("debutant", "intermediaire", "avance"):
            selected = select_adaptive_bank_questions(chapter_id, level)
            assert len(selected) == 10, (
                f"Série invalide chapitre={chapter_id} niveau={level}: {len(selected)}"
            )

    exact_exercise = {
        "question": "Associez chaque œuvre à son auteur et à son genre.",
        "type": "response_short",
        "points": 3,
        "correct_answer": (
            "La Boîte à merveilles — Ahmed Sefrioui — roman autobiographique ; "
            "Antigone — Jean Anouilh — tragédie moderne ; "
            "Le Dernier Jour d’un condamné — Victor Hugo — roman à thèse"
        ),
        "expected_elements": [
            "La Boîte à merveilles — Ahmed Sefrioui — roman autobiographique",
            "Antigone — Jean Anouilh — tragédie moderne",
            "Le Dernier Jour d’un condamné — Victor Hugo — roman à thèse",
        ],
        "correction": "",
        "explanation": "",
    }
    exact_answer = (
        "La Boîte à merveilles — Ahmed Sefrioui — roman autobiographique\n"
        "Antigone — Jean Anouilh — tragédie moderne\n"
        "Le Dernier Jour d’un condamné — Victor Hugo — roman à thèse"
    )
    exact_result = evaluate_exercise(exact_exercise, exact_answer)
    assert exact_result["correct"] is True, exact_result
    assert exact_result["percentage"] >= 99, exact_result

    model_debug = answer_quality_model_service.get_model_debug()
    assert model_debug["loaded"] is True, model_debug

    model_result = answer_quality_model_service.predict_answer_quality(
        question="Pourquoi la boîte à merveilles est-elle importante ?",
        reference=(
            "Elle sert de refuge à Sidi Mohammed, stimule son imagination "
            "et le console lorsqu’il se sent seul."
        ),
        answer=(
            "Elle lui permet de se réfugier dans son imagination et de se "
            "consoler contre la solitude."
        ),
    )
    assert model_result is not None, "Le modèle n'a pas répondu"
    assert model_result["label"] in {"correct", "partiel"}, model_result

    print("=== VÉRIFICATION RÉUSSIE ===")
    print(f"Banque : {EXERCISE_BANK_VERSION}")
    print(f"Questions : {len(questions)}")
    print(f"Répartition : {dict(sorted(counts.items()))}")
    print("Série affichée : 10 questions adaptées par chapitre")
    print(f"Moteur : {EVALUATOR_VERSION}")
    print(f"Modèle : {model_debug['version']} | chargé={model_debug['loaded']}")
    print(
        "Test de la réponse problématique : "
        f"correct={exact_result['correct']} | score={exact_result['percentage']}%"
    )
    print(
        "Test de paraphrase : "
        f"label={model_result['label']} | confiance={model_result['confidence']:.2%}"
    )


if __name__ == "__main__":
    main()
