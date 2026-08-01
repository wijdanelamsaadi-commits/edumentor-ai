from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_admin
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.schemas.admin import AdminStatsOverview, AdminUserRead, CourseProfessorAssignment, RoleUpdate, StatusUpdate
from app.schemas.catalog import SubjectPayload
from app.services import admin_rag_service, admin_service, catalog_service, course_service, diagnostic_service, rag_document_service

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/stats/overview", response_model=AdminStatsOverview)
def get_admin_overview(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.get_overview(db)


@router.get("/users", response_model=list[AdminUserRead])
def get_admin_users(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.list_users(db)


@router.get("/users/{user_id}", response_model=AdminUserRead)
def get_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.get_user(db, user_id)


@router.get("/parents/links")
def get_admin_parent_student_links(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.list_parent_student_links(db)


@router.post("/parents/links")
def create_admin_parent_student_link(
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.create_parent_student_link(db, current_admin, payload)


@router.get("/parents/notifications")
def get_admin_parent_notifications(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.list_parent_notifications(db)


@router.post("/parents/notifications/deliveries/{delivery_id}/retry")
def retry_admin_parent_notification_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.retry_parent_notification_delivery(db, current_admin, delivery_id)


@router.put("/users/{user_id}/role", response_model=AdminUserRead)
def update_admin_user_role(
    user_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.update_user_role(db, current_admin, user_id, payload.role)


@router.put("/users/{user_id}/status", response_model=AdminUserRead)
def update_admin_user_status(
    user_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.update_user_status(db, current_admin, user_id, payload.status)


@router.get("/stats/users")
def get_admin_users_stats(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.get_users_stats(db)


@router.get("/stats/courses")
def get_admin_courses_stats(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.get_courses_stats(db)


@router.get("/stats/quizzes")
def get_admin_quizzes_stats(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.get_quizzes_stats(db)


@router.get("/stats/chatbot")
def get_admin_chatbot_stats(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.get_chatbot_stats(db)


@router.get("/rag/status")
def get_admin_rag_status(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return {
        **admin_rag_service.get_admin_rag_status(),
        "documents": rag_document_service.list_documents(db)[:20],
        "global": rag_document_service.get_public_status(db),
    }


@router.post("/rag/reindex")
def reindex_admin_rag(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    started = admin_rag_service.mark_reindex_started()
    if started:
        documents = rag_document_service.list_documents(db)
        for document in documents:
            if document.get("active"):
                job = rag_document_service.request_index_document(db, document["id"], current_admin, "reindex")
                background_tasks.add_task(rag_document_service.run_job_by_id, job["id"])
        background_tasks.add_task(admin_rag_service.mark_reindex_finished)
        admin_service.create_audit_log(
            db,
            current_admin.id,
            "reindex_rag",
            "rag",
            "course_documents",
            None,
            {"state": "running", "documents": len(documents)},
        )
    return admin_rag_service.get_admin_rag_status()


@router.get("/rag/documents")
def get_admin_rag_documents(
    subject_id: int | None = None,
    course_id: int | None = None,
    professor_id: int | None = None,
    status: str = "",
    search: str = "",
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return rag_document_service.list_documents(
        db,
        {
            "subject_id": subject_id,
            "course_id": course_id,
            "professor_id": professor_id,
            "status": status,
            "search": search,
        },
    )


@router.get("/rag/jobs")
def get_admin_rag_jobs(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return rag_document_service.list_jobs(db)


@router.post("/rag/documents/{document_id}/index")
def index_admin_rag_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    job = rag_document_service.request_index_document(db, document_id, current_admin, "index")
    background_tasks.add_task(rag_document_service.run_job_by_id, job["id"])
    return job


@router.post("/rag/documents/{document_id}/reindex")
def reindex_admin_rag_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    job = rag_document_service.request_index_document(db, document_id, current_admin, "reindex")
    background_tasks.add_task(rag_document_service.run_job_by_id, job["id"])
    return job


@router.delete("/rag/documents/{document_id}/index")
def delete_admin_rag_document_index(
    document_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return rag_document_service.delete_index(db, document_id, current_admin)


@router.post("/rag/courses/{course_id}/reindex")
def reindex_admin_rag_course(
    course_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    jobs = rag_document_service.request_course_reindex(db, course_id, current_admin)
    for job in jobs:
        background_tasks.add_task(rag_document_service.run_job_by_id, job["id"])
    return {"jobs": jobs}


@router.post("/rag/subjects/{subject_id}/reindex")
def reindex_admin_rag_subject(
    subject_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    jobs = rag_document_service.request_subject_reindex(db, subject_id, current_admin)
    for job in jobs:
        background_tasks.add_task(rag_document_service.run_job_by_id, job["id"])
    return {"jobs": jobs}


@router.get("/audit-logs")
def get_admin_audit_logs(
    search: str = "",
    action: str = "all",
    target_type: str = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.list_audit_logs(db, search, action, target_type, page, page_size)


@router.get("/subjects")
def get_admin_subjects(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return catalog_service.list_subjects(db, active_only=False)


@router.post("/subjects")
def create_admin_subject(
    payload: SubjectPayload,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    subject = catalog_service.create_subject(db, payload.model_dump())
    admin_service.create_audit_log(db, current_admin.id, "create_subject", "subject", str(subject["id"]), None, subject)
    return subject


@router.put("/subjects/{subject_id}")
def update_admin_subject(
    subject_id: int,
    payload: SubjectPayload,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = next((item for item in catalog_service.list_subjects(db, active_only=False) if item["id"] == subject_id), None)
    subject = catalog_service.update_subject(db, subject_id, payload.model_dump())
    admin_service.create_audit_log(db, current_admin.id, "update_subject", "subject", str(subject_id), before, subject)
    return subject


@router.delete("/subjects/{subject_id}")
def delete_admin_subject(
    subject_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = next((item for item in catalog_service.list_subjects(db, active_only=False) if item["id"] == subject_id), None)
    result = catalog_service.delete_subject(db, subject_id)
    admin_service.create_audit_log(db, current_admin.id, "delete_subject", "subject", str(subject_id), before, result)
    return result


@router.get("/education-levels")
def get_admin_education_levels(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return catalog_service.list_education_levels(db, active_only=False)


@router.get("/difficulty-levels")
def get_admin_difficulty_levels(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return catalog_service.list_difficulty_levels(db, active_only=False)


@router.get("/diagnostic/questions")
def get_admin_diagnostic_questions(
    subject_id: int | None = None,
    education_level_id: int | None = None,
    source_course_id: int | None = None,
    difficulty_level_id: int | None = None,
    active: bool | None = None,
    generation_method: str | None = None,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return diagnostic_service.list_admin_questions(
        db,
        subject_id=subject_id,
        education_level_id=education_level_id,
        source_course_id=source_course_id,
        difficulty_level_id=difficulty_level_id,
        active=active,
        generation_method=generation_method,
    )


@router.post("/diagnostic/questions")
def create_admin_diagnostic_question(
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    question = diagnostic_service.create_admin_question(db, payload)
    admin_service.create_audit_log(db, current_admin.id, "create_diagnostic_question", "diagnostic_question", str(question["id"]), None, question)
    return question


@router.put("/diagnostic/questions/{question_id}")
def update_admin_diagnostic_question(
    question_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = next((item for item in diagnostic_service.list_admin_questions(db) if item["id"] == question_id), None)
    question = diagnostic_service.update_admin_question(db, question_id, payload)
    admin_service.create_audit_log(db, current_admin.id, "update_diagnostic_question", "diagnostic_question", str(question_id), before, question)
    return question


@router.delete("/diagnostic/questions/{question_id}")
def delete_admin_diagnostic_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = next((item for item in diagnostic_service.list_admin_questions(db) if item["id"] == question_id), None)
    result = diagnostic_service.deactivate_admin_question(db, question_id)
    admin_service.create_audit_log(db, current_admin.id, "deactivate_diagnostic_question", "diagnostic_question", str(question_id), before, result)
    return result


@router.delete("/users/{user_id}")
def delete_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.delete_user(db, current_admin, user_id)


@router.get("/courses")
def get_admin_courses(
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return course_service.get_courses(db, include_unpublished=True)


@router.get("/courses/{course_id}")
def get_admin_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return course_service.get_course_detail(db, course_id, include_unpublished=True)


@router.post("/courses")
def create_admin_course(
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    course = course_service.create_course(db, payload)
    admin_service.create_audit_log(db, current_admin.id, "create_course", "course", str(course["id"]), None, course)
    return course


@router.put("/courses/{course_id}")
def update_admin_course(
    course_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = course_service.get_course_detail(db, course_id, include_unpublished=True)
    course = course_service.update_course(db, course_id, payload)
    admin_service.create_audit_log(db, current_admin.id, "update_course", "course", str(course_id), before, course)
    return course


@router.put("/courses/{course_id}/professor")
def assign_admin_course_professor(
    course_id: int,
    payload: CourseProfessorAssignment,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_service.assign_course_professor(db, current_admin, course_id, payload.professor_id)


@router.delete("/courses/{course_id}")
def delete_admin_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = course_service.get_course_detail(db, course_id, include_unpublished=True)
    result = course_service.delete_course(db, course_id)
    admin_service.create_audit_log(db, current_admin.id, "delete_course", "course", str(course_id), before, result)
    return result


@router.post("/courses/{course_id}/pdf")
def upload_admin_course_pdf(
    course_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = course_service.get_course_detail(db, course_id, include_unpublished=True)
    result = course_service.save_course_pdf(db, course_id, file, replace=False)
    admin_service.create_audit_log(db, current_admin.id, "upload_pdf", "course_pdf", str(course_id), before, result)
    return result


@router.put("/courses/{course_id}/pdf")
def replace_admin_course_pdf(
    course_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = course_service.get_course_detail(db, course_id, include_unpublished=True)
    result = course_service.save_course_pdf(db, course_id, file, replace=True)
    admin_service.create_audit_log(db, current_admin.id, "replace_pdf", "course_pdf", str(course_id), before, result)
    return result


@router.delete("/courses/{course_id}/pdf")
def delete_admin_course_pdf(
    course_id: int,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    before = course_service.get_course_detail(db, course_id, include_unpublished=True)
    result = course_service.delete_course_pdf(db, course_id)
    admin_service.create_audit_log(db, current_admin.id, "delete_pdf", "course_pdf", str(course_id), before, result)
    return result
