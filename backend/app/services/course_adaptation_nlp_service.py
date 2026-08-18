from __future__ import annotations

import json
import logging
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
logger = logging.getLogger(__name__)
MODE_TO_LEVEL = {
    "debutant": "debutant",
    "intermediaire": "intermediaire",
    "avance": "avance",
}
SECTION_TYPES = {
    "title",
    "introduction",
    "definition",
    "explanation",
    "example",
    "exercise",
    "question",
    "correction",
    "summary",
    "figure_de_style",
    "language",
    "comprehension",
    "methodology",
    "written_production",
    "work_content",
    "literary_passage",
    "narrative_analysis",
    "other",
}
EXPLICIT_JSON_TYPES = {"definition", "example", "methodology", "exercise", "summary"}
NARRATIVE_FORBIDDEN_PATTERNS = (
    "progression narrative",
    "personnages",
    "suite de l'oeuvre",
    "suite de l’œuvre",
    "projet general de l'auteur",
    "projet général de l’auteur",
    "cet evenement fait progresser l'action",
    "cet événement fait progresser l’action",
    "reactions des personnages",
    "réactions des personnages",
    "prepare la suite",
    "prépare la suite",
    "enjeux majeurs de l'oeuvre",
    "enjeux majeurs de l’œuvre",
    "themes centraux de l'oeuvre",
    "thèmes centraux de l’œuvre",
)
WEAK_INDICATORS = {"la", "le", "l", "un", "une", "les", "des", "du", "de"}
FIGURE_PROFILES = {
    "comparaison": {
        "example": "Il est courageux comme un lion",
        "indicator": "comme",
        "indicator_label": "outil de comparaison",
        "near_concept": "la metaphore",
        "advanced_distinction": "la comparaison utilise un outil comme \"comme\", alors que la metaphore rapproche directement deux elements sans outil.",
    },
    "metaphore": {
        "example": "Cet homme est un lion",
        "indicator": "rapprochement direct sans outil",
        "indicator_label": "rapprochement direct",
        "near_concept": "la comparaison",
        "advanced_distinction": "la metaphore supprime l'outil de comparaison et presente le rapprochement comme une identite directe.",
    },
    "personnification": {
        "example": "La djellaba dormait au fond du coffre",
        "indicator": "dormait",
        "indicator_label": "verbe ou comportement humain",
        "near_concept": "la metaphore",
        "advanced_distinction": "la personnification attribue un comportement humain, tandis que la metaphore etablit surtout un rapprochement d'images.",
    },
    "antithese": {
        "example": "Il sourit malgre sa profonde tristesse",
        "indicator": "sourit / tristesse",
        "indicator_label": "mots ou idees opposes",
        "near_concept": "l'oxymore",
        "advanced_distinction": "l'antithese oppose deux idees dans une phrase ou un passage, alors que l'oxymore rapproche deux mots contradictoires.",
    },
    "hyperbole": {
        "example": "Je t'ai appele mille fois",
        "indicator": "mille fois",
        "indicator_label": "expression exageree",
        "near_concept": "une exageration non stylistique",
        "advanced_distinction": "l'hyperbole vise un effet expressif; une exageration ordinaire amplifie sans intention stylistique forte.",
    },
    "anaphore": {
        "example": "Toujours aimer, toujours apprendre, toujours avancer",
        "indicator": "toujours",
        "indicator_label": "element repete",
        "near_concept": "une repetition placee ailleurs dans la phrase",
        "advanced_distinction": "l'anaphore repete le meme element au debut de groupes successifs, contrairement a une repetition dispersee.",
    },
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
    validation_errors = validate_adaptations_before_professor_validation(adaptations)
    if validation_errors:
        raise HTTPException(status_code=422, detail=validation_errors)
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
    chapter_examples = collect_examples_by_chapter(sections)
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
        explicit_type = normalize_section_type(section.get("original_type") or "")
        has_explicit_json_type = explicit_type in EXPLICIT_JSON_TYPES and not section.get("metadata", {}).get("source") == "latex"
        content_type = explicit_type if has_explicit_json_type else heuristic_section_type(section)
        type_source = "explicit_json" if has_explicit_json_type else "heuristic_fallback"
        type_confidence = 1.0 if has_explicit_json_type else 0.55
        source_level = heuristic_level(text)
        model_versions: list[str] = []
        if registry is not None and text.strip() and not has_explicit_json_type:
            try:
                predicted_type = predict_content_type(registry, text=text, ui_section=section.get("title") or "")
                content_type = normalize_section_type(str(predicted_type.get("content_type") or content_type))
                type_source = "nlp_model" if content_type != "other" else "heuristic_fallback"
                type_confidence = 0.75 if type_source == "nlp_model" else 0.45
                model_versions.append(str(predicted_type.get("model_version") or "v15"))
            except Exception as exc:
                warnings.append(f"Classification heuristique pour {section['id']}: {str(exc)[:120]}")
        if registry is not None and text.strip():
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
            "detected_type": content_type,
            "type_source": type_source,
            "type_confidence": type_confidence,
            "related_example": find_related_example(section, chapter_examples),
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
                "raw_block": payload,
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
                "raw_block": latex_block,
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
            section_type=section.get("section_type") or "other",
            source_level=section.get("estimated_level") or "intermediaire",
            target_level=target_level,
            original_content=section.get("text") or "",
            adapted_content=adapted["content"],
            metadata_json={
                "chapter_title": section.get("chapter_title"),
                "title": section.get("title"),
                "original_type": section.get("original_type"),
                "detected_type": section.get("detected_type"),
                "type_source": section.get("type_source"),
                "type_confidence": section.get("type_confidence"),
                "generation_method": adapted["generation_method"],
                "adaptation_method": adapted["generation_method"],
                "nlp_model_version": adapted.get("model_version"),
                "generator_provider": adapted.get("generator_provider") or "local_nlp",
                "fallback_used": adapted.get("fallback_used", False),
                "fallback_reason": adapted.get("fallback_reason"),
                "adapted_payload": adapted.get("payload") or {},
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
    section_type = normalize_section_type(section.get("section_type") or section.get("original_type") or "other")
    if not source_text.strip():
        return {"content": "", "generation_method": "empty_source", "warnings": ["Section vide"], "payload": {}}
    if is_protected_source(section):
        return {
            "content": source_text,
            "generation_method": "source_preserved",
            "model_version": "not_applicable",
            "warnings": ["Contenu officiel conserve sans transformation"],
            "payload": structured_payload_from_section(section, source_text),
            "generator_provider": "none",
            "fallback_used": False,
            "fallback_reason": "",
        }

    if section_type in {"definition", "example", "methodology", "exercise", "summary"}:
        adapted = type_aware_adaptation(section, section_type, target_level)
        logger.info(
            "course_adaptation_nlp section=%s type=%s level=%s adaptation_method=%s nlp_model_version=%s generator_provider=%s fallback_used=%s fallback_reason=%s",
            section.get("id"),
            section_type,
            target_level,
            adapted.get("generation_method"),
            "/".join(section.get("model_versions") or []),
            "none",
            False,
            "",
        )
        return adapted

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
            "payload": structured_payload_from_section(section, data["adapted_text"]),
            "generator_provider": "local_nlp",
            "fallback_used": False,
            "fallback_reason": "",
        }
    except Exception as exc:
        fallback_content = rule_based_adaptation(source_text, section_type, target_level)
        logger.warning(
            "course_adaptation_nlp section=%s type=%s level=%s adaptation_method=pedagogical_rules_fallback nlp_model_version=rules_v1 generator_provider=local_nlp fallback_used=%s fallback_reason=%s",
            section.get("id"),
            section_type,
            target_level,
            True,
            str(exc)[:160],
        )
        return {
            "content": fallback_content,
            "generation_method": "pedagogical_rules_fallback",
            "model_version": "rules_v1",
            "warnings": [f"Adaptation generative locale indisponible: {str(exc)[:160]}"],
            "payload": structured_payload_from_section(section, fallback_content),
            "generator_provider": "local_nlp",
            "fallback_used": True,
            "fallback_reason": str(exc)[:160],
        }


def enrich_adapted_text(value: str, source_text: str, section_type: str, target_level: str) -> str:
    clean = normalize_spaces(value)
    if target_level == "debutant":
        return clean
    if target_level == "intermediaire":
        suffix = "Question guidee: expliquez l'idee principale avec une justification courte fondee sur le chapitre."
    else:
        suffix = "Approfondissement: reliez cette notion aux procedes, aux themes et a l'effet produit sur le lecteur."
    if section_type in {"exercise", "question"}:
        suffix = "Correction attendue: reponse justifiee avec un element precis du support et une phrase d'explication."
    return normalize_spaces(f"{clean} {suffix}")


def type_aware_adaptation(section: dict, section_type: str, target_level: str) -> dict:
    raw = section.get("raw_block") if isinstance(section.get("raw_block"), dict) else {}
    source_text = normalize_spaces(section.get("text") or "")
    title = raw.get("title") or section.get("title") or label_for_type(section_type)
    payload = structured_payload_from_section(section, source_text)
    payload["title"] = title
    payload["type"] = section_type
    payload["level"] = target_level

    if section_type == "definition":
        payload = adapt_definition_payload(section, target_level)
        content = payload["content"]
    elif section_type == "example":
        content = adapt_example(source_text, target_level)
        payload["content"] = content
        payload["example"] = raw.get("content") or raw.get("question") or source_text
    elif section_type == "methodology":
        payload = adapt_methodology_payload(section, target_level)
        content = text_from_structured_payload(payload)
    elif section_type == "exercise":
        payload = adapt_exercise_payload(section, target_level)
        content = text_from_structured_payload(payload)
    elif section_type == "summary":
        payload = adapt_summary_payload(section, target_level)
        content = text_from_structured_payload(payload)
    else:
        content = rule_based_adaptation(source_text, section_type, target_level)
        payload["content"] = content

    content = remove_forbidden_narrative_templates(content)
    payload["content"] = remove_forbidden_narrative_templates(str(payload.get("content") or content))
    return {
        "content": content,
        "payload": payload,
        "generation_method": "type_aware_nlp_rules",
        "model_version": "/".join(section.get("model_versions") or ["rules_v2"]),
        "warnings": [],
    }


def adapt_definition(source_text: str, target_level: str) -> str:
    payload = adapt_definition_payload({"text": source_text, "raw_block": {"content": source_text}}, target_level)
    return payload["content"]


def adapt_definition_payload(section: dict, target_level: str) -> dict:
    source_text = section.get("text") or ""
    source = trim_label(source_text)
    figure = detect_figure_key(source)
    profile = FIGURE_PROFILES.get(figure or "")
    term = figure or extract_term(source)
    example = clean_example(section.get("related_example") or (profile or {}).get("example") or "")
    indicator = extract_specific_indicator(source, example, figure)
    instruction = "Reperez dans l'exemple l'element qui permet d'identifier la figure."
    indicator_text = indicator if indicator else instruction
    if target_level == "debutant":
        content = normalize_spaces(
            f"{shorten(source, 170)} Exemple: {example}. Indice: {indicator_text}."
        )
    elif target_level == "avance":
        distinction = (profile or {}).get("advanced_distinction") or f"distinguez {term} d'une notion precise du cours."
        content = normalize_spaces(
            f"{shorten(source, 230)} Exemple: {example}. Indice: {indicator_text}. Distinction: {distinction} Exercice: formulez une justification rigoureuse."
        )
    else:
        content = normalize_spaces(
            f"{shorten(source, 210)} Exemple: {example}. Indice: {indicator_text}. Effet: expliquez brievement ce que cet indice produit dans la phrase. Question: justifiez votre reponse avec l'indice exact."
        )
    payload = structured_payload_from_section(section, content)
    payload.update({
        "type": "definition",
        "content": content,
        "example": example,
        "indicator": indicator_text,
        "near_concept": (profile or {}).get("near_concept"),
    })
    return payload


def adapt_definition_legacy(source_text: str, target_level: str) -> str:
    source = trim_label(source_text)
    profile = FIGURE_PROFILES.get(detect_figure_key(source) or "")
    term = detect_figure_key(source) or extract_term(source)
    indicator = extract_specific_indicator(source, (profile or {}).get("example") or "", detect_figure_key(source))
    if target_level == "debutant":
        return normalize_spaces(
            f"{shorten(source, 220)} Exemple simple: {(profile or {}).get('example') or source}. Indice: {indicator}."
        )
    if target_level == "avance":
        return normalize_spaces(
            f"{shorten(source, 280)} Analyse: precisez la notion, distinguez-la d'une notion proche et expliquez l'effet produit par l'indice repere. Exercice: formulez une justification rigoureuse de {term}."
        )
    return normalize_spaces(
        f"{shorten(source, 260)} Pour la reconnaitre, reperez {indicator}. Utilite: cette notion aide a justifier l'effet produit dans la phrase. Question: quel indice prouve votre reponse ?"
    )


def adapt_example(source_text: str, target_level: str) -> str:
    source = trim_label(source_text)
    indicator = extract_indicator(source)
    if target_level == "debutant":
        return normalize_spaces(f"Exemple conserve: {source} Indice a reperer: {indicator}.")
    if target_level == "avance":
        return normalize_spaces(
            f"Exemple conserve: {source} Analyse avancee: expliquez comment l'indice {indicator} construit l'effet et distinguez ce procede d'un procede voisin."
        )
    return normalize_spaces(
        f"Exemple conserve: {source} Explication: identifiez l'indice {indicator}, puis justifiez en une phrase l'effet produit."
    )


def adapt_methodology_payload(section: dict, target_level: str) -> dict:
    if target_level == "debutant":
        items = ["Nommez la figure.", "Relevez l'indice.", "Expliquez l'effet."]
    elif target_level == "avance":
        items = [
            "Identifiez precisement le procede.",
            "Justifiez avec un indice textuel.",
            "Analysez l'effet produit.",
            "Distinguez-le d'un procede voisin.",
            "Evitez une reponse sans preuve textuelle.",
        ]
    else:
        items = [
            "Identifiez la figure.",
            "Citez l'indice exact.",
            "Justifiez le choix.",
            "Expliquez brievement l'effet.",
        ]
    return {
        **structured_payload_from_section(section, section.get("text") or ""),
        "type": "methodology",
        "items": items,
        "content": "Methode adaptee au niveau.",
    }


def adapt_exercise_payload(section: dict, target_level: str) -> dict:
    raw = section.get("raw_block") if isinstance(section.get("raw_block"), dict) else {}
    question = normalize_spaces(raw.get("question") or raw.get("content") or section.get("text") or "")
    choices = [str(choice) for choice in raw.get("choices") or [] if str(choice).strip()]
    choices = list(dict.fromkeys(choices))
    raw_answer = normalize_spaces(raw.get("answer") or "")
    raw_solution = normalize_spaces(raw.get("solution") or "")
    raw_explanation = normalize_spaces(raw.get("explanation") or "")
    is_qcm = len(choices) >= 2
    answer = raw_answer if is_qcm else ""
    solution = "" if is_qcm else raw_solution
    explanation = raw_explanation
    if is_qcm and not explanation and answer:
        explanation = "La reponse correcte est justifiee par l'indice donne dans la question."
    payload = {
        **structured_payload_from_section(section, section.get("text") or ""),
        "type": "exercise",
        "question": question,
        "choices": choices,
        "answer": answer,
        "explanation": explanation,
        "solution": solution,
        "difficulty": target_level,
        "points": raw.get("points") or (raw.get("metadata") or {}).get("points") or 1,
    }
    if target_level == "debutant":
        payload["question"] = direct_question(question)
    elif target_level == "avance" and not choices:
        payload["question"] = f"{question} Analysez l'effet produit et comparez avec un procede voisin si c'est pertinent."
    elif target_level == "intermediaire":
        payload["question"] = f"{question} Justifiez votre reponse en une phrase."
    if not is_qcm and raw_solution and looks_like_production(question):
        payload["solution"] = f"Exemple possible: {raw_solution}"
    payload["content"] = exercise_content_label(payload, target_level)
    return payload


def adapt_summary_payload(section: dict, target_level: str) -> dict:
    raw = section.get("raw_block") if isinstance(section.get("raw_block"), dict) else {}
    items = [str(item) for item in raw.get("items") or [] if str(item).strip()]
    if not items:
        items = split_steps(raw.get("content") or section.get("text") or "")
    if target_level == "debutant":
        adapted_items = [summary_item_for_level(item, "debutant") for item in items]
    elif target_level == "avance":
        adapted_items = [summary_item_for_level(item, "avance") for item in items]
    else:
        adapted_items = [summary_item_for_level(item, "intermediaire") for item in items]
    return {
        **structured_payload_from_section(section, section.get("text") or ""),
        "type": "summary",
        "items": adapted_items,
        "content": "Points essentiels a retenir.",
    }


def rule_based_adaptation(source_text: str, section_type: str, target_level: str) -> str:
    source = normalize_spaces(source_text)
    if target_level == "debutant":
        return normalize_spaces(
            f"Idee simple: {shorten(source, 260)} Aide: relevez d'abord les mots importants, puis reformulez avec vos propres mots."
        )
    if target_level == "avance":
        return normalize_spaces(
            f"Analyse avancee: {shorten(source, 420)} Travail attendu: interpretez, justifiez et expliquez l'effet produit par les indices du support."
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
            "type": section.get("section_type") or section.get("original_type") or "other",
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
        payload = dict(metadata.get("adapted_payload") or {})
        chapter_id = section.source_chapter_id or "chapter"
        chapter = chapters.setdefault(chapter_id, {
            "source_chapter_id": chapter_id,
            "title": metadata.get("chapter_title") or chapter_id,
            "blocks": [],
        })
        block = {
            **payload,
            "source_block_id": section.source_block_id,
            "source_chapter_id": section.source_chapter_id,
            "source_hash": import_service.sha256(section.original_content.encode("utf-8")),
            "original_block_type": metadata.get("original_type"),
            "level": section.target_level,
            "type": section.section_type,
            "title": metadata.get("title"),
            "content": section.adapted_content,
            "generation_method": metadata.get("generation_method") or "local_nlp_adaptation",
            "detected_type": metadata.get("detected_type") or section.section_type,
            "type_source": metadata.get("type_source"),
            "type_confidence": metadata.get("type_confidence"),
            "adaptation_method": metadata.get("adaptation_method") or metadata.get("generation_method"),
        }
        chapter["blocks"].append(block)
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
        return "exercise"
    if "question" in raw or raw.endswith("?"):
        return "question"
    if "definition" in raw or "definir" in raw:
        return "definition"
    if "resume" in raw:
        return "summary"
    if "methode" in raw or "methodologie" in raw:
        return "methodology"
    if "figure" in raw or "metaphore" in raw or "comparaison" in raw:
        return "figure_de_style"
    if "exemple" in raw:
        return "example"
    if "introduction" in raw:
        return "introduction"
    return "explanation"


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
        "exemple": "example",
        "exemples": "example",
        "example": "example",
        "examples": "example",
        "exercice": "exercise",
        "exercices": "exercise",
        "exercise": "exercise",
        "exercises": "exercise",
        "solution": "correction",
        "resume": "summary",
        "summary": "summary",
        "methodologie": "methodology",
        "methodology": "methodology",
        "production_ecrite": "written_production",
        "written_production": "written_production",
        "contenu_oeuvre": "work_content",
        "work_content": "work_content",
        "oeuvre": "work_content",
        "langue": "language",
        "language": "language",
        "explication": "explanation",
        "explanation": "explanation",
        "comprehension": "comprehension",
        "autre": "other",
        "other": "other",
    }
    normalized = mapping.get(key, key)
    return normalized if normalized in SECTION_TYPES else "other"


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


def collect_examples_by_chapter(sections: list[dict]) -> dict[str, dict[str, str]]:
    examples: dict[str, dict[str, str]] = {}
    positions: dict[str, int] = {}
    figure_order = list(FIGURE_PROFILES.keys())
    for section in sections:
        if normalize_section_type(section.get("original_type") or "") != "example":
            continue
        chapter_id = section.get("chapter_id") or "chapter"
        text = clean_example(section.get("text") or "")
        figure = detect_figure_key(text)
        index = positions.get(chapter_id, 0)
        if not figure:
            figure = figure_order[index] if index < len(figure_order) else None
        positions[chapter_id] = index + 1
        if figure and text:
            examples.setdefault(chapter_id, {})[figure] = text
    return examples


def find_related_example(section: dict, chapter_examples: dict[str, dict[str, str]]) -> str | None:
    if normalize_section_type(section.get("original_type") or "") == "example":
        return clean_example(section.get("text") or "")
    figure = detect_figure_key(" ".join(str(value) for value in [
        section.get("title"),
        section.get("text"),
        section.get("original_type"),
    ] if value))
    if not figure:
        return None
    return (chapter_examples.get(section.get("chapter_id") or "chapter") or {}).get(figure)


def detect_figure_key(value: str) -> str | None:
    normalized = normalize_ascii(value)
    explicit_names = (
        ("personnification", "personnification"),
        ("metaphore", "metaphore"),
        ("comparaison", "comparaison"),
        ("antithese", "antithese"),
        ("hyperbole", "hyperbole"),
        ("anaphore", "anaphore"),
    )
    for key, token in explicit_names:
        if token in normalized:
            return key
    checks = [
        ("metaphore", ("est un lion", "est une ruche")),
        ("personnification", ("dormait", "s_endort", "comportement humain")),
        ("antithese", ("opposition", "oppose", "malgre", "mais")),
        ("hyperbole", ("mille fois", "exagere", "exageration")),
        ("anaphore", ("toujours", "repete", "repetition")),
        ("comparaison", ("comme", "tel que", "ainsi que")),
    ]
    for key, tokens in checks:
        if any(token in normalized for token in tokens):
            return key
    return None


def clean_example(value: str) -> str:
    text = trim_label(value)
    text = re.sub(r"^(exemple\s*(conserve|simple)?\s*[:\-]\s*)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^exemple\s+\d+\s+", "", text, flags=re.IGNORECASE)
    return normalize_spaces(text).rstrip(".")


def extract_specific_indicator(source_text: str, example: str, figure: str | None) -> str:
    profile = FIGURE_PROFILES.get(figure or "")
    source = normalize_ascii(f"{source_text} {example}")
    if figure == "comparaison":
        for token in ("comme", "tel que", "ainsi que"):
            if token in source:
                return token
    if figure == "metaphore":
        return "rapprochement direct sans outil"
    if figure == "personnification":
        for token in ("dormait", "s'endort", "s endort", "parle", "pleure", "sourit"):
            if normalize_ascii(token) in source:
                return token.replace("s endort", "s'endort")
    if figure == "antithese":
        if "sourit" in source and "tristesse" in source:
            return "sourit / tristesse"
        if "mais" in source:
            return "mais"
    if figure == "hyperbole":
        match = re.search(r"(mille\s+fois|cent\s+fois|jamais|toujours)", source, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    if figure == "anaphore":
        words = re.findall(r"\b\w+\b", normalize_ascii(example))
        repeated = [word for word in dict.fromkeys(words) if words.count(word) >= 2 and word not in WEAK_INDICATORS]
        if repeated:
            return repeated[0]
    candidate = normalize_spaces((profile or {}).get("indicator") or "")
    if candidate and normalize_ascii(candidate) not in WEAK_INDICATORS:
        return candidate
    return "Reperez dans l'exemple l'element qui permet d'identifier la figure."


def looks_like_production(question: str) -> bool:
    normalized = normalize_ascii(question)
    return any(token in normalized for token in ("redige", "produis", "ecris", "compose", "production"))


def exercise_content_label(payload: dict, target_level: str) -> str:
    if payload.get("choices"):
        if target_level == "debutant":
            return "QCM simple: choisissez une seule reponse."
        if target_level == "avance":
            return "QCM d'analyse: choisissez la reponse correcte et verifiez l'indice."
        return "QCM guide: choisissez une reponse et justifiez brievement."
    if looks_like_production(payload.get("question") or ""):
        return "Production: plusieurs reponses correctes sont possibles si elles respectent la consigne."
    return "Question ouverte: repondez avec un element attendu et une justification courte."


def summary_item_for_level(item: str, target_level: str) -> str:
    clean = shorten(item, 120)
    figure = detect_figure_key(clean)
    profile = FIGURE_PROFILES.get(figure or "")
    if target_level == "debutant":
        return f"{clean} - definition courte a retenir."
    if target_level == "avance" and profile:
        return f"{clean} - distinction: {profile['advanced_distinction']} Effet: justifiez l'effet produit."
    if target_level == "avance":
        return f"{clean} - precisez la distinction et l'effet."
    indicator = (profile or {}).get("indicator") or "indice principal"
    return f"{clean} - indice principal: {indicator}."


def structured_payload_from_section(section: dict, content: str) -> dict:
    raw = section.get("raw_block") if isinstance(section.get("raw_block"), dict) else {}
    payload: dict[str, Any] = {
        "type": normalize_section_type(section.get("section_type") or raw.get("type") or "other"),
        "title": raw.get("title") or section.get("title") or label_for_type(section.get("section_type") or "other"),
        "content": normalize_spaces(content),
    }
    for key in ("question", "choices", "answer", "solution", "explanation", "items", "metadata", "id"):
        value = raw.get(key)
        if value is not None:
            payload[key] = value
    return payload


def label_for_type(section_type: str) -> str:
    labels = {
        "definition": "Definition",
        "example": "Exemple",
        "methodology": "Methode",
        "exercise": "Exercice",
        "summary": "Resume",
        "correction": "Correction",
        "question": "Question",
        "explanation": "Explication",
    }
    return labels.get(normalize_section_type(section_type), "Contenu")


def trim_label(value: str) -> str:
    return re.sub(
        r"^\s*(definition|exemple|example|exercice|exercise|resume|summary|methode|methodologie)\s*[:\-]\s*",
        "",
        normalize_spaces(value),
        flags=re.IGNORECASE,
    )


def extract_term(value: str) -> str:
    clean = trim_label(value)
    match = re.match(r"([A-Za-zÀ-ÿ'\- ]{3,45})\s*[:\-]", clean)
    if match:
        return normalize_spaces(match.group(1))
    words = re.findall(r"\w+", clean)
    return " ".join(words[:3]) if words else "cette notion"


def extract_indicator(value: str) -> str:
    quoted = re.findall(r"[\"'«](.*?)[\"'»]", value)
    if quoted:
        return f"l'expression « {shorten(quoted[0], 45)} »"
    words = re.findall(r"\w+", trim_label(value))
    if words:
        return f"le mot « {words[0]} »"
    return "un indice precis du support"


def split_steps(value: str) -> list[str]:
    text = normalize_spaces(value)
    chunks = re.split(r"(?:\s*[-•]\s+|\s*\d+[\).]\s+|[.;]\s+)", text)
    return [normalize_spaces(item) for item in chunks if normalize_spaces(item)]


def direct_question(value: str) -> str:
    question = normalize_spaces(value)
    if not question.endswith("?"):
        return question
    return question


def text_from_structured_payload(payload: dict) -> str:
    parts: list[str] = []
    if payload.get("content"):
        parts.append(str(payload["content"]))
    if payload.get("question"):
        parts.append(f"Question: {payload['question']}")
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        parts.append("Choix: " + " | ".join(str(choice) for choice in choices))
    if payload.get("answer"):
        parts.append(f"Reponse: {payload['answer']}")
    if payload.get("solution"):
        parts.append(f"Solution: {payload['solution']}")
    if payload.get("explanation"):
        parts.append(f"Explication: {payload['explanation']}")
    items = payload.get("items")
    if isinstance(items, list) and items:
        parts.extend(str(item) for item in items)
    return remove_forbidden_narrative_templates(normalize_spaces(" ".join(parts)))


def remove_forbidden_narrative_templates(value: str) -> str:
    clean = normalize_spaces(value)
    for pattern in NARRATIVE_FORBIDDEN_PATTERNS:
        clean = re.sub(re.escape(pattern), "", clean, flags=re.IGNORECASE)
    return normalize_spaces(clean)


def validate_adaptations_before_professor_validation(adaptations: list[CourseAdaptation]) -> list[str]:
    errors: list[str] = []
    for adaptation in adaptations:
        sections = list(adaptation.sections)
        if not sections:
            errors.append(f"Adaptation {adaptation.id}: aucune section adaptee")
            continue
        detect_reused_figure_examples(adaptation, sections, errors)
        explicit_sections = [
            section for section in sections
            if normalize_section_type((section.metadata_json or {}).get("original_type") or "") in EXPLICIT_JSON_TYPES
        ]
        other_explicit = [
            section for section in explicit_sections
            if normalize_section_type(section.section_type) == "other"
        ]
        if explicit_sections and (len(other_explicit) / len(explicit_sections)) > 0.30:
            errors.append(f"Adaptation {adaptation.id}: trop de sections explicites classees en other")
        for section in sections:
            metadata = section.metadata_json or {}
            payload = metadata.get("adapted_payload") if isinstance(metadata.get("adapted_payload"), dict) else {}
            section_type = normalize_section_type(section.section_type)
            adapted = normalize_spaces(section.adapted_content)
            original = normalize_spaces(section.original_content)
            label = f"Adaptation {adaptation.id}, section {section.section_id}"
            if not adapted:
                errors.append(f"{label}: adaptation vide")
            if section_type == "other" and normalize_section_type(metadata.get("original_type") or "") in EXPLICIT_JSON_TYPES:
                errors.append(f"{label}: type explicite perdu")
            if section.target_level != section.source_level and adapted and adapted == original:
                errors.append(f"{label}: copie exacte sans adaptation")
            if contains_forbidden_narrative_template(adapted):
                errors.append(f"{label}: modele narratif non pertinent detecte")
            if has_weak_indicator(payload):
                errors.append(f"{label}: indice non fiable")
            if is_question_duplicated(adapted, payload):
                errors.append(f"{label}: question dupliquee dans le rendu")
            if section.target_level == "avance" and asks_vague_distinction(adapted):
                errors.append(f"{label}: distinction avancee sans notion precise")
            if section_type == "exercise":
                validate_exercise_payload(label, payload, errors)
            if section_type == "summary":
                items = payload.get("items")
                if items is not None and not isinstance(items, list):
                    errors.append(f"{label}: le resume doit rester une liste")
    return errors


def validate_exercise_payload(label: str, payload: dict, errors: list[str]) -> None:
    question = normalize_spaces(payload.get("question") or "")
    answer = normalize_spaces(payload.get("answer") or payload.get("solution") or "")
    choices = payload.get("choices")
    if not question:
        errors.append(f"{label}: exercice sans question")
    if not answer:
        errors.append(f"{label}: exercice sans reponse ou solution")
    if choices is not None:
        clean_choices = [str(choice).strip() for choice in choices if str(choice).strip()] if isinstance(choices, list) else []
        if len(clean_choices) < 2:
            errors.append(f"{label}: QCM sans choix valides")
        if len(clean_choices) != len(set(clean_choices)):
            errors.append(f"{label}: QCM avec choix dupliques")
    values = [normalize_ascii(payload.get(key) or "") for key in ("answer", "solution", "explanation") if payload.get(key)]
    if len(values) >= 2 and len(set(values)) == 1:
        errors.append(f"{label}: answer, solution et explanation ne doivent pas etre identiques")
    if looks_like_production(payload.get("question") or "") and normalize_ascii(payload.get("solution") or "").startswith("reponse obligatoire"):
        errors.append(f"{label}: production presentee comme reponse obligatoire")


def contains_forbidden_narrative_template(value: str) -> bool:
    normalized = normalize_ascii(value)
    return any(normalize_ascii(pattern) in normalized for pattern in NARRATIVE_FORBIDDEN_PATTERNS)


def detect_reused_figure_examples(adaptation: CourseAdaptation, sections: list, errors: list[str]) -> None:
    by_example: dict[str, set[str]] = {}
    for section in sections:
        if normalize_section_type(section.section_type) != "definition":
            continue
        payload = (section.metadata_json or {}).get("adapted_payload") or {}
        example = normalize_ascii(payload.get("example") or "")
        figure = detect_figure_key(section.original_content) or detect_figure_key(payload.get("content") or "")
        if example and figure:
            by_example.setdefault(example, set()).add(figure)
    for example, figures in by_example.items():
        if len(figures) > 1:
            errors.append(
                f"Adaptation {adaptation.id}: meme exemple reutilise pour plusieurs figures ({', '.join(sorted(figures))})"
            )


def has_weak_indicator(payload: dict) -> bool:
    indicator = normalize_ascii(payload.get("indicator") or "")
    return indicator in WEAK_INDICATORS


def is_question_duplicated(adapted: str, payload: dict) -> bool:
    question = normalize_spaces(payload.get("question") or "")
    if not question:
        return False
    return normalize_ascii(adapted).count(normalize_ascii(question)) > 1


def asks_vague_distinction(value: str) -> bool:
    normalized = normalize_ascii(value)
    return "notion proche" in normalized and not any(
        normalize_ascii(profile["near_concept"]) in normalized
        for profile in FIGURE_PROFILES.values()
    )
