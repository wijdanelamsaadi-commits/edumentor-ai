from __future__ import annotations

import csv
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from app.services.ai_course_generation_service import adaptive_word_count


BENCHMARK_COLUMNS = [
    "Niveau",
    "Solution",
    "Modele",
    "Type d'execution",
    "Temps de generation",
    "Nombre d'appels",
    "JSON valide",
    "Resume mots",
    "Explication mots",
    "Support mots",
    "Key points",
    "Vocabulaire",
    "Sections completes",
    "Respect du niveau",
    "Qualite pedagogique",
    "Ressources necessaires",
    "Cout",
    "Points forts",
    "Limites",
    "Erreurs",
    "Choix recommande",
    "Justification",
]

LEVEL_THRESHOLDS = {
    "debutant": {
        "summary_words": 80,
        "explanation_words": 140,
        "learning_support_words": 80,
        "key_points_count": 4,
        "vocabulary_count": 4,
    },
    "intermediaire": {
        "summary_words": 110,
        "explanation_words": 200,
        "learning_support_words": 100,
        "key_points_count": 5,
        "vocabulary_count": 5,
    },
}


def ensure_results_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def benchmark_word_count(value: Any) -> int:
    if isinstance(value, dict):
        return adaptive_word_count(" ".join(str(item) for item in value.values()))
    if isinstance(value, list):
        return adaptive_word_count(" ".join(str(item) for item in value))
    return adaptive_word_count(value)


def has_five_sections(content: dict[str, Any] | None) -> bool:
    if not isinstance(content, dict):
        return False
    return all(
        [
            bool(str(content.get("summary") or "").strip()),
            bool(str(content.get("explanation") or "").strip()),
            bool(content.get("guided_example")),
            bool(content.get("practice_question")),
            bool(content.get("learning_support")),
        ]
    )


def level_thresholds(level: str) -> dict[str, int]:
    return LEVEL_THRESHOLDS.get(level, LEVEL_THRESHOLDS["intermediaire"])


def pedagogical_quality_scores(content: dict[str, Any] | None, *, level: str, status: str, errors: list[str]) -> dict[str, Any]:
    if status != "completed" or not isinstance(content, dict) or errors:
        return {
            "clarte": 0,
            "precision": 0,
            "adaptation_niveau": 0,
            "qualite_exemples": 0,
            "qualite_exercices": 0,
            "fidelite_source": 0,
            "qualite_generale": 0,
            "type": "heuristique",
        }
    summary_words = benchmark_word_count(content.get("summary"))
    explanation_words = benchmark_word_count(content.get("explanation"))
    support_words = benchmark_word_count(content.get("learning_support"))
    key_points = content.get("key_points") if isinstance(content.get("key_points"), list) else []
    vocabulary = content.get("vocabulary") if isinstance(content.get("vocabulary"), list) else []
    guided_example = content.get("guided_example") if isinstance(content.get("guided_example"), dict) else {}
    practice = content.get("practice_question") if isinstance(content.get("practice_question"), dict) else {}
    thresholds = level_thresholds(level)

    return {
        "clarte": min(5, 2 + int(summary_words >= thresholds["summary_words"]) + int(bool(key_points)) + int(bool(vocabulary))),
        "precision": min(5, 2 + int(explanation_words >= thresholds["explanation_words"]) + int(len(vocabulary) >= thresholds["vocabulary_count"]) + int(len(key_points) >= thresholds["key_points_count"])),
        "adaptation_niveau": min(5, 2 + int(level in json.dumps(content, ensure_ascii=False).lower()) + int(summary_words >= thresholds["summary_words"]) + int(explanation_words >= thresholds["explanation_words"])),
        "qualite_exemples": min(5, 1 + int(bool(guided_example.get("content"))) * 2 + int(benchmark_word_count(guided_example) >= 120) * 2),
        "qualite_exercices": min(5, 1 + int(bool(practice.get("question"))) + int(bool(practice.get("expected_answer"))) + int(bool(practice.get("explanation"))) + int(benchmark_word_count(practice) >= 120)),
        "fidelite_source": min(5, 3 + int(has_five_sections(content)) + int(not contains_placeholder_text(content))),
        "qualite_generale": 0,
        "type": "heuristique",
    } | {
        "qualite_generale": round(
            sum(
                [
                    min(5, 2 + int(summary_words >= thresholds["summary_words"]) + int(bool(key_points)) + int(bool(vocabulary))),
                    min(5, 2 + int(explanation_words >= thresholds["explanation_words"]) + int(len(vocabulary) >= thresholds["vocabulary_count"]) + int(len(key_points) >= thresholds["key_points_count"])),
                    min(5, 2 + int(level in json.dumps(content, ensure_ascii=False).lower()) + int(summary_words >= thresholds["summary_words"]) + int(explanation_words >= thresholds["explanation_words"])),
                    min(5, 1 + int(bool(guided_example.get("content"))) * 2 + int(benchmark_word_count(guided_example) >= 120) * 2),
                    min(5, 1 + int(bool(practice.get("question"))) + int(bool(practice.get("expected_answer"))) + int(bool(practice.get("explanation"))) + int(benchmark_word_count(practice) >= 120)),
                    min(5, 3 + int(has_five_sections(content)) + int(not contains_placeholder_text(content))),
                ]
            )
            / 6,
            2,
        )
    }


