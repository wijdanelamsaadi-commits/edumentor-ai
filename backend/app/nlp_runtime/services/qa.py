from __future__ import annotations

import hashlib
import re
from typing import Any

import numpy as np

from .registry import ModelRegistry


def _split_pipe(value: str) -> list[str]:
    return [part.strip() for part in str(value).split("|") if part.strip()]


def _sentence(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text)).strip()
    return re.split(r"(?<=[.!?])\s+", value)[0]


def _metadata(registry: ModelRegistry, unit_id: str) -> dict[str, Any]:
    try:
        return registry.chapter_index[unit_id]
    except KeyError as exc:
        raise ValueError(f"unit_id inconnu: {unit_id}") from exc


def _character(meta: dict[str, Any]) -> str:
    values = _split_pipe(meta["characters"])
    return values[0] if values else "le personnage principal"


def _place(meta: dict[str, Any]) -> str:
    values = _split_pipe(meta["places"])
    return values[0] if values else "le lieu principal"


def _themes(meta: dict[str, Any]) -> list[str]:
    values = _split_pipe(meta["themes"])
    return values or ["le thème principal"]


def _language_pair(meta: dict[str, Any], level: str) -> tuple[str, str, str]:
    character = _character(meta)
    selector = int(
        hashlib.sha256(
            f"{meta['unit_id']}::{level}".encode("utf-8")
        ).hexdigest()[:8],
        16,
    ) % 4

    if selector == 0:
        return (
            f"Mettez à la forme négative : « {character} accepte cette situation. »",
            f"{character} n’accepte pas cette situation.",
            "forme_negative",
        )
    if selector == 1:
        return (
            f"Transformez au discours indirect : {character} déclare : "
            "« Cet événement change ma situation. »",
            f"{character} déclare que cet événement change sa situation.",
            "discours_indirect",
        )
    if selector == 2:
        return (
            "Reliez par « parce que » : « Le personnage réagit. "
            "L’événement est grave. »",
            "Le personnage réagit parce que l’événement est grave.",
            "cause",
        )
    return (
        f"Transformez en question totale : « {character} comprend la situation. »",
        f"Est-ce que {character} comprend la situation ?",
        "question_totale",
    )


def generate_pair(
    registry: ModelRegistry,
    *,
    unit_id: str,
    task: str,
    level: str,
) -> dict[str, Any]:
    meta = _metadata(registry, unit_id)
    event = _sentence(meta["base_summary"])
    character = _character(meta)
    place = _place(meta)
    theme_values = _themes(meta)
    theme1 = theme_values[0]
    theme2 = theme_values[1] if len(theme_values) > 1 else "l’évolution du personnage"

    if task == "langue":
        question, correction, operation = _language_pair(meta, level)
        return {
            "unit_id": unit_id,
            "task": task,
            "level": level,
            "question": question,
            "correction": correction,
            "answer_elements": operation,
            "bareme": "2",
            "generation_mode": "grammar_rule",
            "requires_human_validation": True,
        }

    if task == "comprehension":
        if level == "debutant":
            question = (
                f"Quel est l’événement principal de « {meta['unit_title']} » "
                f"et quel personnage est directement concerné ?"
            )
            correction = (
                f"L’événement principal est le suivant : {event} "
                f"Le personnage le plus directement concerné est "
                f"{character}, dans le cadre de {place}."
            )
        elif level == "intermediaire":
            question = (
                f"Comment l’événement « {event.rstrip('.')} » "
                f"modifie-t-il la situation de {character} ?"
            )
            correction = (
                f"{event} Cet événement entraîne de nouvelles réactions, "
                f"modifie la situation de {character} et développe "
                f"le thème de {theme1}."
            )
        else:
            question = (
                f"Expliquez la fonction de « {meta['unit_title']} » "
                f"dans l’architecture générale de {meta['work_title']}."
            )
            correction = (
                f"L’unité fait progresser l’action à partir de "
                f"« {event.rstrip('.')} ». Elle éclaire le rôle de "
                f"{character}, renforce {theme1} et prépare la suite "
                f"de {meta['work_title']}."
            )
        answer_elements = "événement | personnage | conséquence | thème"
        bareme = "2"
    else:
        if level == "debutant":
            question = (
                f"Quel sentiment l’épisode « {meta['unit_title']} » "
                f"peut-il produire chez le lecteur ? Justifiez."
            )
            correction = (
                f"Une réponse cohérente peut retenir une émotion liée à "
                f"{theme1}. Elle doit être justifiée par le fait suivant : "
                f"{event}"
            )
        elif level == "intermediaire":
            question = (
                f"Expliquez comment « {meta['unit_title']} » met en "
                f"relation {theme1} et {theme2}."
            )
            correction = (
                f"L’épisode relie {theme1} à {theme2}. "
                f"{event} Cette relation influence les réactions de "
                f"{character} et la lecture du passage."
            )
        else:
            question = (
                f"Interprétez la portée symbolique ou argumentative "
                f"de « {meta['unit_title']} »."
            )
            correction = (
                f"L’unité dépasse l’événement raconté : en reliant "
                f"{theme1} à {theme2}, elle transforme l’expérience "
                f"de {character} en réflexion sur les valeurs et les "
                f"enjeux généraux de {meta['work_title']}."
            )
        answer_elements = "thème | preuve | interprétation"
        bareme = "3"

    return {
        "unit_id": unit_id,
        "task": task,
        "level": level,
        "question": question,
        "correction": correction,
        "answer_elements": answer_elements,
        "bareme": bareme,
        "generation_mode": f"structured_{task}",
        "requires_human_validation": True,
    }


def _retrieve(
    registry: ModelRegistry,
    question: str,
    task: str,
    level: str,
) -> dict[str, Any]:
    memory = registry.qa_memory
    indices = memory["groups"][(task, level)]
    query = memory["vectorizer"].transform([
        f"TASK={task} LEVEL={level} QUESTION={question}"
    ])
    similarities = (
        memory["matrix"][indices] @ query.T
    ).toarray().ravel()
    local = int(np.argmax(similarities))
    global_index = indices[local]
    row = memory["train_pairs"][global_index]
    return {
        "correction": row["correction"],
        "similarity": float(similarities[local]),
        "retrieved_pair_id": row["pair_id"],
    }


def correct_question(
    registry: ModelRegistry,
    *,
    question: str,
    task: str | None,
    level: str | None,
    unit_id: str = "",
    pair_id: str = "",
) -> dict[str, Any]:
    if pair_id:
        try:
            item = registry.exact_qa_memory[pair_id]
        except KeyError as exc:
            raise ValueError(
                "pair_id absent de la mémoire Train."
            ) from exc
        return {
            **item,
            "mode": "exact_train_pair",
            "requires_human_validation": True,
        }

    if task is None or level is None:
        raise ValueError("task et level sont obligatoires.")

    if unit_id:
        pair = generate_pair(
            registry,
            unit_id=unit_id,
            task=task,
            level=level,
        )
        pair["source_question"] = question
        pair["mode"] = "same_unit_structured_builder"
        return pair

    result = _retrieve(registry, question, task, level)
    return {
        **result,
        "mode": "task_level_retrieval_fallback",
        "requires_human_validation": True,
        "warning": (
            "Sans unit_id, vérifier les personnages, les lieux et les faits."
        ),
    }
