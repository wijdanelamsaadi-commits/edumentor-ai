from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_professor_or_admin, get_current_student, get_current_user
from app.core.database import get_db
from app.models.persistence import UserProfile
from app.services import assessment_service, personalized_lesson_service, study_path_service

router = APIRouter(tags=["Adaptive assessments"])


@router.get("/professor/classrooms")
def professor_classrooms(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> list[dict]:
    return assessment_service.list_professor_classrooms(db, current_user)


@router.post("/professor/classrooms")
def create_professor_classroom(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.create_classroom(db, current_user, payload)


@router.get("/professor/classrooms/{classroom_id}")
def professor_classroom_detail(
    classroom_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.get_professor_classroom(db, current_user, classroom_id)


@router.put("/professor/classrooms/{classroom_id}")
def update_professor_classroom(
    classroom_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.update_classroom(db, current_user, classroom_id, payload)


@router.post("/professor/classrooms/{classroom_id}/students")
def add_professor_classroom_student(
    classroom_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.add_student_to_classroom(db, current_user, classroom_id, payload)


@router.delete("/professor/classrooms/{classroom_id}/students/{student_id}")
def remove_professor_classroom_student(
    classroom_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.remove_student_from_classroom(db, current_user, classroom_id, student_id)


@router.get("/student/classrooms")
def student_classrooms(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> list[dict]:
    return assessment_service.list_student_classrooms(db, current_user)


@router.get("/student/dashboard")
def student_adaptive_dashboard(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.get_student_dashboard(db, current_user)


@router.get("/study-paths")
def student_study_paths(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> list[dict]:
    return study_path_service.list_student_paths(db, current_user)


@router.get("/study-paths/{path_id}")
def student_study_path_detail(
    path_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return study_path_service.get_student_path(db, current_user, path_id)


@router.post("/study-paths/{path_id}/items/{item_id}/start")
def student_start_study_path_item(
    path_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return study_path_service.start_item(db, current_user, path_id, item_id)


@router.post("/study-paths/{path_id}/items/{item_id}/complete")
def student_complete_study_path_item(
    path_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return study_path_service.complete_item(db, current_user, path_id, item_id)


@router.post("/study-paths/{path_id}/items/{item_id}/skip")
def student_skip_study_path_item(
    path_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return study_path_service.skip_item(db, current_user, path_id, item_id)


@router.post("/study-paths/{path_id}/refresh")
def student_refresh_study_path(
    path_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return study_path_service.refresh_student_path(db, current_user, path_id)


@router.get("/professor/assessments")
def professor_assessments(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> list[dict]:
    return assessment_service.list_professor_assessments(db, current_user)


@router.post("/professor/assessments")
def create_professor_assessment(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.create_assessment(db, current_user, payload)


@router.get("/professor/assessments/{assessment_id}")
def professor_assessment_detail(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.get_professor_assessment(db, current_user, assessment_id)


@router.put("/professor/assessments/{assessment_id}")
def update_professor_assessment(
    assessment_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.update_assessment(db, current_user, assessment_id, payload)


@router.delete("/professor/assessments/{assessment_id}")
def delete_professor_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.delete_assessment(db, current_user, assessment_id)


@router.post("/professor/assessments/{assessment_id}/publish")
def publish_professor_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.publish_assessment(db, current_user, assessment_id)


@router.post("/professor/assessments/{assessment_id}/close")
def close_professor_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.close_assessment(db, current_user, assessment_id)


@router.post("/professor/assessments/{assessment_id}/propose-questions")
def propose_professor_assessment_questions(
    assessment_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.propose_questions(db, current_user, assessment_id, payload)


@router.get("/professor/assessments/{assessment_id}/results")
def professor_assessment_results(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.get_professor_assessment_results(db, current_user, assessment_id)


@router.get("/professor/study-paths")
def professor_study_paths(
    classroom_id: int | None = None,
    course_id: int | None = None,
    student_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> list[dict]:
    return study_path_service.list_professor_paths(
        db,
        current_user,
        {"classroom_id": classroom_id, "course_id": course_id, "student_id": student_id, "status": status},
    )


@router.get("/professor/study-paths/{path_id}")
def professor_study_path_detail(
    path_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return study_path_service.get_professor_path(db, current_user, path_id)


@router.put("/professor/study-paths/{path_id}/items/{item_id}")
def professor_update_study_path_item(
    path_id: int,
    item_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return study_path_service.update_professor_item(db, current_user, path_id, item_id, payload)


@router.get("/professor/personalized-assessments/{assessment_id}")
def professor_personalized_assessment_detail(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.get_professor_personalized_assessment(db, current_user, assessment_id)


@router.post("/professor/personalized-assessments/{assessment_id}/questions")
def professor_add_personalized_assessment_question(
    assessment_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.add_personalized_assessment_question(db, current_user, assessment_id, payload)


@router.put("/professor/personalized-assessments/{assessment_id}/questions/{question_id}")
def professor_update_personalized_assessment_question(
    assessment_id: int,
    question_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.update_personalized_assessment_question(db, current_user, assessment_id, question_id, payload)


@router.delete("/professor/personalized-assessments/{assessment_id}/questions/{question_id}")
def professor_delete_personalized_assessment_question(
    assessment_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.delete_personalized_assessment_question(db, current_user, assessment_id, question_id)


@router.post("/professor/personalized-assessments/{assessment_id}/approve")
def professor_approve_personalized_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.approve_personalized_assessment(db, current_user, assessment_id)


@router.post("/professor/personalized-assessments/{assessment_id}/publish")
def professor_publish_personalized_assessment(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return assessment_service.publish_personalized_assessment(db, current_user, assessment_id)


@router.get("/assessments")
def student_assessments(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> list[dict]:
    return assessment_service.list_student_assessments(db, current_user)


@router.get("/assessments/{assessment_id}")
def student_assessment_detail(
    assessment_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.get_student_assessment(db, current_user, assessment_id)


@router.post("/assessments/{assessment_id}/submit")
def submit_student_assessment(
    assessment_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.submit_assessment(db, current_user, assessment_id, payload)


@router.get("/assessment-results/{attempt_id}")
def student_assessment_result(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.get_attempt_report(db, current_user, attempt_id)


@router.get("/assessment-results/{attempt_id}/detailed")
def detailed_assessment_result(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
) -> dict:
    return assessment_service.get_detailed_attempt_report(db, current_user, attempt_id)


@router.get("/remediation/{plan_id}")
def student_remediation_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.get_remediation_plan(db, current_user, plan_id)


@router.get("/remediation")
def student_remediation_plans(
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> list[dict]:
    return assessment_service.list_student_remediation_plans(db, current_user)


@router.put("/remediation/{plan_id}/items/{item_id}/complete")
def complete_student_remediation_item(
    plan_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.complete_remediation_item(db, current_user, plan_id, item_id)


@router.post("/remediation/{plan_id}/lessons/generate")
def generate_student_remediation_lessons(
    plan_id: int,
    payload: dict | None = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    payload = payload or {}
    return personalized_lesson_service.generate_lessons_for_plan(db, current_user, plan_id, use_groq=payload.get("use_groq") is True)


@router.get("/remediation/{plan_id}/lessons")
def student_remediation_lessons(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> list[dict]:
    return [personalized_lesson_service.serialize_lesson(item) for item in personalized_lesson_service.list_lessons_for_plan(db, current_user, plan_id)]


@router.get("/personalized-lessons/{lesson_id}")
def student_personalized_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return personalized_lesson_service.serialize_lesson(personalized_lesson_service.get_student_lesson(db, current_user, lesson_id))


@router.put("/personalized-lessons/{lesson_id}/complete")
def complete_student_personalized_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return personalized_lesson_service.complete_lesson(db, current_user, lesson_id)


@router.post("/personalized-lessons/{lesson_id}/knowledge-check/submit")
def submit_student_personalized_lesson_knowledge_check(
    lesson_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return personalized_lesson_service.submit_knowledge_check(db, current_user, lesson_id, payload)


@router.post("/remediation/{plan_id}/personalized-assessment")
def create_student_personalized_assessment(
    plan_id: int,
    payload: dict | None = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.create_personalized_assessment(db, current_user, plan_id, payload)


@router.get("/assessment-results/compare/{initial_attempt_id}/{personalized_attempt_id}")
def compare_student_assessments(
    initial_attempt_id: int,
    personalized_attempt_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.compare_attempts(db, current_user, initial_attempt_id, personalized_attempt_id)


@router.get("/remediation/{plan_id}/comparison")
def compare_student_remediation_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_student),
) -> dict:
    return assessment_service.compare_latest_for_plan(db, current_user, plan_id)


@router.get("/remediation/{plan_id}/comparison/detailed")
def compare_student_remediation_plan_detailed(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
) -> dict:
    return assessment_service.compare_latest_for_plan_detailed(db, current_user, plan_id)


@router.get("/professor/remediation/lessons")
def professor_remediation_lessons(
    classroom_id: int | None = None,
    course_id: int | None = None,
    student_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> list[dict]:
    return personalized_lesson_service.list_professor_lessons(
        db,
        current_user,
        {"classroom_id": classroom_id, "course_id": course_id, "student_id": student_id, "status": status},
    )


@router.get("/professor/personalized-lessons/{lesson_id}")
def professor_personalized_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return personalized_lesson_service.serialize_lesson(
        personalized_lesson_service.get_professor_lesson(db, current_user, lesson_id),
        professor_view=True,
    )


@router.put("/professor/personalized-lessons/{lesson_id}")
def update_professor_personalized_lesson(
    lesson_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return personalized_lesson_service.update_professor_lesson(db, current_user, lesson_id, payload)


@router.put("/professor/personalized-lessons/{lesson_id}/approve")
def approve_professor_personalized_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_professor_or_admin),
) -> dict:
    return personalized_lesson_service.approve_professor_lesson(db, current_user, lesson_id)