def contains_placeholder_text(content: dict[str, Any]) -> bool:
    text = json.dumps(content, ensure_ascii=False).lower()
    return any(marker in text for marker in ("lorem", "placeholder", "texte a completer", "contenu generique"))


def build_metrics(
    *,
    level: str = "intermediaire",
    solution: str,
    model: str,
    execution_type: str,
    status: str,
    duration_seconds: float,
    calls: int,
    http_statuses: list[int | str],
    json_valid: bool,
    repairs: int,
    content: dict[str, Any] | None,
    errors: list[str],
    resources: dict[str, Any],
    cost: str,
    strengths: list[str],
    limits: list[str],
) -> dict[str, Any]:
    content = content if isinstance(content, dict) else {}
    key_points = content.get("key_points") if isinstance(content.get("key_points"), list) else []
    vocabulary = content.get("vocabulary") if isinstance(content.get("vocabulary"), list) else []
    support_words = benchmark_word_count(content.get("learning_support"))
    thresholds = level_thresholds(level)
    quality = pedagogical_quality_scores(content, level=level, status=status, errors=errors)
    level_ok = bool(
        benchmark_word_count(content.get("summary")) >= thresholds["summary_words"]
        and benchmark_word_count(content.get("explanation")) >= thresholds["explanation_words"]
        and support_words >= thresholds["learning_support_words"]
        and len(key_points) >= thresholds["key_points_count"]
        and len(vocabulary) >= thresholds["vocabulary_count"]
        and has_five_sections(content)
    )
    return {
        "level": level,
        "solution": solution,
        "model": model,
        "execution_type": execution_type,
        "status": status,
        "duration_seconds": round(duration_seconds, 3),
        "calls": calls,
        "http_statuses": http_statuses,
        "json_valid": bool(json_valid),
        "repairs_required": repairs,
        "summary_words": benchmark_word_count(content.get("summary")),
        "explanation_words": benchmark_word_count(content.get("explanation")),
        "learning_support_words": support_words,
        "key_points_count": len(key_points),
        "vocabulary_count": len(vocabulary),
        "has_guided_example": bool(content.get("guided_example")),
        "has_practice_question": bool(content.get("practice_question")),
        "has_correction": bool((content.get("practice_question") or {}).get("explanation")) if isinstance(content.get("practice_question"), dict) else False,
        "has_five_sections": has_five_sections(content),
        "level_requirements_respected": level_ok,
        "intermediate_level_respected": level_ok,
        "source_coherence": "heuristique: sources fournies uniquement; validation humaine requise",
        "errors": errors,
        "resources": resources,
        "estimated_cost": cost,
        "direct_cost": "0 EUR de cout API pour local" if execution_type == "local" else "depend de la tarification Groq et des tokens utilises",
        "installation_ease": "simple si deja configure" if execution_type == "api" else ("indisponible: Ollama non installe" if status == "not_available" else "installation locale requise"),
        "integration_ease": "deja integre au backend" if execution_type == "api" else "integration possible via le provider Ollama existant",
        "strengths": strengths,
        "limits": limits,
        "pedagogical_quality": quality,
    }


