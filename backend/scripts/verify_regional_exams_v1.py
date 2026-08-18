from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from import_regional_exams_v1 import (  # noqa: E402
    DEFAULT_DATASET,
    get_session_factory,
    load_models,
    load_payloads,
    resolve_students,
    student_display,
    verify_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--student-id", type=int)
    parser.add_argument("--student-name", default="Malika")
    parser.add_argument("--all-students", action="store_true")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    models = load_models()
    payloads = load_payloads(args.dataset.resolve())
    SessionFactory = get_session_factory()
    db = SessionFactory()
    try:
        students = resolve_students(db, models["UserProfile"], args.student_id, args.student_name, args.all_students)
        result = verify_dataset(db, models, payloads, students)
        print("Élève(s):", ", ".join(f"{row.id}:{student_display(row)}" for row in students))
        print(f"Examens: {result['exams']}/{result['expected_exams']}")
        print(f"Questions: {result['questions']}/{result['expected_questions']}")
        print(f"Affectations: {result['assignments']}/{result['expected_assignments']}")
        if not result["ok"]:
            print("VÉRIFICATION ÉCHOUÉE")
            return 1
        print("VÉRIFICATION IMPORT RÉUSSIE")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
