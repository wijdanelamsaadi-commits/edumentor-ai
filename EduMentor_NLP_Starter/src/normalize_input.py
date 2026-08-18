from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader


def clean_latex(text: str) -> str:
    text = re.sub(r"%.*", " ", text)
    text = re.sub(r"\\(section|subsection|chapter|title)\*?\{([^}]*)\}", r"\2\n", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?(\[[^]]*\])?(\{[^}]*\})?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(page for page in pages if page)
    if not text.strip():
        raise ValueError("Aucun texte détecté. Le PDF est peut-être scanné et nécessite un OCR.")
    return text


def normalize(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            source_text = obj.get("contenu_source") or obj.get("texte") or json.dumps(obj, ensure_ascii=False)
        else:
            source_text = json.dumps(obj, ensure_ascii=False)
    elif suffix in {".tex", ".latex"}:
        source_text = clean_latex(path.read_text(encoding="utf-8"))
    elif suffix == ".pdf":
        source_text = extract_pdf(path)
    else:
        raise ValueError("Format non pris en charge. Formats acceptés : JSON, LaTeX et PDF textuel.")

    return {
        "source_file": path.name,
        "source_format": suffix.lstrip("."),
        "roman": None,
        "chapitre": None,
        "titre": None,
        "contenu_source": source_text,
        "validation_status": "a_annoter",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalise un fichier JSON, LaTeX ou PDF vers JSON.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = normalize(Path(args.input))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
