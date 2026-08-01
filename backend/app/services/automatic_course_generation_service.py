from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.persistence import (
    Assessment,
    AssessmentAssignment,
    AssessmentQuestion,
    Classroom,
    ClassroomCourseAssignment,
    ClassroomMembership,
    Course,
    CourseChapter,
    CourseExample,
    CourseLevelVariant,
    CourseObjective,
    CourseSkill,
    DiagnosticQuestion,
    DifficultyLevel,
    LiteraryWork,
    Notification,
    PedagogicalPackageImportJob,
    Quiz,
    QuizQuestion,
    RegionalExamProfile,
    Skill,
    Subject,
    UserProfile,
)
from app.schemas.automatic_import import PedagogicalPackage
from app.core.config import get_settings
from app.services import ai_course_generation_service
from app.services import course_service, diagnostic_question_generation_service, rag_document_service

MAX_JSON_SIZE = int(os.getenv("AUTO_IMPORT_MAX_JSON_SIZE", str(2 * 1024 * 1024)))
MAX_LATEX_SIZE = int(os.getenv("AUTO_IMPORT_MAX_LATEX_SIZE", str(5 * 1024 * 1024)))
MAX_GENERATED_PDF_SIZE = int(os.getenv("AUTO_IMPORT_MAX_GENERATED_PDF_SIZE", str(20 * 1024 * 1024)))
LATEX_COMPILE_TIMEOUT_SECONDS = int(os.getenv("AUTO_IMPORT_LATEX_TIMEOUT_SECONDS", "120"))
IMPORT_LATEX_IN_CHAPTER_CONTENT = os.getenv("AUTO_IMPORT_LATEX_IN_CONTENT", "false").lower() == "true"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATED_LATEX_PDF_ROOT = PROJECT_ROOT / "docs" / "automatic_import_pdfs"
LEVELS = ("debutant", "intermediaire", "avance")
AI_VARIANT_TASKS_IN_PROGRESS: set[int] = set()
DANGEROUS_LATEX_PATTERNS = (
    r"\\write18\b",
    r"\\openout\b",
    r"\\openin\b",
    r"\\read\b",
    r"\\immediate\b",
    r"\\input\s*\{[^}]*([/\\]|\.\.)",
    r"\\include\s*\{[^}]*([/\\]|\.\.)",
    r"\\includegraphics(?:\[[^\]]*\])?\s*\{[^}]*([/\\]|\.\.)",
    r"[A-Za-z]:\\",
)


def import_package(
    db: Session,
    professor: UserProfile,
    json_file: UploadFile,
    latex_file: UploadFile | None,
    classroom_id: int,
    auto_assign: bool = True,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    json_bytes = read_upload(json_file, ".json", MAX_JSON_SIZE, "JSON")
    latex_bytes = read_upload(latex_file, {".tex", ".latex"}, MAX_LATEX_SIZE, "LaTeX") if latex_file else None
    package = parse_package(json_bytes)
    latex_structure = parse_latex(latex_bytes.decode("utf-8")) if latex_bytes else {}
    validate_latex_references(package, latex_structure)

    classroom = get_owned_classroom(db, professor, classroom_id)
    json_hash = sha256(json_bytes)
    latex_hash = sha256(latex_bytes) if latex_bytes else None
    existing_job = db.scalars(
        select(PedagogicalPackageImportJob).where(
            PedagogicalPackageImportJob.json_sha256 == json_hash,
            PedagogicalPackageImportJob.latex_sha256 == latex_hash,
            PedagogicalPackageImportJob.classroom_id == classroom_id,
            PedagogicalPackageImportJob.professor_id == professor.id,
        )
    ).first()
    if existing_job and existing_job.status == "completed":
        if auto_assign and existing_job.course_id:
            classroom = get_owned_classroom(db, professor, classroom_id)
            course_assignment_summary = assign_course_to_classroom(db, existing_job.course_id, classroom, professor)
            if isinstance(existing_job.result_summary, dict):
                existing_job.result_summary = {
                    **existing_job.result_summary,
                    **course_assignment_summary,
                }
        refresh_existing_job_summary(db, existing_job)
        db.commit()
        db.refresh(existing_job)
        return serialize_job(existing_job)

    try:
        job = PedagogicalPackageImportJob(
            professor_id=professor.id,
            classroom_id=classroom_id,
            status="processing",
            schema_version=package.schema_version,
            json_filename=safe_filename(json_file.filename or "package.json"),
            latex_filename=safe_filename(latex_file.filename) if latex_file and latex_file.filename else None,
            json_sha256=json_hash,
            latex_sha256=latex_hash,
            generation_method="deterministic",
            source_summary={
                "mode": "json_latex" if latex_bytes else "json_only",
                "target": package.target.model_dump(),
                "course_title": package.course.title,
                "works": [{"title": work.title, "author": work.author} for work in package.works],
                "works_count": len(package.works),
                "chapters_count": len(package.chapters),
                "visuals_count": count_visual_specs(package),
                "regional_exams_count": count_regional_exam_items(package),
            },
            started_at=datetime.utcnow(),
        )
        db.add(job)
        db.flush()

        subject = get_or_create_subject(db, package.course.subject)
        education_level = get_or_create_catalog(db, "education", package.course.education_level)
        difficulty_level = get_or_create_catalog(db, "difficulty", package.course.difficulty)
        job.subject_id = subject.id
        job.education_level_id = education_level.id
        job.academic_year = package.target.academic_year
        course = create_course_from_package(db, professor, package, subject.id, education_level.id, difficulty_level.id)
        db.flush()
        job.course_id = course.id

        latex_pdf_info = None
        if latex_bytes:
            latex_pdf_info = compile_latex_upload_to_pdf(
                latex_text=latex_bytes.decode("utf-8"),
                original_filename=latex_file.filename if latex_file else "support.tex",
                course_id=course.id,
                import_job_id=job.id,
            )
            course.information = {
                **(course.information or {}),
                "latex_pdf": latex_pdf_info,
            }

        chapter_by_source = create_chapters_and_skills(
            db,
            course,
            package,
            latex_structure,
            latex_pdf_info=latex_pdf_info,
        )
        create_literary_works(db, course, package)
        variant_summary = create_variants(db, course, package, latex_structure, background_tasks=background_tasks)
        quiz_questions_count = create_quiz(db, course, package, chapter_by_source)
        diagnostic_bank = diagnostic_question_generation_service.generate_bank_for_import(
            db=db,
            package=package,
            course=course,
            subject_id=subject.id,
            education_level_id=education_level.id,
            chapter_by_source=chapter_by_source,
            imported_package_hash=json_hash,
            classroom_id=classroom.id,
            import_job_id=job.id,
            academic_year=package.target.academic_year,
            latex_structure=latex_structure,
        )
        obsolete_count = deactivate_previous_diagnostic_banks(db, job, subject.id, education_level.id, package.target.academic_year)
        assessments = create_assessments(db, professor, classroom, course, package, subject.id, chapter_by_source)
        course_assignment_summary = assign_course_to_classroom(db, course.id, classroom, professor) if auto_assign else empty_course_assignment_summary()
        assigned_students = assign_assessments(db, assessments, classroom) if auto_assign else 0
        create_regional_profiles(db, package, classroom)

        job.status = "completed"
        job.is_current = True
        job.completed_at = datetime.utcnow()
        job.chapters_count = count_course_chapters(db, course.id)
        job.variants_count = 3
        job.questions_count = sum(len(assessment.questions) for assessment in assessments)
        job.assigned_students_count = assigned_students
        job.result_summary = {
            "course_id": course.id,
            "course_title": course.title,
            "chapters_count": job.chapters_count,
            "visuals_count": count_visual_specs(package),
            "regional_exams_count": count_regional_exam_items(package),
            "assessments_created": len(assessments),
            "assigned_students": assigned_students,
            "course_classroom_assignments": course_assignment_summary["course_classroom_assignments"],
            "assessment_assignments": assigned_students,
            "students_with_course_access": course_assignment_summary["students_with_course_access"],
            "ai_variants_status": variant_summary["ai_variants_status"],
            "ai_variants_generated": variant_summary["ai_variants_generated"],
            "ai_variants_failed": variant_summary["ai_variants_failed"],
            "ai_levels": variant_summary["ai_levels"],
            "generation_method": variant_summary["generation_method"],
            "ai_variants_error": variant_summary.get("ai_variants_error"),
            "diagnostic_bank": diagnostic_bank,
            "obsolete_diagnostic_questions_deactivated": obsolete_count,
            "rag_index_requested": True,
            "quiz_questions_count": quiz_questions_count,
            "latex_pdf": latex_pdf_info,
            "latex_pdf_url": latex_pdf_info.get("url") if latex_pdf_info else None,
        }
        db.commit()
        db.refresh(job)

        try:
            rag_document_service.request_course_reindex(db, course.id, professor)
            db.commit()
        except Exception:
            db.rollback()

        return serialize_job(job)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Import automatique impossible: {exc}") from exc



def compile_latex_upload_to_pdf(
    latex_text: str,
    original_filename: str,
    course_id: int,
    import_job_id: int,
) -> dict:
    """Compile the professor's LaTeX upload in an isolated temporary directory."""

    compiler_name, compiler = select_latex_compiler(latex_text)

    safe_source = prepare_latex_document(latex_text)
    output_directory = GENERATED_LATEX_PDF_ROOT / f"course_{course_id}" / f"import_{import_job_id}"
    output_directory.mkdir(parents=True, exist_ok=True)

    source_stem = slugify(Path(original_filename or "support.tex").stem) or "support"
    final_filename = f"{source_stem}.pdf"
    final_path = output_directory / final_filename

    with tempfile.TemporaryDirectory(prefix="edumentor_latex_") as temp_name:
        temp_dir = Path(temp_name)
        tex_path = temp_dir / "source.tex"
        tex_path.write_text(safe_source, encoding="utf-8")

        command = [
            compiler,
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-output-directory",
            str(temp_dir),
            str(tex_path),
        ]

        compile_log = ""
        for _ in range(2):
            try:
                result = subprocess.run(
                    command,
                    cwd=str(temp_dir),
                    capture_output=True,
                    text=True,
                    timeout=LATEX_COMPILE_TIMEOUT_SECONDS,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Compilation LaTeX trop longue (>{LATEX_COMPILE_TIMEOUT_SECONDS}s).",
                ) from exc

            compile_log = f"{result.stdout}\n{result.stderr}".strip()
            if result.returncode != 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"Compilation LaTeX impossible: {latex_error_excerpt(compile_log)}",
                )

        generated_pdf = temp_dir / "source.pdf"
        if not generated_pdf.exists():
            raise HTTPException(status_code=422, detail="LaTeX compile sans produire de PDF.")

        pdf_size = generated_pdf.stat().st_size
        if pdf_size <= 0:
            raise HTTPException(status_code=422, detail="Le PDF LaTeX genere est vide.")
        if pdf_size > MAX_GENERATED_PDF_SIZE:
            raise HTTPException(status_code=413, detail="Le PDF LaTeX genere est trop volumineux.")

        shutil.copy2(generated_pdf, final_path)

    relative_path = final_path.relative_to(PROJECT_ROOT / "docs").as_posix()
    return {
        "url": f"/docs/{relative_path}",
        "filename": final_filename,
        "source_filename": safe_filename(original_filename or "support.tex"),
        "size_bytes": final_path.stat().st_size,
        "sha256": sha256(final_path.read_bytes()),
        "generated_at": datetime.utcnow().isoformat(),
        "course_id": course_id,
        "import_job_id": import_job_id,
        "kind": "latex_generated_pdf",
        "latex_engine": compiler_name,
    }



