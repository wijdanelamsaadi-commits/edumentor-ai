from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal, init_db
from app.services.french_regional_corpus_service import sync_french_regional_corpus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Indexe le corpus RAG francais 1ere Bac Maroc.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare le corpus et affiche le resume sans ecrire ni indexer.")
    parser.add_argument("--reset-french-only", action="store_true", help="Supprime uniquement les vecteurs du corpus francais avant reindexation.")
    parser.add_argument("--no-index", action="store_true", help="Ecrit les documents sans envoyer les chunks a ChromaDB.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()
    with SessionLocal() as db:
        summary = sync_french_regional_corpus(
            db,
            dry_run=args.dry_run,
            reset_french_only=args.reset_french_only,
            index=not args.no_index,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
