from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

TEXT_FIELDS = ("texte", "question", "terme", "description", "label")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON invalide à la ligne {line_number}: {exc}") from exc
    return records


def extract_text(record: dict[str, Any]) -> str:
    for field in TEXT_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def select_examples(
    records: Iterable[dict[str, Any]],
    target: str,
) -> tuple[list[str], list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []
    ids: list[str] = []
    for record in records:
        text = extract_text(record)
        label = record.get(target)
        if not text or label in (None, ""):
            continue
        texts.append(text)
        labels.append(str(label))
        ids.append(str(record.get("id", "")))
    return texts, labels, ids
