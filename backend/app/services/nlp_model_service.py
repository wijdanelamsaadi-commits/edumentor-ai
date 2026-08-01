from __future__ import annotations

import os
import re
import json
import tempfile
from datetime import datetime
from hashlib import sha256
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

UNIFIED_INFORMATION_TYPES = {
    "personnage": {"personnage", "character", "characters"},
    "evenement": {"evenement", "evenement_cle", "event", "action", "intrigue"},
    "theme": {"theme", "thematique", "idee", "topic"},
    "lieu": {"lieu", "place", "setting", "espace"},
    "idee_essentielle": {"idee_essentielle", "idee principale", "main_idea", "resume", "summary"},
    "vocabulaire": {"vocabulaire", "lexique", "definition", "mot_cle", "keyword"},
    "figure_de_style": {"figure", "figure_de_style", "style", "metaphore", "comparaison"},
    "question_regionale": {"question_regionale", "question", "exam", "regional", "examen"},
}

FIGURE_NONE_LABELS = {"aucune", "none", "non", "pas_de_figure", "sans_figure", "no_figure"}


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
            f"ModÃ¨le introuvable pour '{target}' : {path}. "
            "ExÃ©cutez d'abord l'installateur ou copiez les fichiers .joblib."
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
        raise ValueError("Le texte Ã  analyser est vide.")

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
            f"Erreur pendant la prÃ©diction du modÃ¨le '{target}': {exc}"
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

    figure_prediction = predictions.get("figure") or {}
    figure_label = str(figure_prediction.get("prediction") or "").strip()
    figure_detected = bool(
        figure_label
        and normalize_label(figure_label) not in FIGURE_NONE_LABELS
        and figure_prediction.get("reliable")
    )
    information_prediction = predictions.get("type_information") or {}
    record_prediction = predictions.get("record_type") or {}
    primary_information_type = normalize_information_type(
        information_prediction.get("prediction"),
        fallback=record_prediction.get("prediction"),
    )
    confidence_values = [
        prediction.get("confidence")
        for prediction in predictions.values()
        if prediction.get("confidence") is not None
    ]
    reliable = bool(confidence_values) and all(
        prediction.get("reliable")
        for target, prediction in predictions.items()
        if target != "figure"
    )

    return {
        "text": clean_text,
        "predictions": predictions,
        "predicted_level": (predictions.get("niveau") or {}).get("prediction"),
        "predicted_record_type": record_prediction.get("prediction"),
        "predicted_information_type": information_prediction.get("prediction"),
        "primary_information_type": primary_information_type,
        "predicted_figure": figure_label if figure_detected else None,
        "figure_detected": figure_detected,
        "predicted_competence": (predictions.get("competence") or {}).get("prediction"),
        "confidence": min(confidence_values) if confidence_values else None,
        "reliable": reliable,
        "requires_human_validation": not reliable,
        "adaptation_suggestions": build_adaptation_suggestions(clean_text, predictions),
        "unavailable_models": unavailable,
    }


def analyze_text(text: str, max_units: int = 30) -> dict[str, Any]:
    if not 1 <= max_units <= 100:
        raise ValueError("max_units doit Ãªtre compris entre 1 et 100.")

    units = split_text_units(text, max_units=max_units)
    if not units:
        raise ValueError("Aucune unitÃ© textuelle exploitable n'a Ã©tÃ© dÃ©tectÃ©e.")

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
            "figure": analysis["predicted_figure"],
            "confidence": analysis["predictions"]["figure"]["confidence"],
        }
        for analysis in analyses
        if "figure" in analysis["predictions"]
        and analysis["figure_detected"]
    ]

    return {
        "model": {
            "family": "TF-IDF + Logistic Regression",
            "ownership": "modÃ¨les entraÃ®nÃ©s sur le dataset EduMentor AI",
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
            "Les rÃ©sultats restent des prÃ©dictions de prototype. "
            "Une confiance faible doit dÃ©clencher une validation humaine."
        ),
    }


