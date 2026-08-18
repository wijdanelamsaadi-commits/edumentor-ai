from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any


RAG_RELEVANCE_THRESHOLD = 0.58

OUT_OF_SCOPE_MESSAGE_FR = (
    "Je suis spécialisé dans la préparation au régional de français de 1ère Bac. "
    "Vous pouvez me poser une question sur les œuvres au programme, la langue, les figures de style, "
    "la méthodologie ou la production écrite."
)


WORK_ALIASES = {
    "la_boite_a_merveilles": (
        "boite a merveille",
        "boite a merveilles",
        "boite aux merveilles",
        "boite merveille",
        "boite merveilles",
        "la boite a merveille",
        "la boite a merveilles",
        "sidi mohamed",
        "si abdeslem",
        "lalla zoubida",
        "sefrioui",
        "ahmed sefrioui",
    ),
    "antigone": (
        "antigone",
        "antigonn",
        "creon",
        "ismene",
        "hemon",
        "jean anouilh",
        "anouilh",
    ),
    "dernier_jour_condamne": (
        "dernier jour condamne",
        "dernier jour d un condamne",
        "dernier jour du condamne",
        "le condamne",
        "condamne",
        "victor hugo",
        "hugo",
    ),
}

PEDAGOGICAL_INTENTS = {
    "comprehension",
    "langue",
    "grammaire",
    "conjugaison",
    "vocabulaire",
    "champ lexical",
    "discours direct",
    "discours direct et indirect",
    "discours indirect",
    "figure de style",
    "metaphore",
    "metafore",
    "comparaison",
    "personnification",
    "antithese",
    "hyperbole",
    "anaphore",
    "oxymore",
    "methode",
    "methodologie",
    "situer un passage",
    "bareme",
    "consigne",
    "production ecrite",
    "texte argumentatif",
    "redaction argumentative",
    "redaction",
    "rediger",
    "introduction",
    "conclusion",
    "corrige",
    "correction",
    "note ma reponse",
    "ma reponse",
    "exercice de langue",
    "exercice langue",
    "examen regional",
    "regional",
    "1ere bac",
    "premiere bac",
    "resume",
    "chapitre",
    "personnage",
    "personnages",
    "auteur",
    "genre",
    "theme",
    "evenement",
    "oeuvre",
    "passage",
}

STRONG_SINGLE_INTENTS = {
    "metaphore",
    "metafore",
    "comparaison",
    "personnification",
    "antithese",
    "hyperbole",
    "anaphore",
    "oxymore",
    "production ecrite",
    "texte argumentatif",
    "redaction argumentative",
    "redaction",
    "introduction",
    "exercice de langue",
    "exercice langue",
    "grammaire",
    "discours direct",
    "discours indirect",
    "corrige",
    "correction",
    "regional",
    "examen regional",
}

HARD_OUT_OF_SCOPE_TERMS = {
    "meteo",
    "temperature",
    "pluie demain",
    "capitale du japon",
    "capitale",
    "japon",
    "football",
    "match",
    "gagne le match",
    "voiture",
    "meilleure voiture",
    "reparer un ordinateur",
    "ordinateur",
    "programme python",
    "code python",
    "python",
    "recette",
    "cuisine",
    "musique",
    "chanson",
    "politique",
    "crypto",
    "bourse",
}

OLD_AI_TOPICS = {
    "machine learning",
    "deep learning",
    "prompt engineering",
    "overfitting",
    "underfitting",
    "backpropagation",
    "reinforcement learning",
    "diffusion model",
    "diffusion models",
    "intelligence artificielle",
    "artificial intelligence",
    "llm",
    "embedding",
    "chroma",
    "rag",
}


