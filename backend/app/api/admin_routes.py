from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_admin
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.schemas.admin import AdminStatsOverview, AdminUserRead, RoleUpdate, StatusUpdate
from app.services import admin_rag_service, admin_service, course_service

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
    current_admin: UserProfile = Depends(get_current_admin),
):
    return admin_rag_service.get_admin_rag_status()


@router.post("/rag/reindex")
def reindex_admin_rag(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin: UserProfile = Depends(get_current_admin),
):
    started = admin_rag_service.mark_reindex_started()
    if started:
        admin_service.create_audit_log(
            db,
            current_admin.id,
            "reindex_rag",
            "rag",
            "course_documents",
            None,
            {"state": "running"},
        )
        background_tasks.add_task(admin_rag_service.run_reindex)
    return admin_rag_service.get_admin_rag_status()


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