def analyze_file_bytes(
    raw: bytes,
    filename: str,
    *,
    max_units: int = 60,
) -> dict[str, Any]:
    suffix = Path(filename or "uploaded_file").suffix.lower()
    if suffix == ".json":
        text = extract_json_text(raw)
        input_format = "json"
    elif suffix in {".tex", ".latex"}:
        text = extract_latex_text(raw)
        input_format = suffix.lstrip(".")
    elif suffix == ".pdf":
        text = extract_pdf_text(raw, suffix)
        input_format = "pdf"
    else:
        raise ValueError("Format non supporte. Utilisez JSON, LaTeX ou PDF.")

    result = analyze_text(text, max_units=max_units)
    return {
        "filename": filename,
        "input_format": input_format,
        "extracted_characters": len(text),
        **result,
    }


def extract_json_text(raw: bytes) -> str:
    payload = json.loads(raw.decode("utf-8-sig"))
    strings: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            clean = value.strip()
            if clean:
                strings.append(clean)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    text = "\n\n".join(strings)
    if not text.strip():
        raise ValueError("Le fichier JSON ne contient aucun texte exploitable.")
    return text


def extract_latex_text(raw: bytes) -> str:
    text = raw.decode("utf-8-sig")
    text = re.sub(r"(?<!\\)%.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(
        r"\\(?:part|chapter|section|subsection|subsubsection)\*?\{([^{}]*)\}",
        r"\n\n\1\n\n",
        text,
    )
    for _ in range(4):
        text = re.sub(
            r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}",
            r"\1",
            text,
        )
    text = re.sub(r"\\begin\{[^{}]+\}|\\end\{[^{}]+\}", " ", text)
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace(r"\%", "%").replace(r"\&", "&")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text.strip():
        raise ValueError("Le fichier LaTeX ne contient aucun texte exploitable.")
    return text.strip()


def extract_pdf_text(raw: bytes, suffix: str = ".pdf") -> str:
    from app.services.content_import_service import extract_pdf_pages

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_file.write(raw)
            temp_path = Path(temp_file.name)

        pages = extract_pdf_pages(temp_path)
        texts: list[str] = []
        for page in pages:
            if isinstance(page, str):
                value = page
            else:
                value = page.get("text") or page.get("content") or page.get("raw_text") or ""
            value = str(value).strip()
            if value:
                texts.append(value)
        text = "\n\n".join(texts)
        if not text.strip():
            raise ValueError(
                "Aucun texte n'a ete extrait du PDF. Verifiez le PDF ou la disponibilite de l'OCR."
            )
        return text
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_label(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def normalize_information_type(value: Any, fallback: Any = None) -> str | None:
    normalized = normalize_label(value)
    fallback_normalized = normalize_label(fallback)
    for target, aliases in UNIFIED_INFORMATION_TYPES.items():
        if normalized in aliases or any(alias in normalized for alias in aliases):
            return target
    for target, aliases in UNIFIED_INFORMATION_TYPES.items():
        if fallback_normalized in aliases or any(alias in fallback_normalized for alias in aliases):
            return target
    return normalized or fallback_normalized or None


def build_adaptation_suggestions(text: str, predictions: dict[str, Any]) -> dict[str, Any]:
    level = (predictions.get("niveau") or {}).get("prediction") or "Intermediaire"
    info_type = normalize_information_type(
        (predictions.get("type_information") or {}).get("prediction"),
        (predictions.get("record_type") or {}).get("prediction"),
    )
    short = text[:240].rstrip()
    return {
        "classification_role": "classification uniquement; la generation pedagogique reste separee",
        "level": level,
        "information_type": info_type,
        "debutant": f"Expliquer simplement l'idee suivante avec vocabulaire guide: {short}",
        "intermediaire": f"Structurer l'idee, demander une justification courte et relier au chapitre: {short}",
        "avance": f"Transformer l'idee en analyse argumentee avec nuance et methode d'examen: {short}",
    }


def hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


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

