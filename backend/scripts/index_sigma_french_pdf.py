from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal, init_db
from app.services.sigma_french_pdf_service import SIGMA_SOURCE_PDF, sync_sigma_french_pdf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Indexe le PDF Sigma Francais 1er Bac comme source RAG complementaire.")
    parser.add_argument("--pdf", default=str(SIGMA_SOURCE_PDF), help="Chemin du PDF Sigma.")
    parser.add_argument("--dry-run", action="store_true", help="Analyse sans ecrire dans la base ni ChromaDB.")
    parser.add_argument("--index", action="store_true", help="Ecrit les documents structures et les indexe dans ChromaDB.")
    parser.add_argument("--reset-sigma-only", action="store_true", help="Desactive uniquement les anciens documents Sigma avant reindexation.")
    parser.add_argument("--report", action="store_true", help="Ecrit le rapport SIGMA_PDF_REPORT.md lors d'une execution reelle.")
    args = parser.parse_args()
    if not args.dry_run and not args.index:
        parser.error("Choisissez --dry-run ou --index.")
    if args.reset_sigma_only and not args.index:
        parser.error("--reset-sigma-only doit etre utilise avec --index.")
    return args


def main() -> int:
    args = parse_args()
    init_db()
    with SessionLocal() as db:
        summary = sync_sigma_french_pdf(
            db,
            pdf_path=Path(args.pdf),
            dry_run=args.dry_run,
            reset_sigma_only=args.reset_sigma_only,
            index=args.index,
            write_report=args.report or args.index,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
