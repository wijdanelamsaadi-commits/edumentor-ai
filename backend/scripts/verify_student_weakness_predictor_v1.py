from __future__ import annotations

import numpy as np

from app.services.student_weakness_model_service import (
    FEATURE_NAMES,
    get_model_debug,
    load_model_artifact,
)


def predict(values: dict) -> tuple[str, dict]:
    artifact = load_model_artifact()
    if not artifact:
        raise SystemExit("Modèle introuvable")
    vector = np.array([[float(values[name]) for name in FEATURE_NAMES]], dtype=float)
    model = artifact["model"]
    label = str(model.predict(vector)[0])
    probabilities = {
        str(name): round(float(value), 4)
        for name, value in zip(model.classes_, model.predict_proba(vector)[0])
    }
    return label, probabilities


def main() -> None:
    debug = get_model_debug()
    print("=== MODÈLE ===")
    for key, value in debug.items():
        print(f"{key}: {value}")

    weak = {
        "average_score": 0.25,
        "correct_rate": 0.20,
        "average_time_norm": 0.82,
        "attempts_norm": 0.65,
        "difficulty_mean": 0.55,
        "trend": -0.12,
        "retry_rate": 0.75,
        "coverage": 1.0,
    }
    mastery = {
        "average_score": 0.90,
        "correct_rate": 0.88,
        "average_time_norm": 0.28,
        "attempts_norm": 0.70,
        "difficulty_mean": 0.65,
        "trend": 0.08,
        "retry_rate": 0.12,
        "coverage": 1.0,
    }

    weak_label, weak_prob = predict(weak)
    mastery_label, mastery_prob = predict(mastery)
    print("\nProfil faible:", weak_label, weak_prob)
    print("Profil maîtrisé:", mastery_label, mastery_prob)

    if weak_label != "faible":
        raise SystemExit("Échec: le profil faible n'est pas reconnu")
    if mastery_label != "maitrise":
        raise SystemExit("Échec: le profil maîtrisé n'est pas reconnu")

    print("\nVÉRIFICATION RÉUSSIE")
    print("Note: métriques obtenues sur données synthétiques contrôlées uniquement.")


if __name__ == "__main__":
    main()