def select_latex_compiler(latex_text: str) -> tuple[str, str]:
    """Choose a compatible LaTeX engine from the uploaded document."""

    unicode_engine_patterns = (
        r"\\usepackage(?:\[[^\]]*\])?\{[^}]*fontspec[^}]*\}",
        r"\\usepackage(?:\[[^\]]*\])?\{[^}]*polyglossia[^}]*\}",
        r"\\usepackage(?:\[[^\]]*\])?\{[^}]*unicode-math[^}]*\}",
        r"\\setmainfont\b",
        r"\\setsansfont\b",
        r"\\setmonofont\b",
        r"\\newfontfamily\b",
        r"\\setdefaultlanguage\b",
    )
    needs_unicode_engine = any(
        re.search(pattern, latex_text, flags=re.IGNORECASE)
        for pattern in unicode_engine_patterns
    )

    candidates = (
        ("xelatex", "lualatex")
        if needs_unicode_engine
        else ("pdflatex", "xelatex", "lualatex")
    )
    for compiler_name in candidates:
        compiler_path = shutil.which(compiler_name)
        if compiler_path:
            return compiler_name, compiler_path

    expected = (
        "XeLaTeX ou LuaLaTeX"
        if needs_unicode_engine
        else "pdfLaTeX, XeLaTeX ou LuaLaTeX"
    )
    raise HTTPException(
        status_code=503,
        detail=(
            f"Moteur LaTeX introuvable ({expected}). "
            "Installez MiKTeX puis redemarrez le backend."
        ),
    )


def prepare_latex_document(latex_text: str) -> str:
    """Accept a complete document or wrap a LaTeX fragment in a safe report template."""

    text = latex_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="LaTeX vide")

    if re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", text):
        if not re.search(r"\\begin\{document\}", text) or not re.search(r"\\end\{document\}", text):
            raise HTTPException(
                status_code=422,
                detail="Document LaTeX incomplet: begin{document} ou end{document} absent.",
            )
        return text

    return (
        "\\documentclass[12pt,a4paper]{report}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage{lmodern}\n"
        "\\usepackage[a4paper,margin=2cm]{geometry}\n"
        "\\usepackage[hidelinks]{hyperref}\n"
        "\\setlength{\\parindent}{0pt}\n"
        "\\setlength{\\parskip}{6pt}\n"
        "\\begin{document}\n"
        f"{text}\n"
        "\\end{document}\n"
    )


def latex_error_excerpt(log: str, max_chars: int = 1400) -> str:
    lines = [line.strip() for line in str(log or "").splitlines() if line.strip()]
    important = [
        line
        for line in lines
        if line.startswith("!")
        or "LaTeX Error" in line
        or "Emergency stop" in line
        or re.search(r"\.tex:\d+:", line)
    ]
    selected = important[-8:] if important else lines[-12:]
    excerpt = " | ".join(selected)
    return excerpt[-max_chars:] or "erreur inconnue"


def deactivate_previous_diagnostic_banks(
    db: Session,
    current_job: PedagogicalPackageImportJob,
    subject_id: int,
    education_level_id: int | None,
    academic_year: str | None,
) -> int:
    previous_jobs = list(db.scalars(
        select(PedagogicalPackageImportJob).where(
            PedagogicalPackageImportJob.id != current_job.id,
            PedagogicalPackageImportJob.classroom_id == current_job.classroom_id,
            PedagogicalPackageImportJob.subject_id == subject_id,
            PedagogicalPackageImportJob.education_level_id == education_level_id,
            PedagogicalPackageImportJob.academic_year == academic_year,
            PedagogicalPackageImportJob.status == "completed",
            PedagogicalPackageImportJob.is_current.is_(True),
        )
    ))
    if not previous_jobs:
        return 0

    previous_job_ids = [job.id for job in previous_jobs]
    for job in previous_jobs:
        job.is_current = False

    return int(db.query(DiagnosticQuestion).filter(
        DiagnosticQuestion.import_job_id.in_(previous_job_ids),
        DiagnosticQuestion.classroom_id == current_job.classroom_id,
        DiagnosticQuestion.subject_id == subject_id,
        DiagnosticQuestion.education_level_id == education_level_id,
        DiagnosticQuestion.academic_year == academic_year,
        DiagnosticQuestion.active.is_(True),
    ).update(
        {DiagnosticQuestion.active: False, DiagnosticQuestion.updated_at: datetime.utcnow()},
        synchronize_session=False,
    ) or 0)


def get_job(db: Session, user: UserProfile, job_id: int) -> dict:
    job = db.get(PedagogicalPackageImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job d'import introuvable")
    if user.role != "admin" and job.professor_id != user.id:
        raise HTTPException(status_code=403, detail="Job non autorise")
    return serialize_job(job)


def repair_completed_course_classroom_assignments(db: Session) -> dict:
    jobs = list(
        db.scalars(
            select(PedagogicalPackageImportJob).where(
                PedagogicalPackageImportJob.status == "completed",
                PedagogicalPackageImportJob.course_id.is_not(None),
                PedagogicalPackageImportJob.classroom_id.is_not(None),
                PedagogicalPackageImportJob.assigned_students_count > 0,
            )
        )
    )
    repaired = 0
    students_with_access = 0
    for job in jobs:
        classroom = db.get(Classroom, job.classroom_id)
        professor = db.get(UserProfile, job.professor_id)
        course = db.get(Course, job.course_id) if job.course_id else None
        if classroom is None or professor is None or job.course_id is None:
            continue
        if course is not None and course.status not in {"archived", "closed"}:
            course.published = True
            course.status = "published"
        summary = assign_course_to_classroom(db, job.course_id, classroom, professor)
        repaired += summary["course_classroom_assignments"]
        students_with_access += summary["students_with_course_access"]
        if isinstance(job.result_summary, dict):
            job.result_summary = {
                **job.result_summary,
                "course_classroom_assignments": summary["course_classroom_assignments"],
                "assessment_assignments": job.assigned_students_count,
                "students_with_course_access": summary["students_with_course_access"],
            }
    db.commit()
    return {"jobs_checked": len(jobs), "course_classroom_assignments": repaired, "students_with_course_access": students_with_access}


def read_upload(file: UploadFile | None, extension: str | set[str], max_size: int, label: str) -> bytes:
    if file is None or not file.filename:
        raise HTTPException(status_code=422, detail=f"Fichier {label} obligatoire")
    allowed_extensions = {extension} if isinstance(extension, str) else extension
    if Path(file.filename.lower()).suffix not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(status_code=422, detail=f"Extension {allowed} obligatoire pour {label}")
    data = file.file.read(max_size + 1)
    if len(data) > max_size:
        raise HTTPException(status_code=413, detail=f"Fichier {label} trop volumineux")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Fichier {label} non UTF-8") from exc
    return data


def parse_package(raw: bytes) -> PedagogicalPackage:
    try:
        data = json.loads(raw.decode("utf-8"))
        return PedagogicalPackage.model_validate(data)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"JSON invalide: {exc.msg}") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def parse_latex(text: str) -> dict:
    for pattern in DANGEROUS_LATEX_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            raise HTTPException(status_code=422, detail="LaTeX dangereux detecte")
    if not text.strip():
        raise HTTPException(status_code=422, detail="LaTeX vide")
    sections = {}
    current_key = None
    current_lines: list[str] = []
    pending_heading: str | None = None
    for line in text.splitlines():
        heading = re.search(r"\\(?:chapter|section|subsection)\{([^}]+)\}", line)
        label = re.search(r"\\label\{([^}]+)\}", line)
        if heading and not label:
            if current_key:
                sections[current_key] = latex_lines_to_blocks(current_lines)
            pending_heading = heading.group(1)
            current_key = normalize_ref(pending_heading)
            current_lines = [pending_heading]
        elif label and pending_heading and current_key == normalize_ref(pending_heading) and len(current_lines) == 1:
            current_key = normalize_ref(label.group(1))
            pending_heading = None
            if heading:
                current_lines = [heading.group(1)]
        elif heading or label:
            if current_key:
                sections[current_key] = latex_lines_to_blocks(current_lines)
            current_key = normalize_ref((label or heading).group(1))
            current_lines = [heading.group(1) if heading else ""]
            pending_heading = None
        elif current_key:
            current_lines.append(line)
            if line.strip():
                pending_heading = None
    if current_key:
        sections[current_key] = latex_lines_to_blocks(current_lines)
    return {"sections": sections, "raw_hash": sha256(text.encode("utf-8"))}


