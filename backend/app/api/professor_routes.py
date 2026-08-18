from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_professor_or_admin
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.schemas.course_adaptation import CourseImportAdaptRequest, CourseImportPublishRequest, CourseImportSectionUpdate
from app.services import automatic_course_generation_service, content_import_service, professor_service, rag_document_service
from app.services import course_adaptation_nlp_service

router = APIRouter(prefix="/professor", tags=["Professor"])


@router.get("/dashboard")
def get_professor_dashboard(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return professor_service.get_dashboard(db, current_user)


@router.get("/students")
def get_professor_students(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> list[dict]:
    return professor_service.list_tracked_students(db, current_user)


@router.get("/students/{student_id}")
def get_professor_student_detail(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return professor_service.get_tracked_student_detail(db, current_user, student_id)


@router.get("/courses")
def get_professor_courses(
    search: str = "",
    subject_id: int | None = None,
    education_level_id: int | None = None,
    difficulty_level_id: int | None = None,
    status: str = Query(default=""),
    published: bool | None = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.list_courses(
        db,
        current_user,
        search=search,
        subject_id=subject_id,
        education_level_id=education_level_id,
        difficulty_level_id=difficulty_level_id,
        status_filter=status,
        published=published,
    )


@router.post("/courses/automatic-import")
def import_professor_course_package(
    background_tasks: BackgroundTasks,
    json_file: UploadFile = File(...),
    latex_file: UploadFile | None = File(default=None),
    classroom_id: int = Form(...),
    auto_assign: bool = Form(default=True),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return automatic_course_generation_service.import_package(
        db,
        current_user,
        json_file=json_file,
        latex_file=latex_file,
        classroom_id=classroom_id,
        auto_assign=auto_assign,
        background_tasks=background_tasks,
    )


@router.post("/courses/{course_id}/regenerate-ai-variants")
def regenerate_professor_course_ai_variants(
    course_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    course = professor_service.get_professor_owned_course(db, current_user, course_id)
    return automatic_course_generation_service.request_course_ai_variant_regeneration(
        db,
        course,
        current_user,
        background_tasks,
    )


@router.post("/courses/{course_id}/regenerate-selected-ai-variants")
def regenerate_selected_professor_course_ai_variants(
    course_id: int,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    course = professor_service.get_professor_owned_course(db, current_user, course_id)
    return automatic_course_generation_service.request_selected_course_ai_variant_regeneration(
        db,
        course,
        current_user,
        background_tasks,
        chapter_positions=payload.get("chapter_positions") or [],
        levels=payload.get("levels") or ["debutant", "intermediaire", "avance"],
        replace_existing=bool(payload.get("replace_existing", True)),
    )


@router.get("/courses/automatic-import/{job_id}")
def get_professor_course_package_import_status(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return automatic_course_generation_service.get_job(db, current_user, job_id)


@router.post("/course-imports/analyze")
def analyze_professor_course_import(
    json_file: UploadFile = File(...),
    latex_file: UploadFile | None = File(default=None),
    classroom_id: int = Form(...),
    subject_id: int | None = Form(default=None),
    education_level_id: int | None = Form(default=None),
    adaptation_mode: str = Form(default="automatic_class"),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return course_adaptation_nlp_service.analyze_import(
        db,
        current_user,
        json_file=json_file,
        latex_file=latex_file,
        classroom_id=classroom_id,
        subject_id=subject_id,
        education_level_id=education_level_id,
        adaptation_mode=adaptation_mode,
    )


@router.get("/course-imports/{job_id}")
def get_professor_course_import_workflow(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return course_adaptation_nlp_service.preview_import(db, current_user, job_id)


@router.post("/course-imports/{job_id}/adapt")
def adapt_professor_course_import(
    job_id: int,
    payload: CourseImportAdaptRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return course_adaptation_nlp_service.adapt_import(
        db,
        current_user,
        job_id,
        mode=payload.mode,
        target_levels=payload.target_levels,
    )


@router.get("/course-imports/{job_id}/preview")
def preview_professor_course_import(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return course_adaptation_nlp_service.preview_import(db, current_user, job_id)


@router.patch("/course-imports/{job_id}/sections/{section_id}")
def update_professor_course_import_section(
    job_id: int,
    section_id: str,
    payload: CourseImportSectionUpdate,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return course_adaptation_nlp_service.update_section(
        db,
        current_user,
        job_id,
        section_id,
        payload.model_dump(exclude_none=True),
    )


@router.post("/course-imports/{job_id}/validate")
def validate_professor_course_import(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return course_adaptation_nlp_service.validate_import(db, current_user, job_id)


@router.post("/course-imports/{job_id}/publish")
def publish_professor_course_import(
    job_id: int,
    payload: CourseImportPublishRequest,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return course_adaptation_nlp_service.publish_import(
        db,
        current_user,
        job_id,
        auto_assign=payload.auto_assign,
        adaptation_ids=payload.adaptation_ids,
    )


@router.post("/courses")
def create_professor_course(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.create_course(db, current_user, payload)


@router.get("/courses/{course_id}")
def get_professor_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    course = professor_service.get_professor_owned_course(db, current_user, course_id)
    return professor_service.serialize_professor_course(course)


@router.put("/courses/{course_id}")
def update_professor_course(
    course_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.update_course(db, current_user, course_id, payload)


@router.delete("/courses/{course_id}")
def delete_professor_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.delete_course(db, current_user, course_id)


@router.post("/courses/{course_id}/publish")
def publish_professor_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.publish_course(db, current_user, course_id)


@router.post("/courses/{course_id}/unpublish")
def unpublish_professor_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.unpublish_course(db, current_user, course_id)


@router.post("/courses/{course_id}/archive")
def archive_professor_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.archive_course(db, current_user, course_id)


@router.get("/courses/{course_id}/chapters")
def get_professor_chapters(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.list_chapters(db, current_user, course_id)


@router.post("/courses/{course_id}/chapters")
def create_professor_chapter(
    course_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.create_chapter(db, current_user, course_id, payload)


@router.put("/courses/{course_id}/chapters/{chapter_id}")
def update_professor_chapter(
    course_id: int,
    chapter_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.update_chapter(db, current_user, course_id, chapter_id, payload)


@router.delete("/courses/{course_id}/chapters/{chapter_id}")
def delete_professor_chapter(
    course_id: int,
    chapter_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.delete_chapter(db, current_user, course_id, chapter_id)


@router.post("/courses/{course_id}/chapters/reorder")
def reorder_professor_chapters(
    course_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.reorder_chapters(db, current_user, course_id, payload)


@router.put("/courses/{course_id}/objectives")
def replace_professor_objectives(
    course_id: int,
    payload: list,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.replace_items(db, current_user, course_id, "objectives", payload)


@router.put("/courses/{course_id}/skills")
def replace_professor_skills(
    course_id: int,
    payload: list,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.replace_items(db, current_user, course_id, "skills", payload)


@router.put("/courses/{course_id}/examples")
def replace_professor_examples(
    course_id: int,
    payload: list,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.replace_items(db, current_user, course_id, "examples", payload)


@router.get("/courses/{course_id}/quizzes")
def get_professor_quizzes(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.get_quizzes(db, current_user, course_id)


@router.post("/courses/{course_id}/quizzes")
def create_professor_quiz(
    course_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.create_quiz(db, current_user, course_id, payload)


@router.get("/quizzes/{quiz_id}")
def get_professor_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.get_quiz(db, current_user, quiz_id)


@router.put("/quizzes/{quiz_id}")
def update_professor_quiz(
    quiz_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.update_quiz(db, current_user, quiz_id, payload)


@router.delete("/quizzes/{quiz_id}")
def delete_professor_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.delete_quiz(db, current_user, quiz_id)


@router.post("/quizzes/{quiz_id}/questions")
def create_professor_question(
    quiz_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.add_question(db, current_user, quiz_id, payload)


@router.put("/quizzes/{quiz_id}/questions/{question_id}")
def update_professor_question(
    quiz_id: int,
    question_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.update_question(db, current_user, quiz_id, question_id, payload)


@router.delete("/quizzes/{quiz_id}/questions/{question_id}")
def delete_professor_question(
    quiz_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.delete_question(db, current_user, quiz_id, question_id)


@router.post("/quizzes/{quiz_id}/questions/reorder")
def reorder_professor_questions(
    quiz_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.reorder_questions(db, current_user, quiz_id, payload)


@router.post("/courses/{course_id}/document")
def upload_professor_document(
    course_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.upload_document(db, current_user, course_id, file)


@router.delete("/courses/{course_id}/document")
def delete_professor_document(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.delete_document(db, current_user, course_id)


@router.get("/courses/{course_id}/students")
def get_professor_course_students(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.get_students(db, current_user, course_id)


@router.get("/courses/{course_id}/analytics")
def get_professor_course_analytics(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.get_analytics(db, current_user, course_id)


@router.post("/courses/{course_id}/content/import-from-pdf")
def import_professor_content_from_pdf(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return content_import_service.build_content_from_pdf(db, current_user, course_id)


@router.get("/courses/{course_id}/content/import-status")
def get_professor_content_import_status(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return content_import_service.get_import_status(db, current_user, course_id)


@router.post("/courses/{course_id}/rag/index")
def index_professor_course_rag(
    course_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    professor_service.get_professor_owned_course(db, current_user, course_id)
    document = rag_document_service.get_active_document_for_course(db, course_id)
    if document is None:
        return {"error": "Aucun PDF a indexer", "course_id": course_id}
    job = rag_document_service.request_index_document(db, document.id, current_user, "index")
    background_tasks.add_task(rag_document_service.run_job_by_id, job["id"])
    return job


@router.post("/courses/{course_id}/rag/reindex")
def reindex_professor_course_rag(
    course_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    professor_service.get_professor_owned_course(db, current_user, course_id)
    document = rag_document_service.get_active_document_for_course(db, course_id)
    if document is None:
        return {"error": "Aucun PDF a reindexer", "course_id": course_id}
    job = rag_document_service.request_index_document(db, document.id, current_user, "reindex")
    background_tasks.add_task(rag_document_service.run_job_by_id, job["id"])
    return job


@router.get("/courses/{course_id}/rag/status")
def get_professor_course_rag_status(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    professor_service.get_professor_owned_course(db, current_user, course_id)
    return rag_document_service.get_course_rag_status(db, course_id)


@router.get("/rag/jobs")
def get_professor_rag_jobs(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return rag_document_service.list_jobs(db, current_user, professor_only=True)


@router.get("/analytics")
def get_professor_analytics(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
):
    return professor_service.get_analytics(db, current_user)
