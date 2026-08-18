from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter
from pathlib import Path


SEED = 20260801
PROFILES_PER_LEVEL = 500
ATTEMPTS_PER_PROFILE = 4

OUTPUT_CSV = Path(__file__).resolve().parent / "positioning_dataset.csv"
OUTPUT_METADATA = (
    Path(__file__).resolve().parent
    / "positioning_dataset_metadata.json"
)

LEVELS = {
    "debutant": {
        "ability_mean": -1.00,
        "ability_std": 0.35,
    },
    "intermediaire": {
        "ability_mean": 0.25,
        "ability_std": 0.35,
    },
    "avance": {
        "ability_mean": 1.50,
        "ability_std": 0.35,
    },
}

COMPETENCES = [
    "comprehension",
    "langue_grammaire",
    "connaissance_oeuvres",
    "figures_procedes",
    "interpretation_justification",
]

DIFFICULTY_EFFECT = {
    # Une valeur négative rend la question plus facile.
    "debutant": -0.55,
    "intermediaire": 0.20,
    "avance": 0.90,
}

# Chaque compétence reçoit quatre questions.
# Le total d'un test reste toujours :
# 7 débutant, 7 intermédiaire et 6 avancé.
QUOTA_PATTERNS = [
    {"debutant": 2, "intermediaire": 1, "avance": 1},
    {"debutant": 2, "intermediaire": 1, "avance": 1},
    {"debutant": 1, "intermediaire": 2, "avance": 1},
    {"debutant": 1, "intermediaire": 2, "avance": 1},
    {"debutant": 1, "intermediaire": 1, "avance": 2},
]

CSV_COLUMNS = [
    "profile_id",
    "attempt_id",
    "synthetic",
    "generator_version",
    "label_niveau",
    "score_global",
    "questions_repondues",
    "bonnes_reponses",
    "taux_reponse",
    "score_comprehension",
    "score_langue_grammaire",
    "score_connaissance_oeuvres",
    "score_figures_procedes",
    "score_interpretation_justification",
    "score_debutant",
    "score_intermediaire",
    "score_avance",
]


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def percentage(correct: int, total: int) -> int:
    if total <= 0:
        return 0
    return round((correct / total) * 100)


def simulate_attempt(
    rng: random.Random,
    profile_id: str,
    attempt_id: int,
    label: str,
    base_ability: float,
    competence_offsets: dict[str, float],
) -> dict[str, object]:
    quota_patterns = [dict(pattern) for pattern in QUOTA_PATTERNS]
    rng.shuffle(quota_patterns)

    correct_by_competence = {
        competence: 0
        for competence in COMPETENCES
    }
    total_by_competence = {
        competence: 0
        for competence in COMPETENCES
    }

    correct_by_difficulty = {
        difficulty: 0
        for difficulty in DIFFICULTY_EFFECT
    }
    total_by_difficulty = {
        difficulty: 0
        for difficulty in DIFFICULTY_EFFECT
    }

    # Petite variation naturelle entre plusieurs tentatives
    # du même profil.
    attempt_effect = rng.gauss(0.0, 0.12)

    for competence, quota in zip(
        COMPETENCES,
        quota_patterns,
    ):
        for difficulty, question_count in quota.items():
            for _ in range(question_count):
                item_noise = rng.gauss(0.0, 0.15)

                logit = (
                    base_ability
                    + competence_offsets[competence]
                    + attempt_effect
                    - DIFFICULTY_EFFECT[difficulty]
                    + item_noise
                )

                probability_correct = sigmoid(logit)
                is_correct = rng.random() < probability_correct

                total_by_competence[competence] += 1
                total_by_difficulty[difficulty] += 1

                if is_correct:
                    correct_by_competence[competence] += 1
                    correct_by_difficulty[difficulty] += 1

    total_questions = sum(total_by_competence.values())
    total_correct = sum(correct_by_competence.values())

    if total_questions != 20:
        raise RuntimeError(
            f"Test synthétique invalide : {total_questions} questions."
        )

    expected_difficulty_totals = {
        "debutant": 7,
        "intermediaire": 7,
        "avance": 6,
    }
    if total_by_difficulty != expected_difficulty_totals:
        raise RuntimeError(
            "Répartition des difficultés invalide : "
            f"{total_by_difficulty}"
        )

    return {
        "profile_id": profile_id,
        "attempt_id": attempt_id,
        "synthetic": True,
        "generator_version": "positioning_synthetic_v1",
        "label_niveau": label,
        "score_global": percentage(total_correct, total_questions),
        "questions_repondues": total_questions,
        "bonnes_reponses": total_correct,
        "taux_reponse": 100,
        "score_comprehension": percentage(
            correct_by_competence["comprehension"],
            total_by_competence["comprehension"],
        ),
        "score_langue_grammaire": percentage(
            correct_by_competence["langue_grammaire"],
            total_by_competence["langue_grammaire"],
        ),
        "score_connaissance_oeuvres": percentage(
            correct_by_competence["connaissance_oeuvres"],
            total_by_competence["connaissance_oeuvres"],
        ),
        "score_figures_procedes": percentage(
            correct_by_competence["figures_procedes"],
            total_by_competence["figures_procedes"],
        ),
        "score_interpretation_justification": percentage(
            correct_by_competence[
                "interpretation_justification"
            ],
            total_by_competence[
                "interpretation_justification"
            ],
        ),
        "score_debutant": percentage(
            correct_by_difficulty["debutant"],
            total_by_difficulty["debutant"],
        ),
        "score_intermediaire": percentage(
            correct_by_difficulty["intermediaire"],
            total_by_difficulty["intermediaire"],
        ),
        "score_avance": percentage(
            correct_by_difficulty["avance"],
            total_by_difficulty["avance"],
        ),
    }


