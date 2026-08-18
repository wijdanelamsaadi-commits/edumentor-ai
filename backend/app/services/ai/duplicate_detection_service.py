from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(character for character in text if unicodedata.category(character) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


def token_similarity(left: str | None, right: str | None) -> float:
    left_tokens = set(normalize_text(left).split())
    right_tokens = set(normalize_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def max_similarity(text: str | None, candidates: list[str], threshold: float | None = None) -> float:
    score = max((token_similarity(text, candidate) for candidate in candidates), default=0.0)
    return round(score, 4)


def is_duplicate(text: str | None, candidates: list[str], threshold: float) -> bool:
    return max_similarity(text, candidates) >= threshold

