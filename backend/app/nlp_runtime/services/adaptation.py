from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

import numpy as np

from .registry import ModelRegistry


STOPWORDS = set("""
le la les un une des du de d au aux et ou mais donc or ni car que
qui quoi dont où ce cet cette ces il elle ils elles on nous vous je
tu se sa son ses leur leurs dans sur sous avec sans pour par en à
est sont était étaient être avoir plus moins très aussi comme quand
lorsque puis encore entre vers chez ne pas
""".split())

REPLACEMENTS = {
    "néanmoins": "mais",
    "cependant": "mais",
    "toutefois": "mais",
    "par conséquent": "donc",
    "en outre": "aussi",
    "constitue": "est",
    "possède": "a",
    "afin de": "pour",
    "lorsque": "quand",
    "demeure": "reste",
    "met en évidence": "montre",
    "à la lumière de": "avec",
    "dans la mesure où": "parce que",
    "en raison de": "à cause de",
    "au sein de": "dans",
}

INTERMEDIATE_MARKERS = [
    (
        "Cet événement fait progresser l’action, car il modifie "
        "la situation des personnages et met en évidence le thème "
        "principal de l’unité."
    ),
    (
        "Le passage relie les faits racontés aux réactions des "
        "personnages et prépare la suite de l’œuvre."
    ),
    (
        "Cette évolution permet de comprendre les conséquences de "
        "l’événement sur les personnages et sur leur entourage."
    ),
]

ADVANCED_MARKERS = [
    (
        "Dans une lecture approfondie, cette progression possède une "
        "portée narrative et symbolique : elle relie l’expérience du "
        "personnage aux enjeux majeurs de l’œuvre."
    ),
    (
        "L’épisode dépasse ainsi l’action immédiate et ouvre une "
        "interprétation liée aux valeurs, aux tensions et au projet "
        "général de l’auteur."
    ),
    (
        "La construction du passage articule progression narrative, "
        "caractérisation et réflexion sur les thèmes centraux de l’œuvre."
    ),
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _entities(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(
        r"\b[A-ZÀÂÇÉÈÊËÎÏÔÛÙÜŸ][\wÀ-ÿ’'-]{2,}\b",
        text,
    )))


def _keywords(text: str, count: int = 2) -> list[str]:
    words = [
        word.strip("’'-").lower()
        for word in re.findall(r"\b[\wÀ-ÿ’'-]+\b", text)
    ]
    frequencies = Counter(
        word
        for word in words
        if len(word) > 4 and word not in STOPWORDS
    )
    return [word for word, _ in frequencies.most_common(count)]


def _simple_sentence(text: str, max_words: int = 14) -> str:
    value = _normalize(text)
    for source, target in REPLACEMENTS.items():
        value = re.sub(
            re.escape(source),
            target,
            value,
            flags=re.IGNORECASE,
        )
    value = re.sub(r"\([^)]*\)", "", value)
    words = re.findall(r"\b[\wÀ-ÿ’'-]+\b", value)
    if len(words) > max_words:
        clause = re.split(r"[,;:]", value)[0]
        value = clause if len(clause.split()) >= 6 else " ".join(words[:max_words])
    value = value.strip(" ,;:")
    if value and value[-1] not in ".!?":
        value += "."
    return value[0].upper() + value[1:] if value else value


def _marker(identifier: str, candidates: list[str]) -> str:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return candidates[int(digest[:8], 16) % len(candidates)]


def _operation(source_level: str, target_level: str) -> str:
    if source_level == target_level:
        return "no_change"
    if target_level == "debutant":
        return "simplification"
    if target_level == "intermediaire":
        return "complexification"
    return "approfondissement"


def _retrieve_style(
    registry: ModelRegistry,
    source_text: str,
    operation: str,
    content_type: str,
) -> dict[str, Any] | None:
    if operation == "no_change":
        return None

    memory = registry.adaptation_memory
    key = (operation, content_type)
    if key not in memory["groups"]:
        return None

    indices = memory["groups"][key]
    query = memory["vectorizer"].transform([source_text])
    similarities = (
        memory["matrix"][indices] @ query.T
    ).toarray().ravel()

    local_index = int(np.argmax(similarities))
    global_index = indices[local_index]
    row = memory["train_rows"][global_index]
    return {
        "similarity": float(similarities[local_index]),
        "adaptation_id": row["adaptation_id"],
        "style_example": row["target_text"],
    }


def adapt_text(
    registry: ModelRegistry,
    *,
    source_text: str,
    source_level: str,
    target_level: str,
    content_type: str,
    unit_title: str,
    adaptation_id: str,
) -> dict[str, Any]:
    source = _normalize(source_text)
    operation = _operation(source_level, target_level)

    if operation == "no_change":
        adapted = source
    elif operation == "simplification":
        first = re.split(r"(?<=[.!?])\s+", source)[0]
        if ":" in first and len(first.split(":", 1)[0]) < 45:
            first = first.split(":", 1)[1]
        parts = [
            f"Cette partie parle de « {unit_title} ».",
            _simple_sentence(first),
        ]
        entities = _entities(source)[:3]
        keywords = _keywords(source)
        if entities:
            parts.append("Les noms importants sont " + ", ".join(entities) + ".")
        if keywords:
            parts.append(f"L’idée principale concerne {keywords[0]}.")
        adapted = _normalize(" ".join(parts))
    elif operation == "complexification":
        # Preserve the original facts and add a moderate explanatory layer.
        simplified = _simple_sentence(source, max_words=26)
        adapted = _normalize(
            f"{simplified} {_marker(adaptation_id, INTERMEDIATE_MARKERS)}"
        )
    else:
        adapted = _normalize(
            f"{source} {_marker(adaptation_id, ADVANCED_MARKERS)}"
        )

    return {
        "adapted_text": adapted,
        "source_level": source_level,
        "target_level": target_level,
        "operation": operation,
        "content_type": content_type,
        "style_reference": _retrieve_style(
            registry,
            source,
            operation,
            content_type,
        ),
        "model_version": "v17",
        "requires_human_validation": True,
        "warning": (
            "La référence retrieval sert uniquement d'exemple de style; "
            "elle ne remplace jamais les faits du texte source."
        ),
    }