def recommended_solution(metrics: list[dict[str, Any]]) -> tuple[str, str]:
    completed = [item for item in metrics if item.get("status") == "completed"]
    if not completed:
        return (
            "NOT_DETERMINED",
            "Aucune execution complete n'a permis de comparer objectivement la qualite; Groq ou Ollama doivent etre retestes quand les ressources sont disponibles.",
        )
    best = max(completed, key=lambda item: item.get("pedagogical_quality", {}).get("qualite_generale", 0))
    if best.get("solution") == "Groq":
        return (
            "Groq",
            "Groq est recommande par les mesures disponibles: sortie valide, meilleure qualite heuristique et integration deja operationnelle.",
        )
    return (
        "Ollama local",
        "Le modele local est recommande par les mesures disponibles: sortie valide sans cout API direct et qualite heuristique comparable.",
    )


def metric_to_row(metric: dict[str, Any], recommendation: str, justification: str) -> dict[str, Any]:
    quality = metric.get("pedagogical_quality") or {}
    return {
        "Niveau": metric.get("level"),
        "Solution": metric.get("solution"),
        "Modele": metric.get("model"),
        "Type d'execution": metric.get("execution_type"),
        "Temps de generation": metric.get("duration_seconds"),
        "Nombre d'appels": metric.get("calls"),
        "JSON valide": metric.get("json_valid"),
        "Resume mots": metric.get("summary_words"),
        "Explication mots": metric.get("explanation_words"),
        "Support mots": metric.get("learning_support_words"),
        "Key points": metric.get("key_points_count"),
        "Vocabulaire": metric.get("vocabulary_count"),
        "Sections completes": metric.get("has_five_sections"),
        "Respect du niveau": metric.get("level_requirements_respected"),
        "Qualite pedagogique": quality.get("qualite_generale"),
        "Ressources necessaires": json.dumps(metric.get("resources") or {}, ensure_ascii=False),
        "Cout": metric.get("estimated_cost"),
        "Points forts": "; ".join(metric.get("strengths") or []),
        "Limites": "; ".join(metric.get("limits") or []),
        "Erreurs": "; ".join(str(error) for error in metric.get("errors") or []),
        "Choix recommande": recommendation,
        "Justification": justification,
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BENCHMARK_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in BENCHMARK_COLUMNS})


def write_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    shared_strings: list[str] = []
    shared_index: dict[str, int] = {}

    def shared(value: Any) -> int:
        text = str(value if value is not None else "")
        if text not in shared_index:
            shared_index[text] = len(shared_strings)
            shared_strings.append(text)
        return shared_index[text]

    table = [BENCHMARK_COLUMNS] + [[row.get(column, "") for column in BENCHMARK_COLUMNS] for row in rows]
    sheet_rows = []
    for row_index, row in enumerate(table, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{column_name(col_index)}{row_index}"
            cells.append(f'<c r="{ref}" t="s"><v>{shared(value)}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        + "".join(f"<si><t>{escape(text)}</t></si>" for text in shared_strings)
        + "</sst>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Benchmark" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def sanitize_error(message: str) -> str:
    text = str(message or "")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"sk-[A-Za-z0-9_\-]+", "[REDACTED]", text)
    text = re.sub(r"organization `[^`]+`", "organization `[REDACTED]`", text)
    text = re.sub(r"org_[A-Za-z0-9_\-]+", "org_[REDACTED]", text)
    return text[:1000]


def timestamp() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"
