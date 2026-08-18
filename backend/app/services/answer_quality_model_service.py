from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
import re
import unicodedata

import joblib
import numpy as np
from scipy.sparse import csr_matrix, hstack


MODEL_VERSION = "answer-quality-v1-20260801"
MODEL_PATH = Path(__file__).resolve().parents[1] / "nlp_runtime" / "models" / "answer_quality_classifier_v1.joblib"

_STOP_WORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "d", "et", "ou",
    "à", "a", "au", "aux", "en", "dans", "sur", "par", "pour", "avec",
    "sans", "est", "sont", "que", "qui", "se", "sa", "son", "ses", "ce",
    "cette", "ces", "il", "elle", "ils", "elles", "l", "ne", "pas",
}

_CANONICAL_TOKENS = {
    "seul": "solitude", "seule": "solitude", "seuls": "solitude",
    "seules": "solitude", "solitude": "solitude", "isole": "solitude",
    "isolee": "solitude", "isolement": "solitude",
    "refuge": "refuge", "refugie": "refuge", "refugier": "refuge", "abri": "refuge",
    "console": "reconfort", "consoler": "reconfort",
    "consolation": "reconfort", "reconfort": "reconfort",
    "reconforter": "reconfort",
    "imagination": "imagination", "imaginaire": "imagination",
    "imaginer": "imagination", "reve": "imagination", "rever": "imagination",
    "defend": "defendre", "defendre": "defendre", "defense": "defendre",
    "denonce": "denoncer", "denoncer": "denoncer", "denonciation": "denoncer",
    "mort": "mort", "execution": "mort", "executer": "mort",
    "peur": "peur", "angoisse": "peur", "effroi": "peur",
    "souffrance": "souffrance", "souffre": "souffrance", "souffrir": "souffrance",
    "loi": "loi", "regle": "loi", "interdiction": "loi",
    "ordre": "ordre", "stabilite": "ordre",
    "conscience": "conscience", "conviction": "conscience",
    "convictions": "conscience", "principes": "conscience",
    "enfance": "enfance", "enfant": "enfance",
    "souvenir": "souvenir", "souvenirs": "souvenir", "memoire": "souvenir",
    "auteur": "auteur", "ecrivain": "auteur",
    "explique": "expliquer", "expliquer": "expliquer", "explication": "expliquer",
    "idee": "idee", "these": "idee", "message": "idee",
    "preuve": "indice", "indice": "indice", "exemple": "indice",
    "rythme": "rythme", "insistance": "insistance",
    "repete": "repetition", "repetition": "repetition",
}


@lru_cache(maxsize=1)
def load_model_bundle() -> dict[str, Any] | None:
    if not MODEL_PATH.exists():
        return None
    try:
        bundle = joblib.load(MODEL_PATH)
    except Exception:
        return None
    return bundle if isinstance(bundle, dict) else None


def get_model_debug() -> dict[str, Any]:
    bundle = load_model_bundle()
    return {
        "version": bundle.get("version") if bundle else MODEL_VERSION,
        "path": str(MODEL_PATH),
        "loaded": bundle is not None,
        "training_examples": bundle.get("training_examples") if bundle else None,
        "question_count": bundle.get("question_count") if bundle else None,
    }


def predict_answer_quality(*, question: str, reference: str, answer: str) -> dict[str, Any] | None:
    bundle = load_model_bundle()
    if not bundle or not reference.strip() or not answer.strip():
        return None

    vectorizer = bundle.get("vectorizer")
    classifier = bundle.get("classifier")
    if vectorizer is None or classifier is None:
        return None

    numeric = numeric_features(reference, answer)
    feature_text = build_feature_text(question, reference, answer, numeric)

    text_matrix = vectorizer.transform([feature_text])
    numeric_matrix = csr_matrix(np.asarray([numeric], dtype=float))
    matrix = hstack([text_matrix, numeric_matrix])

    probabilities = classifier.predict_proba(matrix)[0]
    classes = list(classifier.classes_)
    best_index = int(np.argmax(probabilities))
    label = str(classes[best_index])

    return {
        "label": label,
        "confidence": float(probabilities[best_index]),
        "probabilities": {
            str(name): float(probabilities[index])
            for index, name in enumerate(classes)
        },
        "coverage": float(numeric[0]),
        "precision": float(numeric[1]),
        "jaccard": float(numeric[2]),
        "sequence_similarity": float(numeric[3]),
        "length_ratio": float(numeric[4]),
        "version": str(bundle.get("version") or MODEL_VERSION),
    }


