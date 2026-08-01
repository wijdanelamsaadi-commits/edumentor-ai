from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.models.persistence import DiagnosticQuestion, PedagogicalPackageImportJob  # noqa: E402

OBSOLETE_MARKERS = ("Le Voyage de Samir", "oeuvre_demo", "ancien package fictif")


def main() -> None:
    with SessionLocal() as db:
        questions = db.query(DiagnosticQuestion).filter(DiagnosticQuestion.generation_method.in_(["deterministic_fallback", "automatic_import"])).all()
        deactivated = 0
        obsolete_job_ids: set[int] = set()
        obsolete_course_hash_pairs: set[tuple[int | None, str | None]] = set()
        for question in questions:
            snapshot_text = json.dumps(question.source_snapshot or {}, ensure_ascii=False)
            provenance = " ".join([
                snapshot_text,
                question.question or "",
                question.explanation or "",
            ])
            if any(marker.lower() in provenance.lower() for marker in OBSOLETE_MARKERS):
                if question.import_job_id:
                    obsolete_job_ids.add(question.import_job_id)
                obsolete_course_hash_pairs.add((question.source_course_id, question.imported_package_hash))
                if question.active:
                    question.active = False
                    deactivated += 1
        for job_id in obsolete_job_ids:
            job = db.get(PedagogicalPackageImportJob, job_id)
            if job:
                job.is_current = False
        for course_id, package_hash in obsolete_course_hash_pairs:
            if course_id is None or package_hash is None:
                continue
            job = db.query(PedagogicalPackageImportJob).filter_by(course_id=course_id, json_sha256=package_hash).first()
            if job:
                job.is_current = False
                obsolete_job_ids.add(job.id)
        if obsolete_job_ids:
            changed = db.query(DiagnosticQuestion).filter(
                DiagnosticQuestion.import_job_id.in_(list(obsolete_job_ids)),
                DiagnosticQuestion.active.is_(True),
            ).update({DiagnosticQuestion.active: False}, synchronize_session=False)
            deactivated += int(changed or 0)
        db.commit()
        print(f"Questions obsoletes desactivees: {deactivated}")


if __name__ == "__main__":
    main()