def main() -> None:
    rng = random.Random(SEED)
    rows: list[dict[str, object]] = []

    for label, config in LEVELS.items():
        for profile_index in range(1, PROFILES_PER_LEVEL + 1):
            profile_id = f"{label}_{profile_index:04d}"

            base_ability = rng.gauss(
                config["ability_mean"],
                config["ability_std"],
            )

            competence_offsets = {
                competence: rng.gauss(0.0, 0.30)
                for competence in COMPETENCES
            }

            for attempt_id in range(1, ATTEMPTS_PER_PROFILE + 1):
                rows.append(
                    simulate_attempt(
                        rng=rng,
                        profile_id=profile_id,
                        attempt_id=attempt_id,
                        label=label,
                        base_ability=base_ability,
                        competence_offsets=competence_offsets,
                    )
                )

    with OUTPUT_CSV.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=CSV_COLUMNS,
        )
        writer.writeheader()
        writer.writerows(rows)

    label_counts = Counter(
        str(row["label_niveau"])
        for row in rows
    )
    profile_counts = Counter(
        str(row["profile_id"]).split("_")[0]
        for row in rows[::ATTEMPTS_PER_PROFILE]
    )

    metadata = {
        "generator_version": "positioning_synthetic_v1",
        "seed": SEED,
        "synthetic": True,
        "total_rows": len(rows),
        "profiles_per_level": PROFILES_PER_LEVEL,
        "attempts_per_profile": ATTEMPTS_PER_PROFILE,
        "total_profiles": (
            PROFILES_PER_LEVEL * len(LEVELS)
        ),
        "label_distribution": dict(label_counts),
        "profile_distribution": dict(profile_counts),
        "feature_columns": [
            column
            for column in CSV_COLUMNS
            if column.startswith("score_")
            or column in {
                "questions_repondues",
                "bonnes_reponses",
                "taux_reponse",
            }
        ],
        "target_column": "label_niveau",
        "group_column": "profile_id",
        "scientific_status": (
            "Jeu de données synthétique contrôlé, créé pour "
            "prototyper et comparer les modèles. Il ne remplace "
            "pas une validation ultérieure sur de vrais élèves."
        ),
        "anti_leakage_rule": (
            "Les futures séparations train/test doivent être "
            "faites par profile_id, jamais ligne par ligne."
        ),
        "generation_principle": (
            "Le label provient d'un profil latent. Les scores "
            "observés sont ensuite simulés question par question "
            "avec variation par compétence, difficulté et tentative."
        ),
    }

    OUTPUT_METADATA.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Dataset synthétique créé avec succès.")
    print(f"Fichier CSV       : {OUTPUT_CSV}")
    print(f"Fichier métadonnées : {OUTPUT_METADATA}")
    print(f"Nombre de lignes  : {len(rows)}")
    print(f"Nombre de profils : {metadata['total_profiles']}")
    print(f"Distribution      : {dict(label_counts)}")


if __name__ == "__main__":
    main()