@dataclass(frozen=True)
class ScopeDecision:
    in_scope: bool
    reason: str
    detected_works: tuple[str, ...]
    detected_intents: tuple[str, ...]
    score: float
    rag_top_score: float | None = None
    threshold: float = RAG_RELEVANCE_THRESHOLD

    def as_dict(self) -> dict[str, Any]:
        return {
            "in_scope": self.in_scope,
            "reason": self.reason,
            "detected_works": list(self.detected_works),
            "detected_intents": list(self.detected_intents),
            "score": round(self.score, 4),
            "rag_top_score": None if self.rag_top_score is None else round(self.rag_top_score, 4),
            "threshold": self.threshold,
        }


def normalize_french_scope_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or "").lower())
    normalized = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
    normalized = normalized.replace("’", " ").replace("'", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    replacements = {
        "boites": "boite",
        "merveille ": "merveilles ",
        "oeuvres": "oeuvre",
        "œuvres": "oeuvre",
        "francais": "francais",
        "1er bac": "1ere bac",
        "premiere annee bac": "premiere bac",
    }
    padded = f" {normalized} "
    for source, target in replacements.items():
        padded = padded.replace(f" {source} ", f" {target} ")
    return padded.strip()


def detect_works(message: str) -> list[str]:
    normalized = normalize_french_scope_text(message)
    works: list[str] = []
    for work, aliases in WORK_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            works.append(work)
    return works


def detect_pedagogical_intents(message: str) -> list[str]:
    normalized = normalize_french_scope_text(message)
    return sorted({intent for intent in PEDAGOGICAL_INTENTS if intent in normalized})


def has_hard_out_of_scope_signal(message: str) -> bool:
    normalized = normalize_french_scope_text(message)
    return any(term in normalized for term in HARD_OUT_OF_SCOPE_TERMS | OLD_AI_TOPICS)


def classify_french_scope(
    message: str,
    rag_results: list[dict] | None = None,
    threshold: float = RAG_RELEVANCE_THRESHOLD,
) -> ScopeDecision:
    normalized = normalize_french_scope_text(message)
    works = detect_works(normalized)
    intents = detect_pedagogical_intents(normalized)
    hard_out = has_hard_out_of_scope_signal(normalized)
    rag_top_score = _top_rag_score(rag_results or [])

    if hard_out and not works and not intents:
        return ScopeDecision(False, "hard_out_of_scope_keyword", tuple(works), tuple(intents), 0.0, rag_top_score, threshold)

    score = 0.0
    if works:
        score += 0.58
    if intents:
        score += min(0.42, 0.14 * len(intents))
    if rag_top_score is not None and rag_top_score >= threshold:
        score += 0.22
    if hard_out:
        score -= 0.28

    if works or len(intents) >= 2 or any(intent in STRONG_SINGLE_INTENTS for intent in intents):
        return ScopeDecision(True, "work_or_strong_pedagogical_intent", tuple(works), tuple(intents), max(score, 0.65), rag_top_score, threshold)
    if intents and rag_top_score is not None and rag_top_score >= threshold:
        return ScopeDecision(True, "intent_confirmed_by_rag_score", tuple(works), tuple(intents), max(score, 0.6), rag_top_score, threshold)
    if rag_top_score is not None and rag_top_score >= threshold + 0.12 and _source_mentions_french_scope(rag_results or []):
        return ScopeDecision(True, "high_rag_score_with_french_source", tuple(works), tuple(intents), max(score, 0.6), rag_top_score, threshold)

    return ScopeDecision(False, "no_work_no_intent_or_low_rag_score", tuple(works), tuple(intents), max(score, 0.0), rag_top_score, threshold)


def _top_rag_score(results: list[dict]) -> float | None:
    scores: list[float] = []
    for result in results:
        try:
            scores.append(float(result.get("score", 0)))
        except (TypeError, ValueError):
            continue
    return max(scores) if scores else None


def _source_mentions_french_scope(results: list[dict]) -> bool:
    source_text = " ".join(
        str(result.get(key) or "")
        for result in results[:3]
        for key in ("file_name", "display_source", "course_title", "subject_name", "excerpt", "text_preview")
    )
    normalized = normalize_french_scope_text(source_text)
    return bool(detect_works(normalized) or any(term in normalized for term in ("francais", "regional", "1ere bac", "examen")))
