from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

import joblib


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = BACKEND_ROOT / "data" / "nlp_models"
MODELS_DIR = Path(os.getenv("EDUMENTOR_NLP_MODELS_DIR", str(DEFAULT_MODELS_DIR))).resolve()

MODEL_TARGETS = (
    "niveau",
    "record_type",
    "type_information",
    "figure",
    "competence",
)

CONFIDENCE_THRESHOLDS = {
    "niveau": 0.50,
    "record_type": 0.50,
    "type_information": 0.45,
    "figure": 0.45,
    "competence": 0.45,
}


class NLPModelError(RuntimeError):
    """Raised when a local NLP model cannot be loaded or used."""


def _model_path(target: str) -> Path:
    if target not in MODEL_TARGETS:
        raise ValueError(f"Cible NLP inconnue : {target}")
    return MODELS_DIR / f"tfidf_logreg_{target}.joblib"


@lru_cache(maxsize=len(MODEL_TARGETS))
def load_model(target: str) -> Any:
    path = _model_path(target)
    if not path.exists():
        raise NLPModelError(
            f"Modèle introuvable pour '{target}' : {path}. "
            "Exécutez d'abord l'installateur ou copiez les fichiers .joblib."
        )
    try:
        return joblib.load(path)
    except Exception as exc:  # pragma: no cover - defensive
        raise NLPModelError(f"Impossible de charger {path.name}: {exc}") from exc


def clear_model_cache() -> None:
    load_model.cache_clear()


def health_status() -> dict[str, Any]:
    models: dict[str, Any] = {}
    all_ready = True

    for target in MODEL_TARGETS:
        path = _model_path(target)
        ready = path.exists()
        models[target] = {
            "ready": ready,
            "path": str(path),
            "filename": path.name,
        }
        all_ready = all_ready and ready

    return {
        "status": "ready" if all_ready else "partial",
        "model_family": "TF-IDF + Logistic Regression",
        "models_dir": str(MODELS_DIR),
        "models": models,
    }


def predict_target(target: str, text: str) -> dict[str, Any]:
    clean_text = normalize_text(text)
    if not clean_text:
        raise ValueError("Le texte à analyser est vide.")

    model = load_model(target)

    try:
        prediction = str(model.predict([clean_text])[0])
        probabilities: dict[str, float] = {}
        confidence: float | None = None

        if hasattr(model, "predict_proba"):
            raw_probabilities = model.predict_proba([clean_text])[0]
            classes = [str(value) for value in model.classes_]
            probabilities = {
                label: float(score)
                for label, score in sorted(
                    zip(classes, raw_probabilities),
                    key=lambda item: item[1],
                    reverse=True,
                )
            }
            confidence = max(probabilities.values(), default=None)

        threshold = CONFIDENCE_THRESHOLDS.get(target, 0.50)
        return {
            "target": target,
            "prediction": prediction,
            "confidence": confidence,
            "threshold": threshold,
            "reliable": confidence is not None and confidence >= threshold,
            "probabilities": probabilities,
        }
    except Exception as exc:  # pragma: no cover - defensive
        raise NLPModelError(
            f"Erreur pendant la prédiction du modèle '{target}': {exc}"
        ) from exc


def analyze_unit(text: str) -> dict[str, Any]:
    clean_text = normalize_text(text)
    predictions: dict[str, Any] = {}
    unavailable: dict[str, str] = {}

    for target in MODEL_TARGETS:
        try:
            predictions[target] = predict_target(target, clean_text)
        except NLPModelError as exc:
            unavailable[target] = str(exc)

    return {
        "text": clean_text,
        "predictions": predictions,
        "unavailable_models": unavailable,
    }


def analyze_text(text: str, max_units: int = 30) -> dict[str, Any]:
    if not 1 <= max_units <= 100:
        raise ValueError("max_units doit être compris entre 1 et 100.")

    units = split_text_units(text, max_units=max_units)
    if not units:
        raise ValueError("Aucune unité textuelle exploitable n'a été détectée.")

    analyses = [analyze_unit(unit) for unit in units]

    distributions: dict[str, Counter[str]] = {
        target: Counter() for target in MODEL_TARGETS
    }
    confidences: dict[str, list[float]] = defaultdict(list)

    for analysis in analyses:
        for target, prediction in analysis["predictions"].items():
            distributions[target][prediction["prediction"]] += 1
            if prediction["confidence"] is not None:
                confidences[target].append(prediction["confidence"])

    summary: dict[str, Any] = {}
    for target in MODEL_TARGETS:
        distribution = distributions[target]
        dominant = distribution.most_common(1)[0][0] if distribution else None
        summary[target] = {
            "dominant_prediction": dominant,
            "distribution": dict(distribution),
            "average_confidence": (
                float(mean(confidences[target]))
                if confidences[target]
                else None
            ),
        }

    reliable_figures = [
        {
            "text": analysis["text"],
            "figure": analysis["predictions"]["figure"]["prediction"],
            "confidence": analysis["predictions"]["figure"]["confidence"],
        }
        for analysis in analyses
        if "figure" in analysis["predictions"]
        and analysis["predictions"]["figure"]["reliable"]
    ]

    return {
        "model": {
            "family": "TF-IDF + Logistic Regression",
            "ownership": "modèles entraînés sur le dataset EduMentor AI",
            "models_dir": str(MODELS_DIR),
        },
        "document": {
            "characters": len(normalize_text(text)),
            "units_analyzed": len(analyses),
            "max_units": max_units,
        },
        "summary": summary,
        "reliable_figure_detections": reliable_figures,
        "units": analyses,
        "warning": (
            "Les résultats restent des prédictions de prototype. "
            "Une confiance faible doit déclencher une validation humaine."
        ),
    }


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_text_units(text: str, max_units: int = 30) -> list[str]:
    raw_text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [
        normalize_text(value)
        for value in re.split(r"\n\s*\n+", raw_text)
        if normalize_text(value)
    ]

    units: list[str] = []
    seen: set[str] = set()

    for paragraph in paragraphs:
        candidates = [paragraph]
        if len(paragraph) > 700:
            candidates = [
                normalize_text(value)
                for value in re.split(r"(?<=[.!?])\s+", paragraph)
                if normalize_text(value)
            ]

        current = ""
        for candidate in candidates:
            if len(candidate) < 20:
                continue

            if len(candidate) <= 700:
                chunks = [candidate]
            else:
                chunks = [
                    candidate[index:index + 700]
                    for index in range(0, len(candidate), 700)
                ]

            for chunk in chunks:
                chunk = normalize_text(chunk)
                if not chunk or chunk in seen:
                    continue
                seen.add(chunk)
                units.append(chunk)
                if len(units) >= max_units:
                    return units

    if not units:
        clean = normalize_text(raw_text)
        if clean:
            units.append(clean[:700])

    return units[:max_units]
