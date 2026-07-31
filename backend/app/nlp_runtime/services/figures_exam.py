from __future__ import annotations

import re
import unicodedata
from typing import Any

from .registry import ModelRegistry


INANIMATE_SUBJECTS = {
    "prison", "nuit", "peur", "mort", "silence", "ville", "palais",
    "souvenir", "temps", "espoir", "cellule", "foule", "boite",
    "memoire", "solitude", "justice", "loi", "ombre", "lumiere",
}
ANIMATE_VERBS = {
    "avale", "devore", "murmure", "sourit", "poursuit", "refuse",
    "observe", "frappe", "regarde", "marche", "parle", "pleure",
    "dort", "reveille", "crie", "etouffe", "menace", "appelle",
}
HYPERBOLE_MARKERS = [
    "mille", "million", "eternite", "monde entier", "ocean de",
    "infini", "cent mille", "un siecle",
]


def _normalize(text: str) -> str:
    value = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    ).lower()
    return re.sub(r"\s+", " ", value).strip()


def _repetition(value: str) -> bool:
    return bool(re.search(
        r"\b([a-z]{3,})\b(?:\s*[,;:!?-]\s*|\s+)\1\b",
        value,
    ))


def _accumulation(value: str) -> bool:
    if value.count(",") >= 3:
        return True
    item = r"(?:\b\w+\b(?:\s+\b\w+\b){0,2})"
    return bool(re.search(
        rf"{item}\s*,\s*{item}\s*,\s*{item}\s+(?:et|ou)\s+{item}",
        value,
    ))


def _comparison(value: str) -> bool:
    if re.match(r"^\s*comme\s+[^,]{2,45},", value):
        return False
    return bool(re.search(
        r"\bcomme\s+(?:un|une|le|la|les|des|l')\s+|"
        r"\btel(?:le|s|les)?\s+|"
        r"\bsemblable\s+a\b|\bpareil(?:le)?\s+a\b",
        value,
    ))


def _personification(value: str) -> bool:
    clause_starts = re.split(r"[.;:!?]+", value)
    for clause in clause_starts:
        clause = clause.strip()
        for subject in INANIMATE_SUBJECTS:
            for verb in ANIMATE_VERBS:
                if re.match(
                    rf"^(?:l'|le\s+|la\s+|les\s+|un\s+|une\s+|des\s+)?"
                    rf"{re.escape(subject)}\b"
                    rf"(?:\s+\w+){{0,3}}\s+\b{re.escape(verb)}\b",
                    clause,
                ):
                    return True
    return False


def _metaphor(value: str) -> bool:
    return bool(re.search(
        r"(?:la prison|la peur|la solitude|le temps|l'espoir|"
        r"la boite|antigone|le silence|la foule|la memoire|"
        r"la justice|la cellule|le palais)\s+"
        r"(?:est|devient|reste)\s+(?:un|une|le|la)\s+\w+",
        value,
    ))


def _figure_rule(text: str) -> str | None:
    value = _normalize(text)
    if _repetition(value):
        return "repetition"
    if _accumulation(value):
        return "accumulation"
    if _comparison(value):
        return "comparaison"
    if any(marker in value for marker in HYPERBOLE_MARKERS):
        return "hyperbole"
    if _personification(value):
        return "personnification"
    if _metaphor(value):
        return "metaphore"
    return None


def _enrich_figure(text: str) -> str:
    value = _normalize(text)
    rule = _figure_rule(text)
    tokens = [f"__COMMAS_{min(value.count(','), 4)}__"]
    if rule:
        tokens.append(f"__RULE_{rule.upper()}__")
    return text + " " + " ".join(tokens)


def analyze_figure(
    registry: ModelRegistry,
    text: str,
) -> dict[str, Any]:
    rule = _figure_rule(text)
    if rule:
        return {
            "contains_figure": True,
            "figure_type": rule,
            "mode": "linguistic_rule",
            "model_version": "v20",
            "requires_human_validation": True,
        }

    enriched = _enrich_figure(text)
    binary = str(
        registry.figure_binary_model.predict([enriched])[0]
    )
    if binary == "sans_figure":
        return {
            "contains_figure": False,
            "figure_type": None,
            "mode": "svm_fallback",
            "model_version": "v20",
            "requires_human_validation": True,
        }

    figure_type = str(
        registry.figure_type_model.predict([enriched])[0]
    )
    return {
        "contains_figure": True,
        "figure_type": figure_type,
        "mode": "svm_fallback",
        "model_version": "v20",
        "requires_human_validation": True,
    }


def _competence_rule(text: str) -> str | None:
    value = _normalize(text)
    rules = [
        ("reaction_personnelle", [
            r"\ba votre avis\b", r"\bpensez[- ]vous\b",
            r"\bapprouvez[- ]vous\b", r"\bselon vous\b",
            r"\bcomment jugez[- ]vous\b", r"\betes[- ]vous favorable\b",
            r"\bpartagez[- ]vous\b", r"\bdonnez votre point de vue\b",
        ]),
        ("production_ecrite", [
            r"\bredigez\b", r"\becrivez\b", r"\bimaginez\b",
            r"\bproduisez\b", r"\bcomposez\b",
            r"\btexte argumentatif\b", r"\bune lettre\b",
            r"\bun dialogue\b",
        ]),
        ("langue", [
            r"\btransformez\b", r"\bmettez\b", r"\bremplacez\b",
            r"\bcompletez\b", r"\bconjuguez\b",
            r"\bdiscours indirect\b", r"\bvoix passive\b",
            r"\btemps verbal\b", r"\bpronom\b",
        ]),
        ("analyse_stylistique", [
            r"\bfigure de style\b", r"\bprocede stylistique\b",
            r"\bchamp lexical\b", r"\bregistre\b",
            r"\bmetaphore\b", r"\bcomparaison\b",
            r"\bhyperbole\b", r"\brepetition\b",
            r"\beffet produit\b",
        ]),
        ("contextualisation", [
            r"\bsituez\b", r"\breplacez\b", r"\bcontexte\b",
            r"\bfaits anterieurs\b", r"\bce qui precede\b",
            r"\bmoment de l'intrigue\b",
            r"\bderoulement de l'oeuvre\b",
        ]),
        ("interpretation", [
            r"\bvaleur symbolique\b", r"\binterpretez\b",
            r"\bportee\b", r"\bsignification\b",
            r"\bquel sens\b", r"\bque revele\b",
            r"\bcomment comprendre\b", r"\blecture possible\b",
        ]),
        ("justification", [
            r"\bjustifiez\b", r"\bmontrez que\b",
            r"\bprouvez\b", r"\bappuyez\b",
            r"\brelevez un indice\b", r"\bdeux indices\b",
        ]),
    ]
    for label, patterns in rules:
        if any(re.search(pattern, value) for pattern in patterns):
            return label
    return None


def classify_exam_competence(
    registry: ModelRegistry,
    text: str,
) -> dict[str, Any]:
    rule = _competence_rule(text)
    if rule:
        return {
            "competence": rule,
            "mode": "linguistic_rule",
            "model_version": "v20",
            "requires_human_validation": True,
        }

    prediction = str(
        registry.exam_competence_model.predict([text])[0]
    )
    return {
        "competence": prediction,
        "mode": "svm_fallback",
        "model_version": "v20",
        "requires_human_validation": True,
    }
