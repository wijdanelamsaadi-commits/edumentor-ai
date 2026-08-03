from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persistence import (
    CourseAdaptation,
    CourseAdaptedSection,
    CourseLevelVariant,
    DiagnosticResult,
    PedagogicalPackageImportJob,
    UserProfile,
)
from app.nlp_runtime.services.adaptation import adapt_text as nlp_adapt_text
from app.nlp_runtime.services.content import predict_content_type
from app.nlp_runtime.services.level import predict_level
from app.nlp_runtime.services.registry import get_registry
from app.schemas.automatic_import import PedagogicalPackage
from app.services import automatic_course_generation_service as import_service
from app.services import diagnostic_question_generation_service, rag_document_service

LEVELS = ("debutant", "intermediaire", "avance")
MODE_TO_LEVEL = {
    "debutant": "debutant",
    "intermediaire": "intermediaire",
    "avance": "avance",
}
SECTION_TYPES = {
    "titre",
    "introduction",
    "definition",
    "explication",
    "exemple",
    "exercice",
    "question",
    "correction",
    "resume",
    "figure_de_style",
    "langue",
    "comprehension",
    "methodologie",
    "production_ecrite",
    "contenu_oeuvre",
    "autre",
}


def analyze_import(
    db: Session,
    professor: UserProfile,
    *,
    json_file: UploadFile,
    latex_file: UploadFile | None,
    classroom_id: int,
    subject_id: int | None = None,
    education_level_id: int | None = None,
    adaptation_mode: str = "automatic_class",
) -> dict:
    json_bytes = import_service.read_upload(json_file, ".json", import_service.MAX_JSON_SIZE, "JSON")
    latex_bytes = (
        import_service.read_upload(latex_file, {".tex", ".latex"}, import_service.MAX_LATEX_SIZE, "LaTeX")
        if latex_file
        else None
    )
    package = import_service.parse_package(json_bytes)
    latex_structure = import_service.parse_latex(latex_bytes.decode("utf-8")) if latex_bytes else {}
    import_service.validate_latex_references(package, latex_structure)

    classroom = import_service.get_owned_classroom(db, professor, classroom_id)
    json_hash = import_service.sha256(json_bytes)
    latex_hash = import_service.sha256(latex_bytes) if latex_bytes else None
    analysis = analyze_package_sections(package, latex_structure)
    class_level_summary = compute_class_level_summary(
        db,
        classroom.id,
        subject_id=subject_id,
        education_level_id=education_level_id,
    )

    existing_job = db.scalars(
        select(PedagogicalPackageImportJob).where(
            PedagogicalPackageImportJob.json_sha256 == json_hash,
            PedagogicalPackageImportJob.latex_sha256 == latex_hash,
            PedagogicalPackageImportJob.classroom_id == classroom.id,
            PedagogicalPackageImportJob.professor_id == professor.id,
            PedagogicalPackageImportJob.status.in_(("analyzing", "ready", "draft", "validated")),
        )
    ).first()
    job = existing_job or PedagogicalPackageImportJob(
        professor_id=professor.id,
        classroom_id=classroom.id,
        status="analyzing",
        schema_version=package.schema_version,
        json_filename=import_service.safe_filename(json_file.filename or "package.json"),
        latex_filename=import_service.safe_filename(latex_file.filename) if latex_file and latex_file.filename else None,
        json_sha256=json_hash,
        latex_sha256=latex_hash,
        generation_method="nlp_analysis",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.flush()

    subject = import_service.get_or_create_subject(db, package.course.subject)
    education_level = import_service.get_or_create_catalog(db, "education", package.course.education_level)
    job.subject_id = subject_id or subject.id
    job.education_level_id = education_level_id or education_level.id
    job.academic_year = package.target.academic_year
    job.status = "ready"
    job.chapters_count = len(package.chapters)
    job.variants_count = 0
    job.result_summary = {
        "step": "analysis_ready",
        "sections_count": analysis["sections_count"],
        "section_counts": analysis["section_counts"],
        "estimated_level": analysis["estimated_level"],
        "class_level_summary": class_level_summary,
        "warnings": analysis["warnings"],
        "adaptation_mode": adaptation_mode,
    }
    job.source_summary = {
        "workflow": "professor_nlp_adaptation",
        "mode": "json_latex" if latex_bytes else "json_only",
        "target": package.target.model_dump(mode="json"),
        "package": package.model_dump(mode="json"),
        "latex_structure": latex_structure,
        "course_title": package.course.title,
        "works": [{"title": work.title, "author": work.author} for work in package.works],
        "works_count": len(package.works),
        "chapters_count": len(package.chapters),
        "visuals_count": import_service.count_visual_specs(package),
        "regional_exams_count": import_service.count_regional_exam_items(package),
        "analysis": analysis,
        "class_level_summary": class_level_summary,
    }
    db.commit()
    db.refresh(job)
    return serialize_workflow_job(job)


def adapt_import(db: Session, professor: UserProfile, job_id: int, *, mode: str, target_levels: list[str]) -> dict:
    job = get_owned_workflow_job(db, professor, job_id)
    package, latex_structure = package_from_job(job)
    analysis = (job.source_summary or {}).get("analysis") or analyze_package_sections(package, latex_structure)
    class_summary = (job.source_summary or {}).get("class_level_summary") or {}
    levels = resolve_target_levels(mode, target_levels, class_summary)
    existing_by_level = {
        item.target_level: item
        for item in db.scalars(select(CourseAdaptation).where(CourseAdaptation.import_job_id == job.id))
    }

    adaptations: list[CourseAdaptation] = []
    for level in levels:
        adaptation = existing_by_level.get(level) or CourseAdaptation(
            import_job_id=job.id,
            classroom_id=job.classroom_id,
            target_level=level,
            created_by=professor.id,
        )
        adaptation.adaptation_mode = mode
        adaptation.original_content = build_original_preview(package, analysis)
        adaptation.analysis_summary = analysis
        adaptation.class_level_summary = class_summary
        adaptation.model_name = "EduMentor NLP local + regles pedagogiques"
        adaptation.model_version = "level:v13 content:v15/v16 adaptation:v17"
        adaptation.status = "draft"
        db.add(adaptation)
        db.flush()
        replace_adapted_sections(db, adaptation, package, analysis, level)
        db.flush()
        db.refresh(adaptation)
        adaptation.adapted_content = build_adapted_content(adaptation)
        adaptations.append(adaptation)

    job.status = "draft"
    job.variants_count = len(adaptations)
    job.result_summary = {
        **(job.result_summary or {}),
        "step": "adaptation_draft",
        "adapted_levels": levels,
        "adaptations": [serialize_adaptation(item, include_sections=False) for item in adaptations],
    }
    db.commit()
    return preview_import(db, professor, job_id)


def preview_import(db: Session, professor: UserProfile, job_id: int) -> dict:
    job = get_owned_workflow_job(db, professor, job_id)
    adaptations = list(
        db.scalars(
            select(CourseAdaptation)
            .where(CourseAdaptation.import_job_id == job.id)
            .order_by(CourseAdaptation.id)
        )
    )
    package, _ = package_from_job(job)
    return {
        **serialize_workflow_job(job),
        "original": build_original_preview(package, (job.source_summary or {}).get("analysis") or {}),
        "adaptations": [serialize_adaptation(item) for item in adaptations],
        "statistics": (job.result_summary or {}),
    }


def update_section(
    db: Session,
    professor: UserProfile,
    job_id: int,
    section_id: str,
    payload: dict,
) -> dict:
    job = get_owned_workflow_job(db, professor, job_id)
    section = db.scalars(
        select(CourseAdaptedSection)
        .join(CourseAdaptation)
        .where(
            CourseAdaptation.import_job_id == job.id,
            CourseAdaptedSection.section_id == section_id,
        )
    ).first()
    if section is None:
        raise HTTPException(status_code=404, detail="Section adaptee introuvable")
    if payload.get("adapted_content") is not None:
        section.adapted_content = str(payload["adapted_content"])
    if payload.get("section_type") is not None:
        section.section_type = normalize_section_type(str(payload["section_type"]))
    if payload.get("status") is not None:
        section.status = str(payload["status"])
    section.metadata_json = {
        **(section.metadata_json or {}),
        "manual_edit": True,
        "manual_edit_at": datetime.utcnow().isoformat(),
        "edited_by": professor.id,
    }
    section.adaptation.adapted_content = build_adapted_content(section.adaptation)
    section.adaptation.status = "draft"
    db.commit()
    return preview_import(db, professor, job_id)


def validate_import(db: Session, professor: UserProfile, job_id: int) -> dict:
    job = get_owned_workflow_job(db, professor, job_id)
    adaptations = list(db.scalars(select(CourseAdaptation).where(CourseAdaptation.import_job_id == job.id)))
    if not adaptations:
        raise HTTPException(status_code=422, detail="Aucune adaptation a valider")
    for adaptation in adaptations:
        adaptation.status = "validated"
        adaptation.validated_by = professor.id
        adaptation.validated_at = datetime.utcnow()
    job.status = "validated"
    job.result_summary = {**(job.result_summary or {}), "step": "validated"}
    db.commit()
    return preview_import(db, professor, job_id)


def publish_import(
    db: Session,
    professor: UserProfile,
    job_id: int,
    *,
    auto_assign: bool = True,
    adaptation_ids: list[int] | None = None,
) -> dict:
    job = get_owned_workflow_job(db, professor, job_id)
    if job.status not in {"validated", "published", "completed"}:
        raise HTTPException(status_code=422, detail="Validez les adaptations avant publication")
    if job.course_id:
        return serialize_workflow_job(job)

    package, latex_structure = package_from_job(job)
    classroom = import_service.get_owned_classroom(db, professor, job.classroom_id)
    subject = import_service.get_or_create_subject(db, package.course.subject)
    education_level = import_service.get_or_create_catalog(db, "education", package.course.education_level)
    difficulty_level = import_service.get_or_create_catalog(db, "difficulty", package.course.difficulty)
    course = import_service.create_course_from_package(db, professor, package, subject.id, education_level.id, difficulty_level.id)
    db.flush()
    job.course_id = course.id
    chapter_by_source = import_service.create_chapters_and_skills(db, course, package, latex_structure)
    import_service.create_literary_works(db, course, package)
    selected = load_validated_adaptations(db, job.id, adaptation_ids or [])
    persist_validated_course_variants(db, course, selected, package)

    quiz_questions_count = 0
    try:
        quiz_questions_count = import_service.create_quiz(db, course, package, chapter_by_source)
    except HTTPException as exc:
        course.information = {
            **(course.information or {}),
            "quiz_warning": str(exc.detail),
        }

    diagnostic_bank = diagnostic_question_generation_service.generate_bank_for_import(
        db=db,
        package=package,
        course=course,
        subject_id=subject.id,
        education_level_id=education_level.id,
        chapter_by_source=chapter_by_source,
        imported_package_hash=job.json_sha256,
        classroom_id=classroom.id,
        import_job_id=job.id,
        academic_year=package.target.academic_year,
        latex_structure=latex_structure,
    )
    obsolete_count = import_service.deactivate_previous_diagnostic_banks(
        db,
        job,
        subject.id,
        education_level.id,
        package.target.academic_year,
    )
    assessments = import_service.create_assessments(db, professor, classroom, course, package, subject.id, chapter_by_source)
    course_assignment_summary = import_service.assign_course_to_classroom(db, course.id, classroom, professor) if auto_assign else import_service.empty_course_assignment_summary()
    assigned_students = import_service.assign_assessments(db, assessments, classroom) if auto_assign else 0
    import_service.create_regional_profiles(db, package, classroom)

    for adaptation in selected:
        adaptation.status = "published"
        adaptation.source_course_id = course.id
        adaptation.published_at = datetime.utcnow()
    job.status = "completed"
    job.is_current = True
    job.completed_at = datetime.utcnow()
    job.chapters_count = import_service.count_course_chapters(db, course.id)
    job.variants_count = len(selected)
    job.questions_count = sum(len(assessment.questions) for assessment in assessments)
    job.assigned_students_count = assigned_students
    job.result_summary = {
        **(job.result_summary or {}),
        "step": "published",
        "course_id": course.id,
        "course_title": course.title,
        "chapters_count": job.chapters_count,
        "visuals_count": import_service.count_visual_specs(package),
        "regional_exams_count": import_service.count_regional_exam_items(package),
        "adapted_levels": [item.target_level for item in selected],
        "assessments_created": len(assessments),
        "assigned_students": assigned_students,
        "course_classroom_assignments": course_assignment_summary["course_classroom_assignments"],
        "students_with_course_access": course_assignment_summary["students_with_course_access"],
        "diagnostic_bank": diagnostic_bank,
        "obsolete_diagnostic_questions_deactivated": obsolete_count,
        "quiz_questions_count": quiz_questions_count,
    }
    db.commit()
    try:
        rag_document_service.request_course_reindex(db, course.id, professor)
        db.commit()
    except Exception:
        db.rollback()
    return serialize_workflow_job(job)


def get_owned_workflow_job(db: Session, professor: UserProfile, job_id: int) -> PedagogicalPackageImportJob:
    job = db.get(PedagogicalPackageImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import introuvable")
    if professor.role != "admin" and job.professor_id != professor.id:
        raise HTTPException(status_code=403, detail="Import non autorise")
    return job


def package_from_job(job: PedagogicalPackageImportJob) -> tuple[PedagogicalPackage, dict]:
    source = job.source_summary if isinstance(job.source_summary, dict) else {}
    package_payload = source.get("package")
    if not package_payload:
        raise HTTPException(status_code=422, detail="Le job ne contient pas le package source")
    return PedagogicalPackage.model_validate(package_payload), source.get("latex_structure") or {}


def analyze_package_sections(package: PedagogicalPackage, latex_structure: dict) -> dict:
    sections = extract_sections(package, latex_structure)
    warnings: list[str] = []
    try:
        registry = get_registry()
    except Exception as exc:
        registry = None
        warnings.append(f"Runtime NLP indisponible, heuristiques utilisees: {str(exc)[:160]}")

    analyzed = []
    levels: list[str] = []
    for section in sections:
        text = section["text"]
        content_type = heuristic_section_type(section)
        source_level = heuristic_level(text)
        model_versions: list[str] = []
        if registry is not None and text.strip():
            try:
                predicted_type = predict_content_type(registry, text=text, ui_section=section.get("title") or "")
                content_type = normalize_section_type(str(predicted_type.get("content_type") or content_type))
                model_versions.append(str(predicted_type.get("model_version") or "v15"))
            except Exception as exc:
                warnings.append(f"Classification heuristique pour {section['id']}: {str(exc)[:120]}")
            try:
                predicted_level = predict_level(registry, text)
                source_level = normalize_level(str(predicted_level.get("predicted_level") or source_level))
                model_versions.append(str(predicted_level.get("model_version") or "v13"))
            except Exception as exc:
                warnings.append(f"Niveau heuristique pour {section['id']}: {str(exc)[:120]}")
        levels.append(source_level)
        analyzed.append({
            **section,
            "section_type": content_type,
            "estimated_level": source_level,
            "model_versions": sorted(set(model_versions)) or ["heuristic"],
            "warnings": [],
        })

    section_counts = Counter(item["section_type"] for item in analyzed)
    level_counts = Counter(levels)
    estimated_level = level_counts.most_common(1)[0][0] if level_counts else "intermediaire"
    return {
        "sections": analyzed,
        "sections_count": len(analyzed),
        "section_counts": dict(section_counts),
        "estimated_level": estimated_level,
        "level_counts": dict(level_counts),
        "warnings": warnings,
    }


def extract_sections(package: PedagogicalPackage, latex_structure: dict) -> list[dict]:
    sections: list[dict] = []
    position = 1
    for chapter in sorted(package.chapters, key=lambda item: item.order):
        for block_index, block in enumerate(chapter.content_blocks, start=1):
            payload = block.model_dump()
            text = text_from_block(payload)
            if not text:
                continue
            source_block_id = payload.get("id") or f"{chapter.id}_block_{block_index}"
            sections.append({
                "id": f"{chapter.id}:{source_block_id}",
                "chapter_id": chapter.id,
                "chapter_title": chapter.title,
                "source_block_id": source_block_id,
                "position": position,
                "title": payload.get("title") or chapter.title,
                "original_type": payload.get("type") or "paragraph",
                "text": text,
                "metadata": payload.get("metadata") or {},
            })
            position += 1
        latex_blocks = latex_structure.get("sections", {}).get(import_service.normalize_ref(chapter.latex_reference or ""), [])
        for latex_index, latex_block in enumerate(latex_blocks, start=1):
            text = text_from_block(latex_block)
            if not text:
                continue
            sections.append({
                "id": f"{chapter.id}:latex_{latex_index}",
                "chapter_id": chapter.id,
                "chapter_title": chapter.title,
                "source_block_id": f"{chapter.id}_latex_{latex_index}",
                "position": position,
                "title": chapter.title,
                "original_type": latex_block.get("type") or "paragraph",
                "text": text,
                "metadata": {"source": "latex"},
            })
            position += 1
    return sections


def replace_adapted_sections(
    db: Session,
    adaptation: CourseAdaptation,
    package: PedagogicalPackage,
    analysis: dict,
    target_level: str,
) -> None:
    db.query(CourseAdaptedSection).filter(CourseAdaptedSection.adaptation_id == adaptation.id).delete()
    for section in analysis.get("sections", []):
        adapted = adapt_section(section, target_level)
        db.add(CourseAdaptedSection(
            adaptation_id=adaptation.id,
            section_id=section["id"],
            source_chapter_id=section.get("chapter_id"),
            source_block_id=section.get("source_block_id"),
            section_type=section.get("section_type") or "autre",
            source_level=section.get("estimated_level") or "intermediaire",
            target_level=target_level,
            original_content=section.get("text") or "",
            adapted_content=adapted["content"],
            metadata_json={
                "chapter_title": section.get("chapter_title"),
                "title": section.get("title"),
                "original_type": section.get("original_type"),
                "generation_method": adapted["generation_method"],
                "warnings": adapted.get("warnings") or [],
                "model_version": adapted.get("model_version"),
                "preservation": "Les faits, noms propres, citations et corrections officielles restent sous validation professeur.",
            },
            position=int(section.get("position") or 0),
            status="draft",
        ))


def adapt_section(section: dict, target_level: str) -> dict:
    source_text = section.get("text") or ""
    source_level = normalize_level(section.get("estimated_level") or "intermediaire")
    section_type = normalize_section_type(section.get("section_type") or section.get("original_type") or "autre")
    if not source_text.strip():
        return {"content": "", "generation_method": "empty_source", "warnings": ["Section vide"]}
    if is_protected_source(section):
        return {
            "content": source_text,
            "generation_method": "source_preserved",
            "model_version": "not_applicable",
            "warnings": ["Contenu officiel conserve sans transformation"],
        }
    try:
        registry = get_registry()
        data = nlp_adapt_text(
            registry,
            source_text=source_text,
            source_level=source_level,
            target_level=target_level,
            content_type=section_type,
            unit_title=section.get("chapter_title") or "chapitre",
            adaptation_id=f"{section.get('id')}:{target_level}",
        )
        return {
            "content": enrich_adapted_text(data["adapted_text"], source_text, section_type, target_level),
            "generation_method": "local_nlp_adaptation",
            "model_version": data.get("model_version", "v17"),
            "warnings": [data.get("warning")] if data.get("warning") else [],
        }
    except Exception as exc:
        return {
            "content": rule_based_adaptation(source_text, section_type, target_level),
            "generation_method": "pedagogical_rules_fallback",
            "model_version": "rules_v1",
            "warnings": [f"Adaptation generative locale indisponible: {str(exc)[:160]}"],
        }


def enrich_adapted_text(value: str, source_text: str, section_type: str, target_level: str) -> str:
    clean = normalize_spaces(value)
    if target_level == "debutant":
        return clean
    if target_level == "intermediaire":
        suffix = "Question guidee: expliquez l'idee principale avec une justification courte fondee sur le chapitre."
    else:
        suffix = "Approfondissement: reliez cette notion aux procedes, aux themes et a l'effet produit sur le lecteur."
    if section_type in {"exercice", "question"}:
        suffix = "Correction attendue: reponse justifiee avec un element precis du support et une phrase d'explication."
    return normalize_spaces(f"{clean} {suffix}")


def rule_based_adaptation(source_text: str, section_type: str, target_level: str) -> str:
    source = normalize_spaces(source_text)
    if target_level == "debutant":
        return normalize_spaces(
            f"Idee simple: {shorten(source, 260)} Aide: relevez d'abord les mots importants, puis reformulez avec vos propres mots."
        )
    if target_level == "avance":
        return normalize_spaces(
            f"Analyse avancee: {shorten(source, 420)} Travail attendu: interpretez, justifiez et reliez cette partie aux enjeux litteraires du chapitre."
        )
    return normalize_spaces(
        f"Explication intermediaire: {shorten(source, 340)} Activite: identifiez l'idee principale, donnez un exemple et justifiez en deux phrases."
    )


def compute_class_level_summary(
    db: Session,
    classroom_id: int,
    *,
    subject_id: int | None = None,
    education_level_id: int | None = None,
) -> dict:
    from app.models.persistence import ClassroomMembership

    memberships = list(db.scalars(select(ClassroomMembership).where(
        ClassroomMembership.classroom_id == classroom_id,
        ClassroomMembership.active.is_(True),
    )))
    counts = {"debutant": 0, "intermediaire": 0, "avance": 0, "non_evalue": 0}
    for membership in memberships:
        query = select(DiagnosticResult).where(DiagnosticResult.user_id == membership.student_id)
        if subject_id:
            query = query.where(DiagnosticResult.subject_id == subject_id)
        if education_level_id:
            query = query.where(DiagnosticResult.education_level_id == education_level_id)
        result = db.scalars(query.order_by(DiagnosticResult.created_at.desc()).limit(1)).first()
        if result is None:
            counts["non_evalue"] += 1
        else:
            counts[normalize_level(result.level)] += 1
    evaluated = sum(counts[level] for level in LEVELS)
    dominant = max(LEVELS, key=lambda level: counts[level]) if evaluated else "intermediaire"
    total = len(memberships) or 1
    return {
        **counts,
        "dominant_level": dominant,
        "total_students": len(memberships),
        "distribution": {key: round((value / total) * 100, 2) for key, value in counts.items()},
    }


def resolve_target_levels(mode: str, target_levels: list[str], class_summary: dict) -> list[str]:
    normalized_mode = normalize_level(mode)
    if mode == "automatic_class":
        return [normalize_level(class_summary.get("dominant_level") or "intermediaire")]
    if mode == "create_three_versions" or "three" in mode:
        return list(LEVELS)
    if target_levels:
        selected = [normalize_level(item) for item in target_levels if normalize_level(item) in LEVELS]
        return list(dict.fromkeys(selected)) or ["intermediaire"]
    return [MODE_TO_LEVEL.get(normalized_mode, "intermediaire")]


def persist_validated_course_variants(
    db: Session,
    course,
    adaptations: list[CourseAdaptation],
    package: PedagogicalPackage,
) -> None:
    source_hash = import_service.source_hash_for_package(package)
    for adaptation in adaptations:
        content = adaptation.adapted_content if isinstance(adaptation.adapted_content, dict) else {}
        existing = db.scalars(select(CourseLevelVariant).where(
            CourseLevelVariant.course_id == course.id,
            CourseLevelVariant.level == adaptation.target_level,
            CourseLevelVariant.source_hash == source_hash,
        )).first()
        if existing:
            existing.structured_content = content.get("chapters") or []
            existing.generation_method = "professor_validated_nlp"
            continue
        db.add(CourseLevelVariant(
            course=course,
            level=adaptation.target_level,
            title=f"{course.title} - {adaptation.target_level}",
            structured_content=content.get("chapters") or [],
            generation_method="professor_validated_nlp",
            source_hash=source_hash,
        ))


def load_validated_adaptations(db: Session, job_id: int, ids: list[int]) -> list[CourseAdaptation]:
    query = select(CourseAdaptation).where(
        CourseAdaptation.import_job_id == job_id,
        CourseAdaptation.status.in_(("validated", "published")),
    )
    if ids:
        query = query.where(CourseAdaptation.id.in_(ids))
    adaptations = list(db.scalars(query.order_by(CourseAdaptation.id)))
    if not adaptations:
        raise HTTPException(status_code=422, detail="Aucune version validee a publier")
    return adaptations


def build_original_preview(package: PedagogicalPackage, analysis: dict) -> dict:
    by_chapter: dict[str, dict] = {}
    for section in analysis.get("sections", []):
        chapter_id = section.get("chapter_id") or "chapter"
        chapter = by_chapter.setdefault(chapter_id, {
            "source_chapter_id": chapter_id,
            "title": section.get("chapter_title") or chapter_id,
            "blocks": [],
        })
        chapter["blocks"].append({
            "source_block_id": section.get("source_block_id"),
            "type": section.get("section_type") or section.get("original_type") or "autre",
            "title": section.get("title"),
            "content": section.get("text") or "",
            "source_level": section.get("estimated_level"),
            "generation_method": "source_original",
        })
    if by_chapter:
        chapters = list(by_chapter.values())
    else:
        chapters = [{"source_chapter_id": item.id, "title": item.title, "blocks": []} for item in package.chapters]
    return {
        "title": package.course.title,
        "summary": package.course.summary,
        "description": package.course.description,
        "chapters": chapters,
    }


def build_adapted_content(adaptation: CourseAdaptation) -> dict:
    chapters: dict[str, dict] = {}
    for section in sorted(adaptation.sections, key=lambda item: item.position):
        metadata = section.metadata_json or {}
        chapter_id = section.source_chapter_id or "chapter"
        chapter = chapters.setdefault(chapter_id, {
            "source_chapter_id": chapter_id,
            "title": metadata.get("chapter_title") or chapter_id,
            "blocks": [],
        })
        chapter["blocks"].append({
            "source_block_id": section.source_block_id,
            "source_chapter_id": section.source_chapter_id,
            "source_hash": import_service.sha256(section.original_content.encode("utf-8")),
            "original_block_type": metadata.get("original_type"),
            "level": section.target_level,
            "type": section.section_type,
            "title": metadata.get("title"),
            "content": section.adapted_content,
            "generation_method": metadata.get("generation_method") or "local_nlp_adaptation",
        })
    return {
        "level": adaptation.target_level,
        "generation_method": "professor_validated_nlp" if adaptation.status in {"validated", "published"} else "local_nlp_draft",
        "chapters": list(chapters.values()),
    }


def serialize_workflow_job(job: PedagogicalPackageImportJob) -> dict:
    result = job.result_summary if isinstance(job.result_summary, dict) else {}
    source = job.source_summary if isinstance(job.source_summary, dict) else {}
    return {
        "id": job.id,
        "status": job.status,
        "course_id": job.course_id,
        "classroom_id": job.classroom_id,
        "subject_id": job.subject_id,
        "education_level_id": job.education_level_id,
        "schema_version": job.schema_version,
        "source_summary": {
            key: value
            for key, value in source.items()
            if key not in {"package", "latex_structure"}
        },
        "result_summary": result,
        "chapters_count": job.chapters_count,
        "variants_count": job.variants_count,
        "questions_count": job.questions_count,
        "assigned_students_count": job.assigned_students_count,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def serialize_adaptation(adaptation: CourseAdaptation, include_sections: bool = True) -> dict:
    data = {
        "id": adaptation.id,
        "target_level": adaptation.target_level,
        "adaptation_mode": adaptation.adaptation_mode,
        "status": adaptation.status,
        "model_name": adaptation.model_name,
        "model_version": adaptation.model_version,
        "validated_at": adaptation.validated_at.isoformat() if adaptation.validated_at else None,
        "published_at": adaptation.published_at.isoformat() if adaptation.published_at else None,
        "adapted_content": adaptation.adapted_content,
        "sections_count": len(adaptation.sections),
    }
    if include_sections:
        data["sections"] = [
            {
                "id": section.section_id,
                "db_id": section.id,
                "source_chapter_id": section.source_chapter_id,
                "source_block_id": section.source_block_id,
                "section_type": section.section_type,
                "source_level": section.source_level,
                "target_level": section.target_level,
                "original_content": section.original_content,
                "adapted_content": section.adapted_content,
                "metadata": section.metadata_json or {},
                "position": section.position,
                "status": section.status,
            }
            for section in adaptation.sections
        ]
    return data


def text_from_block(block: dict) -> str:
    parts: list[str] = []
    for key in ("title", "content", "question", "solution", "answer", "explanation"):
        value = block.get(key)
        if value:
            parts.append(str(value))
    items = block.get("items")
    if isinstance(items, list):
        parts.extend(str(item) for item in items if str(item).strip())
    choices = block.get("choices")
    if isinstance(choices, list):
        parts.extend(str(item) for item in choices if str(item).strip())
    return normalize_spaces(" ".join(parts))


def heuristic_section_type(section: dict) -> str:
    raw = normalize_spaces(f"{section.get('original_type', '')} {section.get('title', '')} {section.get('text', '')}").lower()
    if "correction" in raw or "solution" in raw:
        return "correction"
    if "exercice" in raw:
        return "exercice"
    if "question" in raw or raw.endswith("?"):
        return "question"
    if "definition" in raw or "definir" in raw:
        return "definition"
    if "resume" in raw:
        return "resume"
    if "methode" in raw or "methodologie" in raw:
        return "methodologie"
    if "figure" in raw or "metaphore" in raw or "comparaison" in raw:
        return "figure_de_style"
    if "exemple" in raw:
        return "exemple"
    if "introduction" in raw:
        return "introduction"
    return "explication"


def heuristic_level(text: str) -> str:
    words = re.findall(r"\w+", text)
    if len(words) < 35:
        return "debutant"
    average = sum(len(word) for word in words) / max(len(words), 1)
    if len(words) > 120 or average > 6.4:
        return "avance"
    return "intermediaire"


def normalize_section_type(value: str) -> str:
    key = normalize_ascii(value).replace("-", "_")
    mapping = {
        "definition": "definition",
        "definitions": "definition",
        "example": "exemple",
        "examples": "exemple",
        "exercise": "exercice",
        "solution": "correction",
        "summary": "resume",
        "methodology": "methodologie",
        "production_ecrite": "production_ecrite",
        "written_production": "production_ecrite",
        "work_content": "contenu_oeuvre",
        "oeuvre": "contenu_oeuvre",
        "language": "langue",
        "comprehension": "comprehension",
    }
    normalized = mapping.get(key, key)
    return normalized if normalized in SECTION_TYPES else "autre"


def normalize_level(value: Any) -> str:
    key = normalize_ascii(str(value or "")).replace("-", "_")
    if key in {"debutant", "beginner", "facile"}:
        return "debutant"
    if key in {"avance", "advanced", "difficile"}:
        return "avance"
    return "intermediaire"


def normalize_ascii(value: str) -> str:
    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "à": "a",
        "â": "a",
        "ù": "u",
        "û": "u",
        "ô": "o",
        "î": "i",
        "ï": "i",
        "ç": "c",
        "œ": "oe",
    }
    text = value.lower()
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_")


def is_protected_source(section: dict) -> bool:
    metadata = section.get("metadata") if isinstance(section.get("metadata"), dict) else {}
    text = normalize_ascii(" ".join(str(value) for value in [
        section.get("original_type"),
        section.get("title"),
        metadata.get("correction_status"),
        metadata.get("status"),
        metadata.get("source"),
    ] if value))
    return any(token in text for token in ("official", "officiel", "bareme", "regional_exam", "examen_regional"))


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def shorten(value: str, limit: int) -> str:
    clean = normalize_spaces(value)
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "."