def latex_lines_to_blocks(lines: list[str]) -> list[dict]:
    blocks = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        if line.startswith(r"\begin{itemize}") or line.startswith(r"\end{itemize}"):
            continue
        if line.startswith(r"\item"):
            blocks.append({"type": "list_item", "content": line.replace(r"\item", "", 1).strip()})
        elif r"\[" in line or r"\(" in line or r"\begin{equation}" in line:
            blocks.append({"type": "formula", "content": line})
        elif "exercice" in line.lower():
            blocks.append({"type": "exercise", "content": line})
        elif "solution" in line.lower():
            blocks.append({"type": "solution", "content": line})
        else:
            blocks.append({"type": "paragraph", "content": line})
    return blocks


def validate_latex_references(package: PedagogicalPackage, latex_structure: dict) -> None:
    if not latex_structure:
        return
    available = set(latex_structure.get("sections", {}).keys())
    for chapter in package.chapters:
        if chapter.latex_reference and normalize_ref(chapter.latex_reference) not in available:
            raise HTTPException(status_code=422, detail=f"Reference LaTeX absente: {chapter.latex_reference}")


def get_owned_classroom(db: Session, user: UserProfile, classroom_id: int) -> Classroom:
    classroom = db.get(Classroom, classroom_id)
    if classroom is None or not classroom.active:
        raise HTTPException(status_code=404, detail="Classe introuvable")
    if user.role != "admin" and classroom.professor_id != user.id:
        raise HTTPException(status_code=403, detail="Classe non autorisee")
    return classroom


def get_or_create_subject(db: Session, name: str) -> Subject:
    slug = catalog_slug(name)
    subject = db.scalars(select(Subject).where((Subject.slug == slug) | (Subject.name == name.strip()))).first()
    if subject:
        return subject
    subject = Subject(name=name.strip(), slug=slug, description=f"Matiere importee automatiquement: {name.strip()}")
    db.add(subject)
    db.flush()
    return subject


def get_or_create_catalog(db: Session, kind: str, name: str):
    model = DifficultyLevel if kind == "difficulty" else __import__("app.models.persistence", fromlist=["EducationLevel"]).EducationLevel
    slug = catalog_slug(name)
    row = db.scalars(select(model).where((model.slug == slug) | (model.name == name.strip()))).first()
    if row:
        return row
    row = model(name=name.strip(), slug=slug, display_order=99)
    db.add(row)
    db.flush()
    return row


def create_course_from_package(db: Session, professor: UserProfile, package: PedagogicalPackage, subject_id: int, education_level_id: int, difficulty_level_id: int) -> Course:
    next_id = (db.scalar(select(Course.id).order_by(Course.id.desc()).limit(1)) or 0) + 1
    course = Course(
        id=next_id,
        title=package.course.title.strip(),
        level="Adaptatif",
        duration=f"{package.course.estimated_duration_hours:g}h",
        summary=package.course.summary.strip(),
        description=package.course.description.strip(),
        exercises=[],
        information={
            "level": "Adaptatif",
            "duration": f"{package.course.estimated_duration_hours:g}h",
            "language": "Francais",
            "last_update": datetime.utcnow().date().isoformat(),
            "chapter_count": len(package.chapters),
            "target": package.target.model_dump(),
            "schema_version": package.schema_version,
            "visuals_count": count_visual_specs(package),
            "regional_exams_count": count_regional_exam_items(package),
            "content_quality_requirements": package.content_quality_requirements.model_dump() if package.content_quality_requirements else None,
            "source_policy": package.source_policy.model_dump() if package.source_policy else None,
            "assets": package.assets.model_dump() if package.assets else None,
            "ai_generation_rules": package.ai_generation_rules.model_dump() if package.ai_generation_rules else None,
            "latex_export": package.latex_export.model_dump() if package.latex_export else None,
            "regional_exam_bank": package.regional_exam_bank.model_dump() if package.regional_exam_bank else {"items": []},
        },
        display_order=next_id,
        published=True,
        status="published",
        subject_id=subject_id,
        education_level_id=education_level_id,
        difficulty_level_id=difficulty_level_id,
        professor_id=professor.id,
        estimated_duration=f"{package.course.estimated_duration_hours:g}h",
        prerequisites="\n".join(package.course.prerequisites),
    )
    db.add(course)
    return course


def create_chapters_and_skills(db: Session, course: Course, package: PedagogicalPackage, latex_structure: dict, latex_pdf_info: dict | None = None) -> dict[str, CourseChapter]:
    chapter_by_source = {}
    all_objectives: list[str] = []
    all_skills: list[str] = []
    for chapter_data in sorted(package.chapters, key=lambda item: item.order):
        source_blocks = [block.model_dump() for block in chapter_data.content_blocks]
        latex_blocks = (
            latex_structure.get("sections", {}).get(normalize_ref(chapter_data.latex_reference or ""), [])
            if IMPORT_LATEX_IN_CHAPTER_CONTENT
            else []
        )
        chapter_visuals = visual_specs_for_chapter(package, chapter_data.id, chapter_data.latex_reference)
        blocks = build_structured_blocks(
            chapter_data.id,
            source_blocks,
            latex_blocks,
            chapter_visuals,
            latex_pdf_info=latex_pdf_info,
        )
        chapter = CourseChapter(
            course=course,
            title=chapter_data.title,
            duration="45 min",
            status="active" if chapter_data.order == 1 else "locked",
            openable=chapter_data.order == 1,
            content=plain_text_from_blocks(blocks),
            structured_content=blocks,
            position=chapter_data.order,
            estimated_duration="45 min",
        )
        course.chapters.append(chapter)
        db.flush()
        chapter_by_source[chapter_data.id] = chapter
        all_objectives.extend(chapter_data.objectives)
        all_skills.extend(chapter_data.skills)
        for skill_name in chapter_data.skills:
            ensure_skill(db, course, chapter, skill_name)
    course.objectives = [CourseObjective(text=text, position=index) for index, text in enumerate(unique_keep_order(all_objectives), start=1)]
    course.skills = [CourseSkill(text=text, position=index) for index, text in enumerate(unique_keep_order(all_skills), start=1)]
    course.examples = [
        CourseExample(title=f"Exemple {index}", description=block.get("content", ""), position=index)
        for index, block in enumerate(extract_blocks(package, "example")[:8], start=1)
    ]
    return chapter_by_source