def build_feature_text(question: str, reference: str, answer: str, numeric: list[float]) -> str:
    markers = [
        f"COVERAGE_{bucket(numeric[0])}",
        f"PRECISION_{bucket(numeric[1])}",
        f"JACCARD_{bucket(numeric[2])}",
        f"SEQUENCE_{bucket(numeric[3])}",
        f"LENGTH_{bucket(numeric[4])}",
        "NEGATION_MISMATCH" if numeric[5] else "NEGATION_MATCH",
    ]
    return (
        f"QUESTION {question} "
        f"REFERENCE {reference} "
        f"ANSWER {answer} "
        f"FEATURES {' '.join(markers)}"
    )


def numeric_features(reference: str, answer: str) -> list[float]:
    reference_tokens = canonical_tokens(reference)
    answer_tokens = canonical_tokens(answer)

    coverage = fuzzy_coverage(reference_tokens, answer_tokens)
    precision = fuzzy_coverage(answer_tokens, reference_tokens)

    matched_reference = coverage * len(reference_tokens)
    matched_answer = precision * len(answer_tokens)
    approximate_intersection = (matched_reference + matched_answer) / 2
    denominator = (
        len(reference_tokens)
        + len(answer_tokens)
        - approximate_intersection
    )
    jaccard = approximate_intersection / denominator if denominator > 0 else 0.0

    normalized_reference = normalize_text(reference)
    normalized_answer = normalize_text(answer)
    sequence = SequenceMatcher(None, normalized_reference, normalized_answer).ratio()

    shortest = min(len(normalized_reference), len(normalized_answer))
    longest = max(len(normalized_reference), len(normalized_answer), 1)
    length_ratio = shortest / longest

    reference_negation = has_negation(normalized_reference)
    answer_negation = has_negation(normalized_answer)
    negation_mismatch = float(reference_negation != answer_negation)

    return [
        coverage,
        precision,
        jaccard,
        sequence,
        length_ratio,
        negation_mismatch,
    ]


def fuzzy_coverage(source_tokens: list[str], target_tokens: list[str]) -> float:
    if not source_tokens or not target_tokens:
        return 0.0

    matched = 0
    for source in source_tokens:
        if any(
            source == target
            or SequenceMatcher(None, source, target).ratio() >= 0.82
            for target in target_tokens
        ):
            matched += 1
    return matched / len(source_tokens)


def canonical_tokens(value: str) -> list[str]:
    return [
        canonical_token(token)
        for token in normalize_text(value).split()
        if len(token) >= 2 and token not in _STOP_WORDS
    ]


def canonical_token(token: str) -> str:
    if token in _CANONICAL_TOKENS:
        return _CANONICAL_TOKENS[token]

    for suffix in (
        "ements", "ement", "ations", "ation", "iques", "ique",
        "euses", "euse", "eurs", "eur", "ées", "ée", "és", "es", "s",
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            token = token[:-len(suffix)]
            break

    return _CANONICAL_TOKENS.get(token, token)


def normalize_text(value: str) -> str:
    clean = "".join(
        char
        for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    ).lower()
    clean = clean.replace("’", "'")
    return re.sub(r"[^a-z0-9']+", " ", clean).strip()


def has_negation(value: str) -> bool:
    padded = f" {value} "
    return any(token in padded for token in (" ne ", " pas ", " faux ", " aucun ", " jamais "))


def bucket(value: float) -> str:
    if value >= 0.85:
        return "VERY_HIGH"
    if value >= 0.65:
        return "HIGH"
    if value >= 0.40:
        return "MEDIUM"
    if value >= 0.20:
        return "LOW"
    return "VERY_LOW"
