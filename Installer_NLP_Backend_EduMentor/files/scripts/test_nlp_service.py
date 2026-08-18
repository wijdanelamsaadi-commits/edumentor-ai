from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.nlp_model_service import analyze_text, health_status  # noqa: E402


def main() -> None:
    print("=== Santé des modèles ===")
    print(json.dumps(health_status(), ensure_ascii=False, indent=2))

    sample = (
        "Sidi Mohammed est un enfant de six ans qui vit à Dar Chouafa.\n\n"
        "La boîte est un royaume merveilleux pour l'enfant.\n\n"
        "Expliquez le rôle symbolique de la boîte à merveilles."
    )

    print("\n=== Analyse de démonstration ===")
    print(json.dumps(analyze_text(sample, max_units=10), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
