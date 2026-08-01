from __future__ import annotations

from collections import Counter
from typing import Any

DIFFICULTY_ORDER = ["debutant", "intermediaire", "avance"]


def next_difficulty(previous_difficulty: str | None, was_correct: bool) -> str:
    current = previous_difficulty if previous_difficulty in DIFFICULTY_ORDER else "debutant"
    index = DIFFICULTY_ORDER.index(current)
    if was_correct:
        return DIFFICULTY_ORDER[min(len(DIFFICULTY_ORDER) - 1, index + 1)]
    return DIFFICULTY_ORDER[max(0, index - 1)]


def estimate_level(sequence: list[dict[str, Any]]) -> dict[str, Any]:
    if not sequence:
        return {"level": "debutant", "confidence": 0, "justification": "Aucune réponse disponible."}
    correct_by_level = Counter()
    total_by_level = Counter()
    for item in sequence:
        level = item.get("difficulty") or "debutant"
        total_by_level[level] += 1
        if item.get("correct"):
            correct_by_level[level] += 1
    if correct_by_level["avance"] >= max(1, total_by_level["avance"] * 0.6):
        level = "avance"
    elif correct_by_level["intermediaire"] >= max(1, total_by_level["intermediaire"] * 0.5):
        level = "intermediaire"
    else:
        level = "debutant"
    confidence = round(sum(correct_by_level.values()) / max(1, sum(total_by_level.values())), 2)
    return {"level": level, "confidence": confidence, "justification": "Niveau calculé côté backend à partir de la séquence adaptative."}