def build_structured_blocks(
    source_chapter_id: str,
    source_blocks: list[dict],
    latex_blocks: list[dict],
    visual_specs: list[dict] | None = None,
    latex_pdf_info: dict | None = None,
) -> list[dict]:
    """Preserve JSON metadata and attach the generated LaTeX PDF to regional exams."""

    blocks: list[dict] = []

    for index, block in enumerate(source_blocks, start=1):
        content = block.get("content") or block.get("question") or ""
        metadata = dict(block.get("metadata") or {}) if isinstance(block.get("metadata"), dict) else {}
        section = block.get("section") or metadata.get("section")
        source_block_id = block.get("id") or f"{source_chapter_id}_block_{index}"

        is_regional_exam = (
            normalize_ref(str(section or "")) in {"regional-exams", "regional-exam", "examens-regionaux", "examen-regional"}
            or "regional-exam" in normalize_ref(str(source_block_id))
        )
        if latex_pdf_info and is_regional_exam:
            metadata.setdefault("latex_pdf_url", latex_pdf_info["url"])
            metadata.setdefault("combined_pdf_url", latex_pdf_info["url"])
            metadata.setdefault("pdf_filename", latex_pdf_info["filename"])
            metadata.setdefault("pdf_generated_from_latex", True)

        payload = {
            "type": block.get("type", "paragraph"),
            "title": block.get("title"),
            "content": content,
            "question": block.get("question"),
            "solution": block.get("solution"),
            "answer": block.get("answer"),
            "explanation": block.get("explanation"),
            "items": block.get("items"),
            "choices": block.get("choices"),
            "metadata": metadata or None,
            "section": section,
            "source_chapter_id": source_chapter_id,
            "source_block_id": source_block_id,
            "generation_method": "source_json",
        }
        payload["source_hash"] = sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        )
        blocks.append({key: value for key, value in payload.items() if value is not None})

    for index, visual in enumerate(visual_specs or [], start=1):
        visual_payload = dict(visual)
        visual_id = visual_payload.get("id") or f"{source_chapter_id}_visual_{index}"
        visual_type = visual_payload.get("type", "visual")
        content = (
            visual_payload.get("content")
            or visual_payload.get("description")
            or visual_payload.get("title")
            or visual_type
        )
        visual_metadata = (
            dict(visual_payload.get("metadata"))
            if isinstance(visual_payload.get("metadata"), dict)
            else {}
        )
        visual_section = visual_payload.get("section") or visual_metadata.get("section") or "schemas"

        visual_block = {
            "type": "visual",
            "visual_type": visual_type,
            "title": visual_payload.get("title") or visual_type,
            "content": content,
            "spec": visual_payload,
            "metadata": visual_metadata or None,
            "section": visual_section,
            "source_chapter_id": source_chapter_id,
            "source_block_id": visual_id,
            "generation_method": "source_json_visual",
            "source_hash": sha256(
                json.dumps(visual_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ),
        }
        blocks.append({key: value for key, value in visual_block.items() if value is not None})

    for index, block in enumerate(latex_blocks, start=1):
        content = block.get("content", "")
        latex_block = {
            "type": block.get("type", "paragraph"),
            "title": block.get("title"),
            "content": content,
            "metadata": block.get("metadata") if isinstance(block.get("metadata"), dict) else None,
            "section": block.get("section"),
            "source_chapter_id": source_chapter_id,
            "source_block_id": f"{source_chapter_id}_latex_{index}",
            "generation_method": "source_latex",
            "source_hash": sha256(content.encode("utf-8")),
        }
        blocks.append({key: value for key, value in latex_block.items() if value is not None})

    return blocks


def create_literary_works(db: Session, course: Course, package: PedagogicalPackage) -> None:
    for work in package.works:
        db.add(LiteraryWork(
            course=course,
            source_work_id=work.id,
            title=work.title,
            author=work.author,
            genre=work.genre,
            context=work.context,
            chapters=[chapter.model_dump() for chapter in work.chapters],
            target_metadata=package.target.model_dump(),
        ))


def create_variants(
    db: Session,
    course: Course,
    package: PedagogicalPackage,
    latex_structure: dict,
    background_tasks: BackgroundTasks | None = None,
) -> dict:
    source_hash = source_hash_for_package(package)
    existing_levels = {
        level
        for level in db.scalars(
            select(CourseLevelVariant.level).where(
                CourseLevelVariant.course_id == course.id,
                CourseLevelVariant.source_hash == source_hash,
                CourseLevelVariant.level.in_(LEVELS),
            )
        )
    }
    if all(level in existing_levels for level in LEVELS):
        return {
            "ai_variants_status": "completed",
            "ai_variants_generated": 0,
            "ai_variants_failed": 0,
            "ai_levels": list(LEVELS),
            "generation_method": "existing",
            "source_hash": source_hash,
        }

    if get_settings().get("ai_content_generation_enabled"):
        fallback_summary = create_deterministic_variants(db, course, package, source_hash, reason="AI variants are generated in background")
        if background_tasks is not None:
            course.information = {
                **(course.information or {}),
                "ai_generation": {
                    **((course.information or {}).get("ai_generation") or {}),
                    "enabled": True,
                    "status": "processing",
                    "levels": list(LEVELS),
                    "source_hash": source_hash,
                    "generation_method": "processing",
                },
            }
            background_tasks.add_task(
                run_import_ai_variant_generation,
                course.id,
                package.model_dump(mode="json"),
                course.professor_id,
                source_hash,
            )
            return {
                **fallback_summary,
                "ai_variants_status": "processing",
                "generation_method": "processing",
                "ai_variants_error": None,
            }
        return create_ai_variants(db, course, package, latex_structure, source_hash, replace_fallback=True)

    return create_deterministic_variants(db, course, package, source_hash, reason="AI_CONTENT_GENERATION_ENABLED=false")


def create_deterministic_variants(
    db: Session,
    course: Course,
    package: PedagogicalPackage,
    source_hash: str,
    reason: str = "",
) -> dict:
    source_hash = normalize_source_hash(source_hash)
    by_level: dict[str, list[dict]] = {level: [] for level in LEVELS}
    subject = package.course.subject or "cours"
    for chapter in package.chapters:
        sources = sources_for_json_chapter(chapter)
        for level in LEVELS:
            payload = ai_course_generation_service.deterministic_adaptive_chapter_variant(
                chapter_source_id=chapter.id,
                chapter_title=chapter.title,
                level=level,
                sources=sources,
            ).model_dump()
            payload["subject"] = subject
            by_level[level].append(payload)

    for level, content in by_level.items():
        if variant_exists(db, course.id, level, source_hash):
            continue
        db.add(CourseLevelVariant(
            course=course,
            level=level,
            title=f"{course.title} - {level}",
            structured_content=content,
            generation_method="deterministic_fallback",
            source_hash=source_hash,
        ))

    course.information = {
        **(course.information or {}),
        "ai_generation": {
            "enabled": False,
            "status": "deterministic_fallback",
            "levels": list(LEVELS),
            "source_hash": source_hash,
            "error": reason[:500] if reason else None,
        },
    }
    return {
        "ai_variants_status": "completed",
        "ai_variants_generated": len(LEVELS),
        "ai_variants_failed": len(package.chapters) * len(LEVELS),
        "ai_levels": list(LEVELS),
        "generation_method": "deterministic_fallback",
        "ai_variants_error": reason[:500] if reason else None,
        "source_hash": source_hash,
    }


def create_ai_variants(
    db: Session,
    course: Course,
    package: PedagogicalPackage,
    latex_structure: dict,
    source_hash: str,
    replace_fallback: bool = False,
) -> dict:
    source_hash = normalize_source_hash(source_hash)
    chapter_sources = [
        {
            "chapter_source_id": chapter.id,
            "chapter_title": chapter.title,
            "sources": sources_for_json_chapter(chapter),
        }
        for chapter in package.chapters
    ]
    try:
        return create_ai_variants_from_sources(
            db,
            course,
            subject=package.course.subject or "cours",
            chapter_sources=chapter_sources,
            source_hash=source_hash,
            user_id=course.professor_id,
            replace_fallback=replace_fallback,
        )
    except Exception as exc:
        if replace_fallback:
            course.information = {
                **(course.information or {}),
                "ai_generation": {
                    "enabled": True,
                    "status": "completed",
                    "levels": list(LEVELS),
                    "source_hash": source_hash,
                    "generation_method": "deterministic_fallback",
                    "error": str(exc)[:500],
                },
            }
            return {
                "ai_variants_status": "completed",
                "ai_variants_generated": len(LEVELS),
                "ai_variants_failed": len(chapter_sources) * len(LEVELS),
                "ai_levels": list(LEVELS),
                "generation_method": "deterministic_fallback",
                "ai_variants_error": str(exc)[:500],
                "source_hash": source_hash,
            }
        return create_deterministic_variants(db, course, package, source_hash, reason=str(exc))


def create_ai_variants_from_sources(
    db: Session,
    course: Course,
    *,
    subject: str,
    chapter_sources: list[dict],
    source_hash: str,
    user_id: int | None,
    replace_fallback: bool = False,
    merge_existing: bool = False,
    selected_levels: tuple[str, ...] = LEVELS,
) -> dict:
    source_hash = normalize_source_hash(source_hash)
    if len(source_hash) != 64:
        raise ValueError("source_hash must be a 64-character SHA-256 value")
    selected_source_ids = {str(item.get("chapter_source_id")) for item in chapter_sources}
    by_level: dict[str, list[dict]] = existing_variant_content_by_level(db, course, selected_source_ids, selected_levels) if merge_existing else {level: [] for level in selected_levels}
    generation_metadata: dict[str, list[dict]] = {level: [] for level in selected_levels}
    failed_items = 0
    total_items = 0

    for chapter in chapter_sources:
        variants, metadata = ai_course_generation_service.generate_three_level_adaptive_variants(
            db,
            course_id=course.id,
            chapter_id=chapter.get("chapter_id"),
            chapter_source_id=str(chapter["chapter_source_id"]),
            chapter_title=chapter["chapter_title"],
            subject=subject,
            sources=chapter["sources"],
            user_id=user_id,
            levels=selected_levels,
        )
        for level, model in variants.items():
            if level not in selected_levels:
                continue
            total_items += 1
            payload = model.model_dump()
            payload["course_id"] = course.id
            payload["source_hash"] = source_hash
            payload["traceability"] = {
                "course_id": course.id,
                "chapter_source_id": chapter["chapter_source_id"],
                "source_block_ids": payload.get("source_block_ids", []),
                "source_hash": source_hash,
                "level": level,
                "model": payload.get("model"),
                "method": payload.get("generation_method"),
                "generated_at": payload.get("generated_at"),
            }
            if payload.get("generation_method") != "ai_generated":
                failed_items += 1
                generation_metadata[level].append(metadata.get(level, {}))
                continue
            by_level[level].append(payload)
            generation_metadata[level].append(metadata.get(level, {}))
            persist_level_variant_content(db, course, level, source_hash, by_level[level])

    ai_items = total_items - failed_items
    method = generation_method_from_counts(total_items, ai_items)
    first_generation_error = next(
        (
            str(item.get("error") or item.get("previous_error") or "")
            for items in generation_metadata.values()
            for item in items
            if isinstance(item, dict) and (item.get("error") or item.get("previous_error"))
        ),
        "",
    )

    for level, content in by_level.items():
        if variant_exists(db, course.id, level, source_hash):
            continue
        db.add(
            CourseLevelVariant(
                course=course,
                level=level,
                title=f"{course.title} - {level}",
                structured_content=content,
                generation_method=method,
                source_hash=source_hash,
            )
        )
    course.information = {
        **(course.information or {}),
        "ai_generation": {
            "enabled": True,
            "status": "completed",
            "levels": list(LEVELS),
            "selected_levels": list(selected_levels),
            "metadata": generation_metadata,
            "source_hash": source_hash,
            "generation_method": method,
            "error": first_generation_error[:500] if failed_items else None,
        },
    }
    return {
        "ai_variants_status": "completed",
        "ai_variants_generated": len(selected_levels),
        "ai_variants_failed": failed_items,
        "ai_levels": list(selected_levels),
        "generation_method": method,
        "source_hash": source_hash,
        "ai_variants_error": first_generation_error[:500] if failed_items else None,
    }


def persist_level_variant_content(
    db: Session,
    course: Course,
    level: str,
    source_hash: str,
    content: list[dict],
) -> None:
    if not hasattr(db, "scalars"):
        return
    source_hash = normalize_source_hash(source_hash)
    method = generation_method_from_content(content)
    variant = db.scalars(
        select(CourseLevelVariant)
        .where(
            CourseLevelVariant.course_id == course.id,
            CourseLevelVariant.level == level,
            CourseLevelVariant.source_hash == source_hash,
        )
        .order_by(CourseLevelVariant.id.desc())
        .limit(1)
    ).first()
    if variant is None:
        variant = CourseLevelVariant(
            course=course,
            level=level,
            title=f"{course.title} - {level}",
            structured_content=content,
            generation_method=method,
            source_hash=source_hash,
        )
        db.add(variant)
    else:
        variant.structured_content = content
        variant.generation_method = method
        variant.generated_at = datetime.utcnow()
    db.flush()
    if hasattr(db, "commit"):
        db.commit()


def generation_method_from_content(content: list[dict]) -> str:
    total_items = len([item for item in content if isinstance(item, dict)])
    ai_items = len([
        item for item in content
        if isinstance(item, dict) and item.get("generation_method") == "ai_generated"
    ])
    return generation_method_from_counts(total_items, ai_items)


def generation_method_from_counts(total_items: int, ai_items: int) -> str:
    if total_items <= 0 or ai_items <= 0:
        return "deterministic_fallback"
    if ai_items == total_items:
        return "ai_generated"
    return "mixed"


def existing_variant_content_by_level(db: Session, course: Course, replaced_source_ids: set[str], selected_levels: tuple[str, ...]) -> dict[str, list[dict]]:
    content_by_level: dict[str, list[dict]] = {level: [] for level in selected_levels}
    for level in selected_levels:
        selected_variant = course_service.serialize_selected_course_variant(db, course, level)
        content = selected_variant.get("chapters") if isinstance(selected_variant, dict) else []
        for item in content:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("chapter_source_id") or item.get("source_chapter_id") or "")
            if source_id not in replaced_source_ids:
                content_by_level[level].append(item)
    return content_by_level


