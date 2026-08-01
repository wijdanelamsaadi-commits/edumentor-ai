from __future__ import annotations

import hashlib
import json
from typing import Any


def source_hash(sources: list[dict[str, Any]] | dict[str, Any] | None) -> str:
    payload = sources or []
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def truncate_sources(sources: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    remaining = max(0, int(max_chars))
    selected: list[dict[str, Any]] = []
    for source in sources:
        text = str(source.get("text") or source.get("content") or source.get("excerpt") or source.get("text_preview") or "")
        if not text or remaining <= 0:
            continue
        clipped = text[:remaining]
        remaining -= len(clipped)
        selected.append({**source, "text": clipped})
    return selected


def validate_source_ids(output: dict[str, Any], allowed_source_ids: set[str]) -> list[str]:
    unknown: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            ids = value.get("source_ids")
            if isinstance(ids, list):
                for source_id in ids:
                    if str(source_id) not in allowed_source_ids:
                        unknown.append(str(source_id))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(output)
    return sorted(set(unknown))