def run_import_ai_variant_generation(course_id: int, package_payload: dict, user_id: int | None, source_hash: str) -> None:
    if course_id in AI_VARIANT_TASKS_IN_PROGRESS:
        return
    AI_VARIANT_TASKS_IN_PROGRESS.add(course_id)
    db = SessionLocal()
    try:
        course = db.get(Course, course_id)
        if course is None:
            return
        package = PedagogicalPackage.model_validate(package_payload)
        summary = create_ai_variants(db, course, package, {}, source_hash, replace_fallback=True)
        course.information = {
            **(course.information or {}),
            "ai_generation": {
                **((course.information or {}).get("ai_generation") or {}),
                "status": "completed",
                "generation_method": summary.get("generation_method"),
                "source_hash": source_hash,
                "completed_at": datetime.utcnow().isoformat(),
            },
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        course = db.get(Course, course_id)
        if course is not None:
            course.information = {
                **(course.information or {}),
                "ai_generation": {
                    **((course.information or {}).get("ai_generation") or {}),
                    "status": "failed",
                    "generation_method": "deterministic_fallback",
                    "error": str(exc)[:500],
                    "completed_at": datetime.utcnow().isoformat(),
                },
            }
            db.commit()
    finally:
        AI_VARIANT_TASKS_IN_PROGRESS.discard(course_id)
        db.close()


def request_course_ai_variant_regeneration(
    db: Session,
    course: Course,
    actor: UserProfile,
    background_tasks: BackgroundTasks,
) -> dict:
    if course.id in AI_VARIANT_TASKS_IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Generation IA deja en cours pour ce cours")
    info = course.information or {}
    if isinstance(info.get("ai_generation"), dict) and info["ai_generation"].get("status") == "processing":
        raise HTTPException(status_code=409, detail="Generation IA deja en cours pour ce cours")
    source_hash = source_hash_for_course(course)
    course.information = {
        **info,
        "ai_generation": {
            **(info.get("ai_generation") or {}),
            "enabled": True,
            "status": "processing",
            "levels": list(LEVELS),
            "source_hash": source_hash,
            "generation_method": "processing",
            "requested_by": actor.id,
            "requested_at": datetime.utcnow().isoformat(),
        },
    }
    db.commit()
    background_tasks.add_task(run_existing_course_ai_variant_generation, course.id, actor.id, source_hash)
    return {
        "course_id": course.id,
        "ai_variants_status": "processing",
        "generation_method": "processing",
        "source_hash": source_hash,
        "message": "Regeneration des variantes IA lancee en arriere-plan.",
    }


def request_selected_course_ai_variant_regeneration(
    db: Session,
    course: Course,
    actor: UserProfile,
    background_tasks: BackgroundTasks,
    *,
    chapter_positions: list[int],
    levels: list[str],
    replace_existing: bool = True,
) -> dict:
    clean_positions = sorted({int(position) for position in chapter_positions if int(position) > 0})
    clean_levels = [level for level in LEVELS if level in set(levels or LEVELS)]
    if not clean_positions:
        raise HTTPException(status_code=400, detail="chapter_positions doit contenir au moins une position valide")
    if not clean_levels:
        raise HTTPException(status_code=400, detail="levels doit contenir au moins un niveau valide")
    active_positions = {chapter.position for chapter in course.chapters if chapter.active}
    unknown_positions = [position for position in clean_positions if position not in active_positions]
    if unknown_positions:
        raise HTTPException(status_code=400, detail=f"Positions de chapitre introuvables: {unknown_positions}")
    task_key = selected_variant_task_key(course.id, clean_positions, clean_levels)
    if task_key in AI_VARIANT_TASKS_IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Generation IA deja en cours pour cette selection")
    source_hash = normalize_source_hash(
        json.dumps(
            {
                "course_hash": source_hash_for_course(course),
                "chapter_positions": clean_positions,
                "levels": clean_levels,
                "replace_existing": replace_existing,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    course.information = {
        **(course.information or {}),
        "ai_generation": {
            **((course.information or {}).get("ai_generation") or {}),
            "enabled": True,
            "status": "processing",
            "levels": clean_levels,
            "chapter_positions": clean_positions,
            "source_hash": source_hash,
            "generation_method": "processing",
            "requested_by": actor.id,
            "requested_at": datetime.utcnow().isoformat(),
        },
    }
    db.commit()
    background_tasks.add_task(
        run_selected_course_ai_variant_generation,
        course.id,
        actor.id,
        source_hash,
        clean_positions,
        clean_levels,
        replace_existing,
    )
    return {
        "course_id": course.id,
        "status": "processing",
        "ai_variants_status": "processing",
        "chapter_positions": clean_positions,
        "levels": clean_levels,
        "generation_method": "processing",
        "source_hash": source_hash,
    }


def selected_variant_task_key(course_id: int, positions: list[int], levels: list[str]) -> str:
    return f"{course_id}:{','.join(str(item) for item in positions)}:{','.join(levels)}"


def run_existing_course_ai_variant_generation(course_id: int, user_id: int | None, source_hash: str) -> None:
    if course_id in AI_VARIANT_TASKS_IN_PROGRESS:
        return
    AI_VARIANT_TASKS_IN_PROGRESS.add(course_id)
    db = SessionLocal()
    try:
        course = course_service.get_course_model(db, course_id)
        if course is None:
            return
        subject = course.subject.name if course.subject else course.level or "cours"
        chapter_sources = [
            {
                "chapter_id": chapter.id,
                "chapter_source_id": course_service.stable_chapter_source_id(chapter),
                "chapter_title": chapter.title,
                "sources": sources_for_course_chapter(chapter),
            }
            for chapter in course.chapters
            if chapter.active
        ]
        summary = create_ai_variants_from_sources(
            db,
            course,
            subject=subject,
            chapter_sources=chapter_sources,
            source_hash=source_hash,
            user_id=user_id,
            replace_fallback=True,
        )
        course.information = {
            **(course.information or {}),
            "ai_generation": {
                **((course.information or {}).get("ai_generation") or {}),
                "status": "completed",
                "generation_method": summary.get("generation_method"),
                "source_hash": source_hash,
                "completed_at": datetime.utcnow().isoformat(),
            },
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        course = db.get(Course, course_id)
        if course is not None:
            course.information = {
                **(course.information or {}),
                "ai_generation": {
                    **((course.information or {}).get("ai_generation") or {}),
                    "status": "failed",
                    "generation_method": "deterministic_fallback",
                    "error": str(exc)[:500],
                    "completed_at": datetime.utcnow().isoformat(),
                },
            }
            db.commit()
    finally:
        AI_VARIANT_TASKS_IN_PROGRESS.discard(course_id)
        db.close()


def run_selected_course_ai_variant_generation(
    course_id: int,
    user_id: int | None,
    source_hash: str,
    chapter_positions: list[int],
    levels: list[str],
    replace_existing: bool,
) -> None:
    task_key = selected_variant_task_key(course_id, chapter_positions, levels)
    if task_key in AI_VARIANT_TASKS_IN_PROGRESS:
        return
    AI_VARIANT_TASKS_IN_PROGRESS.add(task_key)
    db = SessionLocal()
    try:
        course = course_service.get_course_model(db, course_id)
        if course is None:
            return
        subject = course.subject.name if course.subject else course.level or "cours"
        selected_positions = set(chapter_positions)
        chapter_sources = [
            {
                "chapter_id": chapter.id,
                "chapter_source_id": course_service.stable_chapter_source_id(chapter),
                "chapter_title": chapter.title,
                "sources": sources_for_course_chapter(chapter),
            }
            for chapter in sorted(course.chapters, key=lambda item: item.position)
            if chapter.active and chapter.position in selected_positions
        ]
        summary = create_ai_variants_from_sources(
            db,
            course,
            subject=subject,
            chapter_sources=chapter_sources,
            source_hash=source_hash,
            user_id=user_id,
            replace_fallback=replace_existing,
            merge_existing=True,
            selected_levels=tuple(levels),
        )
        course.information = {
            **(course.information or {}),
            "ai_generation": {
                **((course.information or {}).get("ai_generation") or {}),
                "status": "completed",
                "generation_method": summary.get("generation_method"),
                "source_hash": source_hash,
                "chapter_positions": chapter_positions,
                "levels": levels,
                "completed_at": datetime.utcnow().isoformat(),
            },
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        course = db.get(Course, course_id)
        if course is not None:
            course.information = {
                **(course.information or {}),
                "ai_generation": {
                    **((course.information or {}).get("ai_generation") or {}),
                    "status": "failed",
                    "generation_method": "deterministic_fallback",
                    "error": str(exc)[:500],
                    "chapter_positions": chapter_positions,
                    "levels": levels,
                    "completed_at": datetime.utcnow().isoformat(),
                },
            }
            db.commit()
    finally:
        AI_VARIANT_TASKS_IN_PROGRESS.discard(task_key)
        db.close()


def source_hash_for_package(package: PedagogicalPackage) -> str:
    payload = [
        {
            "chapter_id": chapter.id,
            "title": chapter.title,
            "content_blocks": [block.model_dump() for block in chapter.content_blocks],
        }
        for chapter in sorted(package.chapters, key=lambda item: item.order)
    ]
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))


def source_hash_for_course(course: Course) -> str:
    payload = [
        {
            "chapter_id": chapter.id,
            "title": chapter.title,
            "structured_content": chapter.structured_content,
            "content": chapter.content,
        }
        for chapter in sorted(course.chapters, key=lambda item: item.position)
        if chapter.active
    ]
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))


def variant_exists(db: Session, course_id: int, level: str, source_hash: str) -> bool:
    source_hash = normalize_source_hash(source_hash)
    return db.scalar(
        select(CourseLevelVariant.id).where(
            CourseLevelVariant.course_id == course_id,
            CourseLevelVariant.level == level,
            CourseLevelVariant.source_hash == source_hash,
        )
    ) is not None


def normalize_source_hash(value: Any) -> str:
    raw = str(value or "")
    if re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        return raw.lower()
    return sha256(raw.encode("utf-8"))


def sources_for_json_chapter(chapter) -> list[dict]:
    sources = []
    for index, block in enumerate(chapter.content_blocks, start=1):
        text = block.content or block.question or block.solution or block.answer or ""
        if text:
            source_block_id = block.id or f"{chapter.id}_json_{index}"
            source_payload = block.model_dump()
            sources.append(
                {
                    "id": source_block_id,
                    "source_block_id": source_block_id,
                    "source_chapter_id": chapter.id,
                    "type": block.type,
                    "original_block_type": block.type,
                    "title": getattr(block, "title", "") or "",
                    "section": getattr(block, "section", "") or (source_payload.get("metadata") or {}).get("section", ""),
                    "metadata": source_payload.get("metadata") or {},
                    "text": text,
                    "source_hash": sha256(json.dumps(source_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")),
                }
            )
    return sources


def sources_for_course_chapter(chapter: CourseChapter) -> list[dict]:
    blocks = chapter.structured_content or []
    if isinstance(blocks, dict):
        blocks = blocks.get("blocks") or blocks.get("source_blocks") or [blocks]
    if not isinstance(blocks, list):
        blocks = []
    sources = []
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            continue
        content = block.get("content")
        if isinstance(content, (dict, list)):
            text = json.dumps(content, ensure_ascii=False, default=str)
        else:
            text = str(content or block.get("text") or block.get("question") or block.get("solution") or "")
        if not text:
            continue
        source_block_id = str(block.get("id") or block.get("source_block_id") or f"{chapter.id}_db_{index}")
        source_payload = {
            "chapter_id": chapter.id,
            "block": block,
            "content": text,
        }
        sources.append(
            {
                "id": source_block_id,
                "source_block_id": source_block_id,
                "source_chapter_id": str(chapter.id),
                "type": block.get("type") or "paragraph",
                "original_block_type": block.get("original_block_type") or block.get("type") or "paragraph",
                "title": block.get("title") or chapter.title,
                "section": block.get("section") or "",
                "metadata": block.get("metadata") or {},
                "text": text,
                "source_hash": block.get("source_hash") or sha256(json.dumps(source_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")),
            }
        )
    if not sources and chapter.content:
        sources.append(
            {
                "id": f"{chapter.id}_content",
                "source_block_id": f"{chapter.id}_content",
                "source_chapter_id": str(chapter.id),
                "type": "paragraph",
                "original_block_type": "paragraph",
                "title": chapter.title,
                "section": "content",
                "metadata": {},
                "text": chapter.content,
                "source_hash": sha256(chapter.content.encode("utf-8")),
            }
        )
    return sources


def sources_for_ai_chapter(chapter, latex_structure: dict) -> list[dict]:
    sources = []
    for index, block in enumerate(chapter.content_blocks, start=1):
        text = block.content or block.question or ""
        if text:
            sources.append(
                {
                    "id": block.id or f"{chapter.id}_json_{index}",
                    "source_block_id": block.id or f"{chapter.id}_json_{index}",
                    "type": block.type,
                    "text": text,
                }
            )
    for index, block in enumerate(latex_structure.get("sections", {}).get(normalize_ref(chapter.latex_reference or ""), []), start=1):
        text = block.get("content") or ""
        if text:
            sources.append(
                {
                    "id": f"{chapter.id}_latex_{index}",
                    "source_block_id": f"{chapter.id}_latex_{index}",
                    "type": block.get("type", "paragraph"),
                    "text": text,
                }
            )
    return sources


def create_quiz(
    db: Session,
    course: Course,
    package: PedagogicalPackage,
    chapter_by_source: dict[str, CourseChapter],
) -> int:
    target_count = max(5, min(int(os.getenv("AUTO_IMPORT_QUIZ_QUESTIONS", "20")), 50))
    questions = build_quiz_questions_from_json(
        package,
        chapter_by_source,
        target_count=target_count,
    )
    if len(questions) < 4:
        raise HTTPException(
            status_code=422,
            detail=(
                "Le JSON doit contenir au moins 4 questions QCM explicites "
                "avec question, choices, answer et explanation. "
                "Les questions ouvertes restent dans Entrainement."
            ),
        )

    quiz = Quiz(
        course=course,
        title=f"Quiz - {course.title}",
        description=(
            f"Quiz de {len(questions)} QCM fournis explicitement dans le JSON du professeur."
        ),
        passing_score=package.assessment_blueprint.passing_score,
        active=True,
        published=True,
        questions=[
            QuizQuestion(
                question=item["question"],
                choices=item["choices"],
                answer=item["correct_answer"],
                explanation=item["explanation"],
                chapter_id=item["chapter_id"],
                position=index,
                active=True,
            )
            for index, item in enumerate(questions, start=1)
        ],
    )
    course.quiz = quiz
    db.add(quiz)
    return len(questions)


def create_assessments(db: Session, professor: UserProfile, classroom: Classroom, course: Course, package: PedagogicalPackage, subject_id: int, chapter_by_source: dict[str, CourseChapter]) -> list[Assessment]:
    assessments = []
    for level in LEVELS:
        assessment = Assessment(
            professor_id=professor.id,
            classroom_id=classroom.id,
            course_id=course.id,
            subject_id=subject_id,
            title=f"{course.title} - Evaluation {level}",
            description="Evaluation adaptee generee automatiquement.",
            instructions="Repondez aux questions selon votre niveau actuel.",
            assessment_type="initial",
            status="published",
            publication_at=datetime.utcnow(),
            time_limit_minutes=package.assessment_blueprint.duration_minutes,
            max_attempts=package.assessment_blueprint.max_attempts,
        )
        db.add(assessment)
        db.flush()
        for index, item in enumerate(build_questions(package, chapter_by_source, level, package.assessment_blueprint.questions_per_assessment), start=1):
            db.add(AssessmentQuestion(
                assessment_id=assessment.id,
                chapter_id=item["chapter_id"],
                skill_id=item["skill_id"],
                question=item["question"],
                choices=item["choices"],
                correct_answer=item["correct_answer"],
                explanation=item["explanation"],
                points=item["points"],
                order_index=index,
                active=True,
                generation_method="automatic_import",
                adaptation_reason=f"Question generee pour le niveau {level}.",
            ))
        assessments.append(assessment)
    return assessments



def build_quiz_questions_from_json(
    package: PedagogicalPackage,
    chapter_by_source: dict[str, CourseChapter],
    target_count: int = 20,
) -> list[dict]:
    """Use only explicit professor-authored MCQs from the uploaded JSON."""

    candidates: list[dict] = []

    for chapter in sorted(package.chapters, key=lambda item: item.order):
        db_chapter = chapter_by_source.get(chapter.id)
        if db_chapter is None:
            continue

        for block_index, block_model in enumerate(chapter.content_blocks, start=1):
            block = block_model.model_dump()
            block_type = str(block.get("type") or "").strip().lower()
            if block_type not in {"quiz", "mcq", "qcm"}:
                continue

            metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else {}
            question_text_value = clean_source_question_text(
                str(block.get("question") or block.get("content") or "")
            )
            choices = unique_keep_order(
                [
                    str(choice).strip()
                    for choice in (block.get("choices") or [])
                    if str(choice).strip()
                ]
            )
            correct_answer = str(block.get("answer") or "").strip()
            explanation = str(
                block.get("explanation")
                or block.get("solution")
                or correct_answer
            ).strip()

            if not question_text_value or len(choices) < 2 or not correct_answer:
                continue

            normalized_choices = {normalize_text(choice): choice for choice in choices}
            matched_answer = normalized_choices.get(normalize_text(correct_answer))
            if matched_answer is None:
                continue
            correct_answer = matched_answer

            question_id = str(
                block.get("id")
                or metadata.get("question_id")
                or f"{chapter.id}_mcq_{block_index}"
            ).strip()

            candidates.append(
                {
                    "source_question_id": question_id,
                    "chapter_source_id": chapter.id,
                    "chapter_order": chapter.order,
                    "chapter_id": db_chapter.id,
                    "question_number": source_question_number(
                        question_id,
                        block.get("title"),
                        question_text_value,
                    ),
                    "question": question_text_value,
                    "correct_answer": correct_answer,
                    "explanation": explanation,
                    "points": float(metadata.get("points") or 1),
                    "choices": deterministic_source_choice_order(
                        choices[:4],
                        question_id,
                    ),
                }
            )

    selected = select_balanced_source_questions(candidates, target_count)
    return [
        {
            "question": candidate["question"],
            "choices": candidate["choices"],
            "correct_answer": candidate["correct_answer"],
            "explanation": candidate["explanation"],
            "points": candidate["points"],
            "chapter_id": candidate["chapter_id"],
            "skill_id": None,
            "source_question_id": candidate["source_question_id"],
            "generation_method": "source_json_explicit_mcq",
        }
        for candidate in selected
    ]


def select_balanced_source_questions(candidates: list[dict], target_count: int) -> list[dict]:
    """Round-robin selection: distribute the quiz across all chapters."""

    by_chapter: dict[str, list[dict]] = {}
    chapter_order: list[str] = []

    for candidate in sorted(
        candidates,
        key=lambda item: (
            item["chapter_order"],
            item["question_number"],
            item["source_question_id"],
        ),
    ):
        chapter_key = candidate["chapter_source_id"]
        if chapter_key not in by_chapter:
            by_chapter[chapter_key] = []
            chapter_order.append(chapter_key)
        by_chapter[chapter_key].append(candidate)

    selected: list[dict] = []
    position = 0
    while len(selected) < target_count:
        added = False
        for chapter_key in chapter_order:
            questions = by_chapter[chapter_key]
            if position < len(questions):
                selected.append(questions[position])
                added = True
                if len(selected) >= target_count:
                    break
        if not added:
            break
        position += 1

    return selected


def build_source_json_choices(candidate: dict, all_candidates: list[dict]) -> tuple[list[str], str]:
    """Use choices and corrections already present in JSON; do not use outside knowledge."""

    full_answer = candidate["correct_answer_full"]
    correct_answer = concise_source_answer(full_answer)

    explicit_choices = unique_keep_order(candidate.get("explicit_choices") or [])
    if explicit_choices:
        choices = explicit_choices
        if normalize_text(correct_answer) not in {normalize_text(item) for item in choices}:
            matching_full = next(
                (
                    item
                    for item in choices
                    if normalize_text(item) == normalize_text(full_answer)
                ),
                None,
            )
            if matching_full:
                correct_answer = matching_full
            else:
                choices.append(correct_answer)
        return deterministic_source_choice_order(
            unique_keep_order(choices)[:4],
            candidate["source_question_id"],
        ), correct_answer

    distractor_pool: list[str] = []

    # Prefer answers to the same question number in other chapters.
    for other in all_candidates:
        if other["source_question_id"] == candidate["source_question_id"]:
            continue
        if other["question_number"] != candidate["question_number"]:
            continue
        distractor_pool.append(concise_source_answer(other["correct_answer_full"]))

    # Complete only with other answers from the same uploaded JSON.
    for other in all_candidates:
        if len(unique_keep_order(distractor_pool)) >= 8:
            break
        if other["source_question_id"] == candidate["source_question_id"]:
            continue
        distractor_pool.append(concise_source_answer(other["correct_answer_full"]))

    distractors = [
        item
        for item in unique_keep_order(distractor_pool)
        if normalize_text(item) != normalize_text(correct_answer)
    ][:3]

    choices = unique_keep_order([correct_answer, *distractors])
    return deterministic_source_choice_order(
        choices,
        candidate["source_question_id"],
    ), correct_answer


def deterministic_source_choice_order(choices: list[str], seed: str) -> list[str]:
    return sorted(
        unique_keep_order(choices),
        key=lambda value: sha256(f"{seed}|{value}".encode("utf-8")),
    )


def clean_source_question_text(value: str) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""

    if re.match(
        r"^question\s*\d+\s*(?:[—–-]\s*\d+(?:[.,]\d+)?\s*pt(?:\(s\))?)?\s*$",
        lines[0],
        flags=re.IGNORECASE,
    ):
        lines = lines[1:]

    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def parse_source_correction(value: str) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""

    answer_match = re.search(
        r"(?is)r[ée]ponse\s*:\s*(.+?)(?=\n\s*explication\s*:|$)",
        text,
    )
    explanation_match = re.search(
        r"(?is)explication\s*:\s*(.+)$",
        text,
    )

    answer = answer_match.group(1).strip() if answer_match else text
    explanation = (
        explanation_match.group(1).strip()
        if explanation_match
        else answer
    )
    return answer, explanation


def source_question_number(question_id: str, title: Any, raw_question: str) -> int:
    for value in (question_id, str(title or ""), raw_question):
        match = re.search(r"(?:q|question)[_\s-]*(\d+)", value, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 999


def concise_source_answer(value: str, limit: int = 230) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text

    shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{shortened}…"


def build_questions(package: PedagogicalPackage, chapter_by_source: dict[str, CourseChapter], level: str, count: int) -> list[dict]:
    base_questions = []
    for chapter in sorted(package.chapters, key=lambda item: item.order):
        db_chapter = chapter_by_source[chapter.id]
        skill_name = chapter.skills[0]
        skill_id = db_chapter.id and None
        context = first_text(chapter.content_blocks) or chapter.title
        correct = shorten(context, 80)
        choices = unique_keep_order([
            correct,
            f"Un element secondaire de {chapter.title}",
            f"Une interpretation non justifiee",
            f"Une information absente du cours",
        ])
        while len(choices) < 4:
            choices.append(f"Choix {len(choices) + 1}")
        base_questions.append({
            "question": question_text(level, chapter.title),
            "choices": choices[:4],
            "correct_answer": correct,
            "explanation": f"La reponse est fondee sur le chapitre {chapter.title} et sur les sources importees.",
            "points": 1,
            "chapter_id": db_chapter.id,
            "skill_id": skill_id,
        })
    generated = []
    seen = set()
    index = 0
    while len(generated) < max(2, count):
        source = base_questions[index % len(base_questions)]
        variant = dict(source)
        variant["question"] = f"{source['question']} ({len(generated) + 1})"
        normalized = normalize_text(variant["question"])
        if normalized not in seen:
            seen.add(normalized)
            generated.append(variant)
        index += 1
    return generated[:count]


def assign_assessments(db: Session, assessments: list[Assessment], classroom: Classroom) -> int:
    active_members = list(db.scalars(select(ClassroomMembership).where(ClassroomMembership.classroom_id == classroom.id, ClassroomMembership.active.is_(True))))
    created = 0
    for assessment in assessments:
        for membership in active_members:
            exists = db.scalars(select(AssessmentAssignment).where(AssessmentAssignment.assessment_id == assessment.id, AssessmentAssignment.student_id == membership.student_id)).first()
            if exists:
                continue
            db.add(AssessmentAssignment(assessment_id=assessment.id, student_id=membership.student_id, classroom_id=classroom.id, status="assigned"))
            db.add(Notification(id=f"assessment-{assessment.id}-{membership.student_id}", user_id=membership.student_id, type="assessment", title="Evaluation disponible", message=f"{assessment.title} est disponible."))
            created += 1
    return created


def assign_course_to_classroom(db: Session, course_id: int, classroom: Classroom, professor: UserProfile) -> dict:
    existing = db.scalars(
        select(ClassroomCourseAssignment).where(
            ClassroomCourseAssignment.classroom_id == classroom.id,
            ClassroomCourseAssignment.course_id == course_id,
        )
    ).first()
    created = 0
    if existing:
        existing.active = True
        existing.assigned_by = existing.assigned_by or professor.id
    else:
        db.add(
            ClassroomCourseAssignment(
                classroom_id=classroom.id,
                course_id=course_id,
                assigned_by=professor.id,
                active=True,
            )
        )
        created = 1

    students_with_access = db.scalar(
        select(ClassroomMembership.id)
        .join(Classroom, Classroom.id == ClassroomMembership.classroom_id)
        .where(
            ClassroomMembership.classroom_id == classroom.id,
            ClassroomMembership.active.is_(True),
            Classroom.active.is_(True),
        )
        .limit(1)
    )
    access_count = db.query(ClassroomMembership).filter(
        ClassroomMembership.classroom_id == classroom.id,
        ClassroomMembership.active.is_(True),
    ).count() if students_with_access is not None else 0

    return {
        "course_classroom_assignments": created,
        "students_with_course_access": access_count,
    }


def empty_course_assignment_summary() -> dict:
    return {
        "course_classroom_assignments": 0,
        "students_with_course_access": 0,
    }


def refresh_existing_job_summary(db: Session, job: PedagogicalPackageImportJob) -> None:
    if not job.course_id:
        return
    chapter_count = count_course_chapters(db, job.course_id)
    job.chapters_count = chapter_count
    result_summary = job.result_summary if isinstance(job.result_summary, dict) else {}
    source_summary = job.source_summary if isinstance(job.source_summary, dict) else {}
    job.result_summary = {
        **result_summary,
        "chapters_count": chapter_count,
        "visuals_count": result_summary.get("visuals_count", source_summary.get("visuals_count", 0)),
        "regional_exams_count": result_summary.get("regional_exams_count", source_summary.get("regional_exams_count", 0)),
    }


def count_course_chapters(db: Session, course_id: int) -> int:
    return db.query(CourseChapter).filter(CourseChapter.course_id == course_id).count()


def count_visual_specs(package: PedagogicalPackage) -> int:
    return len(collect_visual_specs(package))


def collect_visual_specs(package: PedagogicalPackage) -> list[dict]:
    visuals: list[dict] = []
    for visual in package.visuals:
        visuals.append(visual.model_dump())
    for chapter in package.chapters:
        for visual in chapter.visuals:
            payload = visual.model_dump()
            if not payload.get("chapter_id") and not payload.get("chapter_ref") and not payload.get("source_ref"):
                payload["chapter_id"] = chapter.id
            visuals.append(payload)
    return visuals


def visual_specs_for_chapter(package: PedagogicalPackage, chapter_id: str, latex_reference: str | None) -> list[dict]:
    keys = {normalize_ref(chapter_id)}
    if latex_reference:
        keys.add(normalize_ref(latex_reference))
    selected: list[dict] = []
    for visual in collect_visual_specs(package):
        refs = [
            visual.get("chapter_id"),
            visual.get("chapter_ref"),
            visual.get("source_ref"),
        ]
        normalized_refs = {normalize_ref(str(ref)) for ref in refs if ref}
        if normalized_refs & keys:
            selected.append(visual)
    return selected


def count_regional_exam_items(package: PedagogicalPackage) -> int:
    if not package.regional_exam_bank:
        return 0
    return len(package.regional_exam_bank.items)


def create_regional_profiles(db: Session, package: PedagogicalPackage, classroom: Classroom) -> None:
    members = list(db.scalars(select(ClassroomMembership).where(ClassroomMembership.classroom_id == classroom.id, ClassroomMembership.active.is_(True))))
    for membership in members:
        student = membership.student
        student.school_year = "1ere Bac"
        student.academic_year = package.target.academic_year
        student.study_stream = package.target.stream
        student.region = package.target.region
        student.prepared_subjects = [package.course.subject]
        existing = db.scalars(
            select(RegionalExamProfile).where(
                RegionalExamProfile.student_id == membership.student_id,
                RegionalExamProfile.academic_year == package.target.academic_year,
                RegionalExamProfile.region == package.target.region,
                RegionalExamProfile.stream == package.target.stream,
            )
        ).first()
        if existing:
            continue
        db.add(RegionalExamProfile(
            student_id=membership.student_id,
            country=package.target.country,
            cycle=package.target.cycle,
            academic_year=package.target.academic_year,
            region=package.target.region,
            stream=package.target.stream,
            exam_type=package.target.exam_type,
            prepared_subjects=[package.course.subject],
            readiness_details={"source": "automatic_import", "works": [work.title for work in package.works]},
        ))


def ensure_skill(db: Session, course: Course, chapter: CourseChapter, name: str) -> Skill:
    skill = db.scalars(select(Skill).where(Skill.course_id == course.id, Skill.chapter_id == chapter.id, Skill.name == name)).first()
    if skill:
        return skill
    skill = Skill(subject_id=course.subject_id, course_id=course.id, chapter_id=chapter.id, name=name, description=f"Competence importee: {name}")
    db.add(skill)
    db.flush()
    return skill


def serialize_job(job: PedagogicalPackageImportJob) -> dict:
    result_summary = job.result_summary or {}
    return {
        "id": job.id,
        "status": job.status,
        "course_id": job.course_id,
        "classroom_id": job.classroom_id,
        "subject_id": job.subject_id,
        "education_level_id": job.education_level_id,
        "academic_year": job.academic_year,
        "is_current": job.is_current,
        "schema_version": job.schema_version,
        "source_summary": job.source_summary or {},
        "result_summary": result_summary,
        "error_message": job.error_message,
        "chapters_count": job.chapters_count,
        "visuals_count": result_summary.get("visuals_count", 0) if isinstance(result_summary, dict) else 0,
        "regional_exams_count": result_summary.get("regional_exams_count", 0) if isinstance(result_summary, dict) else 0,
        "variants_count": job.variants_count,
        "questions_count": job.questions_count,
        "assigned_students_count": job.assigned_students_count,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(value).name)[:240]


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-") or "item"


def catalog_slug(value: str) -> str:
    clean = slugify(value)
    if clean in {"francais", "francais-fr"}:
        return "francais"
    if clean in {"1ere-annee-baccalaureat", "premiere-annee-baccalaureat", "1ere-bac", "premiere-bac"}:
        return "1ere_bac"
    return clean


def normalize_ref(value: str) -> str:
    return slugify(value.replace("_", "-"))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", value.lower())).strip()


def unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        clean = str(item).strip()
        key = normalize_text(clean)
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def first_text(blocks) -> str:
    for block in blocks:
        text = block.content or block.question or ""
        if text.strip():
            return text.strip()
    return ""


def shorten(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit].rstrip() or "Information presente dans le cours"


def plain_text_from_blocks(blocks: list[dict]) -> str:
    return "\n\n".join(str(block.get("content") or block.get("question") or "") for block in blocks if block.get("content") or block.get("question"))


def extract_blocks(package: PedagogicalPackage, block_type: str) -> list[dict]:
    return [
        block.model_dump()
        for chapter in package.chapters
        for block in chapter.content_blocks
        if block.type == block_type
    ]


def level_variant_tone(level: str) -> dict:
    return {
        "debutant": {"label": "Debutant", "guidance": "Explication simple, vocabulaire explique, aide visible."},
        "intermediaire": {"label": "Intermediaire", "guidance": "Analyse guidee, liens entre idees et exercices semi-guides."},
        "avance": {"label": "Avance", "guidance": "Analyse litteraire, argumentation et contraintes proches du regional."},
    }[level]


def adapt_text(value: str, level: str) -> str:
    if level == "debutant":
        return f"Version simple: {shorten(value, 180)}"
    if level == "avance":
        return f"Version avancee: analysez, justifiez et reliez aux themes. Source: {shorten(value, 220)}"
    return f"Version intermediaire: expliquez les liens importants. Source: {shorten(value, 200)}"


def question_text(level: str, chapter_title: str) -> str:
    if level == "debutant":
        return f"Quel element explicite faut-il retenir dans {chapter_title} ?"
    if level == "avance":
        return f"Quelle interpretation argumentee correspond le mieux a {chapter_title} ?"
    return f"Quelle relation importante apparait dans {chapter_title} ?"
