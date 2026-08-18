from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import re
import urllib.error
import urllib.request
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.roles import UserRole
from app.models.persistence import (
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    Course,
    CourseChapter,
    Notification,
    PersonalizedLesson,
    PersonalizedLessonSource,
    RagDocument,
    RemediationItem,
    RemediationPlan,
    Skill,
    UserProfile,
)
from app.services import rag_document_service, study_path_service
from app.services.groq_service import GROQ_CHAT_COMPLETIONS_URL

GENERATION_METHODS = {"deterministic", "groq", "manual"}
LESSON_STATUSES = {"draft", "ready", "approved", "completed", "failed", "archived"}
SOURCE_TYPES = {"structured_content", "rag", "chapter", "assessment_error", "manual"}
ALLOWED_BLOCK_TYPES = {
    "heading",
    "paragraph",
    "definition",
    "key_point",
    "bullet_list",
    "numbered_list",
    "diagram",
    "example",
    "exercise",
    "solution",
    "knowledge_check",
    "summary",
    "warning",
    "tip",
    "table",
    "code",
}


def generate_lessons_for_plan(db: Session, user: UserProfile, plan_id: int, use_groq: bool = False, commit: bool = True) -> dict:
    plan = get_student_plan(db, user, plan_id)
    source_attempt = get_source_attempt(db, plan)
    weak_groups = plan_groups_from_items(plan, source_attempt)
    created_or_existing: list[PersonalizedLesson] = []

    for group in weak_groups:
        existing = find_existing_lesson(db, plan.id, group["chapter_id"], group["skill_id"])
        if existing:
            created_or_existing.append(existing)
            continue

        lesson_payload = build_deterministic_lesson(db, plan, source_attempt, group)
        generation_method = "deterministic"
        if use_groq:
            groq_payload = improve_lesson_with_groq(lesson_payload)
            if groq_payload:
                lesson_payload = groq_payload
                generation_method = "groq"

        lesson = PersonalizedLesson(
            remediation_plan_id=plan.id,
            student_id=plan.student_id,
            course_id=plan.course_id,
            subject_id=plan.subject_id,
            chapter_id=group["chapter_id"],
            skill_id=group["skill_id"],
            title=lesson_payload["title"],
            objective=lesson_payload["objective"],
            reason=lesson_payload["reason"],
            structured_content=lesson_payload["structured_content"],
            generation_method=generation_method,
            status="ready",
            source_attempt_id=source_attempt.id,
            active=True,
        )
        db.add(lesson)
        db.flush()
        add_lesson_sources(db, lesson, lesson_payload["sources"])
        link_remediation_items(db, plan.id, lesson, group["chapter_id"], group["skill_id"])
        created_or_existing.append(lesson)

    if created_or_existing:
        create_deduplicated_notification(
            db,
            plan.student_id,
            "remediation",
            "Mini-cours pret",
            "Un mini-cours personnalise est disponible dans votre parcours.",
        )
    if commit:
        try:
            study_path_service.create_or_refresh_for_plan(db, plan)
            db.commit()
        except IntegrityError:
            db.rollback()
            return generate_lessons_for_plan(db, user, plan_id, use_groq=False)

    return {
        "plan_id": plan.id,
        "created_count": len(created_or_existing),
        "lessons": [serialize_lesson(item) for item in list_lessons_for_plan(db, user, plan.id)],
    }


def list_lessons_for_plan(db: Session, user: UserProfile, plan_id: int) -> list[PersonalizedLesson]:
    plan = get_student_plan(db, user, plan_id)
    return db.scalars(
        select(PersonalizedLesson)
        .where(PersonalizedLesson.remediation_plan_id == plan.id, PersonalizedLesson.active.is_(True))
        .options(*lesson_options())
        .order_by(PersonalizedLesson.created_at.asc(), PersonalizedLesson.id.asc())
    ).all()


def get_student_lesson(db: Session, user: UserProfile, lesson_id: int) -> PersonalizedLesson:
    lesson = db.scalars(select(PersonalizedLesson).where(PersonalizedLesson.id == lesson_id).options(*lesson_options())).first()
    if lesson is None or not lesson.active:
        raise HTTPException(status_code=404, detail="Mini-cours introuvable")
    if not is_admin(user) and lesson.student_id != user.id:
        raise HTTPException(status_code=403, detail="Mini-cours non autorise")
    return lesson


def complete_lesson(db: Session, user: UserProfile, lesson_id: int) -> dict:
    lesson = get_student_lesson(db, user, lesson_id)
    lesson.status = "completed"
    lesson.completed_at = lesson.completed_at or datetime.utcnow()
    lesson.updated_at = datetime.utcnow()
    for item in lesson.remediation_items:
        item.completed = True
        item.completed_at = item.completed_at or datetime.utcnow()
    update_plan_status_from_lessons(lesson.plan)
    study_path_service.create_or_refresh_for_plan(db, lesson.plan)
    db.commit()
    db.refresh(lesson)
    return serialize_lesson(lesson)


def submit_knowledge_check(db: Session, user: UserProfile, lesson_id: int, payload: dict) -> dict:
    lesson = get_student_lesson(db, user, lesson_id)
    check = first_knowledge_check(lesson.structured_content or [])
    if not check:
        raise HTTPException(status_code=404, detail="Mini-question introuvable")
    selected = str(payload.get("answer") or "").strip()
    expected = str(check.get("answer") or check.get("correct_answer") or "").strip()
    correct = normalize_text(selected) == normalize_text(expected)
    if correct:
        study_path_service.complete_matching_knowledge_check(db, lesson)
        db.commit()
    return {
        "lesson_id": lesson.id,
        "correct": correct,
        "selected_answer": selected,
        "correct_answer": expected,
        "explanation": check.get("explanation") or ("Bonne reponse." if correct else "Revoyez le resume du mini-cours puis reessayez."),
    }


def list_professor_lessons(db: Session, user: UserProfile, filters: dict) -> list[dict]:
    query = select(PersonalizedLesson).join(AssessmentAttempt, AssessmentAttempt.id == PersonalizedLesson.source_attempt_id).join(Assessment, Assessment.id == AssessmentAttempt.assessment_id).options(*lesson_options())
    if not is_admin(user):
        query = query.where(Assessment.professor_id == user.id)
    if filters.get("course_id"):
        query = query.where(PersonalizedLesson.course_id == int(filters["course_id"]))
    if filters.get("student_id"):
        query = query.where(PersonalizedLesson.student_id == int(filters["student_id"]))
    if filters.get("status"):
        query = query.where(PersonalizedLesson.status == str(filters["status"]))
    if filters.get("classroom_id"):
        query = query.where(Assessment.classroom_id == int(filters["classroom_id"]))
    return [serialize_professor_tracking_lesson(db, item) for item in db.scalars(query.order_by(PersonalizedLesson.created_at.desc()))]


def get_professor_lesson(db: Session, user: UserProfile, lesson_id: int) -> PersonalizedLesson:
    lesson = db.scalars(select(PersonalizedLesson).where(PersonalizedLesson.id == lesson_id).options(*lesson_options())).first()
    if lesson is None or not lesson.active:
        raise HTTPException(status_code=404, detail="Mini-cours introuvable")
    if is_admin(user):
        return lesson
    source_attempt = lesson.source_attempt
    assessment = source_attempt.assessment if source_attempt else None
    if assessment is None or assessment.professor_id != user.id:
        raise HTTPException(status_code=403, detail="Mini-cours non autorise")
    return lesson


def update_professor_lesson(db: Session, user: UserProfile, lesson_id: int, payload: dict) -> dict:
    lesson = get_professor_lesson(db, user, lesson_id)
    if "title" in payload:
        lesson.title = clean_text(payload["title"])[:260]
    if "objective" in payload:
        lesson.objective = clean_text(payload["objective"])
    if "structured_content" in payload:
        lesson.structured_content = validate_structured_content(payload["structured_content"])
        lesson.generation_method = "manual"
    lesson.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lesson)
    return serialize_lesson(lesson, professor_view=True)


def approve_professor_lesson(db: Session, user: UserProfile, lesson_id: int) -> dict:
    lesson = get_professor_lesson(db, user, lesson_id)
    lesson.status = "approved"
    lesson.approved_at = lesson.approved_at or datetime.utcnow()
    lesson.updated_at = datetime.utcnow()
    create_deduplicated_notification(db, lesson.student_id, "remediation", "Mini-cours approuve", f"{lesson.title} est approuve.")
    db.commit()
    db.refresh(lesson)
    return serialize_lesson(lesson, professor_view=True)


def serialize_professor_tracking_lesson(db: Session, lesson: PersonalizedLesson) -> dict:
    data = serialize_lesson(lesson, professor_view=True)
    plan = lesson.plan
    after_score = latest_personalized_score_for_plan(db, plan)
    initial_score = float(plan.initial_score or 0) if plan else None
    data.update(
        {
            "plan_status": plan.status if plan else None,
            "initial_score": initial_score,
            "after_score": after_score,
            "evolution_points": round(after_score - initial_score, 2) if after_score is not None and initial_score is not None else None,
        }
    )
    return data


def latest_personalized_score_for_plan(db: Session, plan: RemediationPlan | None) -> float | None:
    if plan is None:
        return None
    attempts = db.scalars(
        select(AssessmentAttempt)
        .join(Assessment, Assessment.id == AssessmentAttempt.assessment_id)
        .join(AssessmentQuestion, AssessmentQuestion.assessment_id == Assessment.id)
        .where(
            AssessmentAttempt.student_id == plan.student_id,
            AssessmentAttempt.completed.is_(True),
            Assessment.assessment_type == "personalized",
            AssessmentQuestion.source_attempt_id == plan.source_attempt_id,
        )
        .order_by(AssessmentAttempt.submitted_at.desc(), AssessmentAttempt.id.desc())
    ).all()
    return float(attempts[0].percentage or 0) if attempts else None


def serialize_lesson(lesson: PersonalizedLesson, professor_view: bool = False) -> dict:
    progress = 100 if lesson.status == "completed" else 0
    data = {
        "id": lesson.id,
        "remediation_plan_id": lesson.remediation_plan_id,
        "student_id": lesson.student_id,
        "student_name": lesson.student.full_name if lesson.student else "",
        "course_id": lesson.course_id,
        "course_title": lesson.course.title if lesson.course else "",
        "subject_id": lesson.subject_id,
        "chapter_id": lesson.chapter_id,
        "chapter_title": lesson.chapter.title if lesson.chapter else "",
        "skill_id": lesson.skill_id,
        "skill_name": lesson.skill.name if lesson.skill else "",
        "title": lesson.title,
        "objective": lesson.objective,
        "reason": lesson.reason,
        "structured_content": lesson.structured_content or [],
        "generation_method": lesson.generation_method,
        "status": lesson.status,
        "source_attempt_id": lesson.source_attempt_id,
        "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
        "updated_at": lesson.updated_at.isoformat() if lesson.updated_at else None,
        "approved_at": lesson.approved_at.isoformat() if lesson.approved_at else None,
        "completed_at": lesson.completed_at.isoformat() if lesson.completed_at else None,
        "active": lesson.active,
        "progression": {
            "total_steps": 1,
            "completed_steps": 1 if lesson.status == "completed" else 0,
            "percentage": progress,
            "next_step": "termine" if lesson.status == "completed" else "lire_le_mini_cours",
        },
        "sources": [serialize_source(source) for source in lesson.sources],
    }
    if professor_view:
        data["assessment_title"] = lesson.source_attempt.assessment.title if lesson.source_attempt and lesson.source_attempt.assessment else ""
    return data


def serialize_plan_with_lessons(plan: RemediationPlan) -> dict:
    lessons = [lesson for lesson in plan.personalized_lessons if lesson.active]
    items = list(plan.items)
    total_steps = len([item for item in items if item.required]) + len(lessons)
    completed_steps = sum(1 for item in items if item.required and item.completed) + sum(1 for lesson in lessons if lesson.status == "completed")
    percentage = round((completed_steps / total_steps) * 100, 2) if total_steps else 0
    return {
        "total_steps": total_steps,
        "completed_steps": completed_steps,
        "percentage": percentage,
        "next_step": next_plan_step(plan, lessons, items),
    }


def serialize_source(source: PersonalizedLessonSource) -> dict:
    document = source.document
    return {
        "id": source.id,
        "document_id": source.document_id,
        "file_name": document.original_filename if document else None,
        "chapter_id": source.chapter_id,
        "page_start": source.page_start,
        "page_end": source.page_end,
        "source_type": source.source_type,
        "excerpt": source.excerpt,
    }


def group_incorrect_answers(attempt: AssessmentAttempt) -> list[dict]:
    groups: dict[tuple[int | None, int | None], dict] = {}
    for answer in attempt.answers:
        if answer.correct or answer.question is None:
            continue
        question = answer.question
        key = (question.chapter_id, question.skill_id)
        group = groups.setdefault(
            key,
            {
                "chapter_id": question.chapter_id,
                "skill_id": question.skill_id,
                "answers": [],
            },
        )
        group["answers"].append(answer)
    return list(groups.values())


def plan_groups_from_items(plan: RemediationPlan, attempt: AssessmentAttempt) -> list[dict]:
    allowed_keys = {
        (item.chapter_id, item.skill_id)
        for item in plan.items
        if item.required and (item.chapter_id is not None or item.skill_id is not None)
    }
    if not allowed_keys:
        return []
    groups = group_incorrect_answers(attempt)
    return [group for group in groups if (group["chapter_id"], group["skill_id"]) in allowed_keys]


def build_deterministic_lesson(db: Session, plan: RemediationPlan, attempt: AssessmentAttempt, group: dict) -> dict:
    chapter = db.get(CourseChapter, group["chapter_id"]) if group.get("chapter_id") else None
    skill = db.get(Skill, group["skill_id"]) if group.get("skill_id") else None
    if chapter and chapter.course_id != plan.course_id:
        raise HTTPException(status_code=422, detail="Chapitre hors du cours de remediation")
    if skill and skill.course_id and skill.course_id != plan.course_id:
        raise HTTPException(status_code=422, detail="Competence hors du cours de remediation")

    blocks = select_relevant_blocks(chapter)
    rag_results = search_lesson_sources(db, plan, chapter, skill)
    topic = skill.name if skill else chapter.title if chapter else "Notion a reviser"
    wrong_answers = group["answers"]
    reason = build_reason(wrong_answers, topic)
    sources = build_sources(blocks, rag_results, wrong_answers)
    content_blocks = build_lesson_blocks(topic, reason, blocks, rag_results, wrong_answers, sources)

    return {
        "title": f"Comprendre {topic}",
        "objective": f"Revoir {topic} et corriger les erreurs observees dans l'evaluation.",
        "reason": reason,
        "structured_content": validate_structured_content(content_blocks),
        "sources": sources,
    }


def build_lesson_blocks(topic: str, reason: str, source_blocks: list[dict], rag_results: list[dict], wrong_answers: list[AssessmentAnswer], sources: list[dict]) -> list[dict]:
    definition = first_block_content(source_blocks, {"definition", "key_point", "paragraph"}) or first_result_preview(rag_results)
    key_points = collect_list_items(source_blocks)
    example = first_block_content(source_blocks, {"example"}) or "Reprenez la question incorrecte, identifiez la notion visee, puis comparez votre choix avec l'explication de correction."
    warning = first_block_content(source_blocks, {"warning"}) or "Erreur frequente : repondre trop vite sans relier la question au chapitre et a la competence evaluee."
    summary = first_block_content(source_blocks, {"summary"}) or f"{topic} doit etre compris a partir de sa definition, de ses indices dans l'enonce et de son application pratique."
    diagram = first_block_content(source_blocks, {"diagram"})
    first_wrong = wrong_answers[0]
    wrong_question = first_wrong.question.question if first_wrong.question else "Question de l'evaluation"
    selected = first_wrong.selected_answer or "aucune reponse"
    correct = first_wrong.question.correct_answer if first_wrong.question else ""

    blocks = [
        {"type": "heading", "content": f"Mini-cours : {topic}"},
        {"type": "paragraph", "title": "Introduction", "content": shorten_text(f"Ce mini-cours cible une difficulte reperee pendant l'evaluation. {reason}", 420)},
        {"type": "definition", "title": "Definition", "content": shorten_text(definition, 520)},
        {"type": "key_point", "title": "Point essentiel", "content": shorten_text(warning, 420)},
        {"type": "bullet_list", "title": "A retenir", "content": key_points[:5] or [summary]},
    ]
    if diagram:
        blocks.append({"type": "diagram", "title": "Schema", "content": sanitize_mermaid(diagram)})
    blocks.extend(
        [
            {"type": "example", "title": "Exemple concret", "content": shorten_text(example, 560)},
            {"type": "exercise", "title": "Exercice cible", "content": f"Relisez cette question : {shorten_text(wrong_question, 260)} Pourquoi la reponse '{shorten_text(selected, 80)}' n'etait-elle pas la meilleure ?"},
            {"type": "solution", "title": "Correction guidee", "content": shorten_text(f"La bonne reponse attendue etait : {correct}. Appuyez-vous sur la definition et le point essentiel du mini-cours pour justifier ce choix.", 520)},
            {
                "type": "knowledge_check",
                "title": "Mini-verification",
                "content": {
                    "question": f"Quelle est l'action la plus utile pour maitriser {topic} ?",
                    "options": [
                        "Relier la definition a un exemple et refaire la correction.",
                        "Memoriser seulement le titre du chapitre.",
                        "Changer de cours sans revoir l'erreur.",
                        "Ignorer l'explication de correction.",
                    ],
                    "answer": "Relier la definition a un exemple et refaire la correction.",
                    "explanation": "La remediation est efficace quand l'apprenant relie la notion, l'exemple et son erreur initiale.",
                },
            },
            {"type": "summary", "title": "Resume", "content": shorten_text(summary, 520)},
            {"type": "sources", "title": "Sources utilisees", "content": [format_source_text(source) for source in sources[:6]]},
        ]
    )
    return attach_block_sources(blocks, sources)


def select_relevant_blocks(chapter: CourseChapter | None) -> list[dict]:
    if chapter is None:
        return []
    raw = chapter.structured_content or []
    if isinstance(raw, dict):
        raw = raw.get("blocks") or raw.get("items") or []
    blocks = [block for block in raw if isinstance(block, dict) and block.get("type") in ALLOWED_BLOCK_TYPES]
    if blocks:
        return blocks[:12]
    if chapter.content:
        return [{"type": "paragraph", "title": chapter.title, "content": chapter.content}]
    return []


def search_lesson_sources(db: Session, plan: RemediationPlan, chapter: CourseChapter | None, skill: Skill | None) -> list[dict]:
    query = " ".join(item for item in [skill.name if skill else "", chapter.title if chapter else ""] if item).strip()
    if not query:
        return []
    try:
        results = rag_document_service.filtered_semantic_search(
            db,
            query,
            course_id=plan.course_id,
            subject_id=plan.subject_id,
            top_k=4,
            published_only=True,
        )
    except Exception:
        return []
    return [result for result in results if int(result.get("course_id") or plan.course_id) == plan.course_id]


def build_sources(blocks: list[dict], rag_results: list[dict], wrong_answers: list[AssessmentAnswer]) -> list[dict]:
    sources = []
    seen = set()

    for block in blocks:
        document_id = block.get("source_document_db_id") or block.get("source_document_id")
        page_start = safe_int(block.get("source_page_start") or block.get("page"))
        page_end = safe_int(block.get("source_page_end") or page_start)
        if document_id or page_start:
            add_source(sources, seen, "structured_content", document_id, None, page_start, page_end, block_content_text(block))

    for result in rag_results:
        add_source(
            sources,
            seen,
            "rag",
            safe_int(result.get("document_id")),
            None,
            safe_int(result.get("page_start") or result.get("page_number")),
            safe_int(result.get("page_end") or result.get("page_start") or result.get("page_number")),
            result.get("text") or result.get("text_preview") or "",
        )

    for answer in wrong_answers:
        question = answer.question
        if question:
            add_source(
                sources,
                seen,
                "assessment_error",
                question.source_document_id,
                question.chapter_id,
                question.source_page_start,
                question.source_page_end,
                question.explanation,
            )
    return sources[:8]


def add_source(sources: list[dict], seen: set, source_type: str, document_id: int | None, chapter_id: int | None, page_start: int | None, page_end: int | None, excerpt: str | None) -> None:
    key = (source_type, document_id, chapter_id, page_start, page_end)
    if key in seen:
        return
    seen.add(key)
    sources.append(
        {
            "source_type": source_type,
            "document_id": document_id,
            "chapter_id": chapter_id,
            "page_start": page_start,
            "page_end": page_end,
            "excerpt": shorten_text(excerpt or "", 280),
        }
    )


def add_lesson_sources(db: Session, lesson: PersonalizedLesson, sources: list[dict]) -> None:
    for source in sources:
        document_id = source.get("document_id")
        if document_id and db.get(RagDocument, int(document_id)) is None:
            document_id = None
        lesson.sources.append(
            PersonalizedLessonSource(
                document_id=document_id,
                chapter_id=source.get("chapter_id") or lesson.chapter_id,
                page_start=source.get("page_start"),
                page_end=source.get("page_end"),
                source_type=source.get("source_type") if source.get("source_type") in SOURCE_TYPES else "chapter",
                excerpt=source.get("excerpt"),
            )
        )


def improve_lesson_with_groq(payload: dict) -> dict | None:
    settings = get_settings()
    api_key = settings.get("groq_api_key")
    if not api_key:
        return None

    safe_payload = {
        "title": payload["title"],
        "objective": payload["objective"],
        "reason": payload["reason"],
        "blocks": payload["structured_content"][:10],
    }
    request_body = {
        "model": settings["groq_model"],
        "temperature": 0.2,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Tu ameliores un mini-cours EduMentor AI. Reponds en JSON strict avec title, objective, reason, structured_content. "
                    "Utilise uniquement les extraits fournis, sans HTML, sans script, sans source externe et sans donnee privee. "
                    "Les blocs doivent garder les types: heading, paragraph, definition, key_point, bullet_list, example, exercise, solution, knowledge_check, summary."
                ),
            },
            {"role": "user", "content": json.dumps(safe_payload, ensure_ascii=True)},
        ],
    }
    request = urllib.request.Request(
        GROQ_CHAT_COMPLETIONS_URL,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "EduMentorAI/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = json.loads(data["choices"][0]["message"]["content"])
        content["structured_content"] = validate_structured_content(content.get("structured_content") or [])
        if not content["structured_content"]:
            return None
        content["sources"] = payload["sources"]
        return {
            "title": clean_text(content.get("title") or payload["title"])[:260],
            "objective": clean_text(content.get("objective") or payload["objective"]),
            "reason": clean_text(content.get("reason") or payload["reason"]),
            "structured_content": content["structured_content"],
            "sources": payload["sources"],
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def validate_structured_content(blocks: Any) -> list[dict]:
    if not isinstance(blocks, list):
        raise HTTPException(status_code=422, detail="Contenu structure invalide")
    validated = []
    for block in blocks[:16]:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "paragraph")
        if block_type not in ALLOWED_BLOCK_TYPES and block_type != "sources":
            continue
        content = block.get("content")
        if block_type == "diagram":
            content = sanitize_mermaid(content)
        elif block_type == "knowledge_check":
            content = sanitize_knowledge_check(content)
        elif isinstance(content, list):
            content = [shorten_text(item, 240) for item in content if clean_text(item)]
        elif block_type != "table":
            content = shorten_text(content, 900)
        validated.append({"type": block_type, "title": clean_text(block.get("title") or ""), "content": content})
    if not validated:
        raise HTTPException(status_code=422, detail="Contenu structure invalide")
    return validated


def sanitize_knowledge_check(content: Any) -> dict:
    data = content if isinstance(content, dict) else {}
    options = [shorten_text(option, 160) for option in data.get("options", []) if clean_text(option)]
    return {
        "question": shorten_text(data.get("question") or "Quelle notion devez-vous revoir ?", 240),
        "options": options[:4],
        "answer": shorten_text(data.get("answer") or data.get("correct_answer") or (options[0] if options else ""), 160),
        "explanation": shorten_text(data.get("explanation") or "La reponse correcte reprend l'idee centrale du mini-cours.", 360),
    }


def get_student_plan(db: Session, user: UserProfile, plan_id: int) -> RemediationPlan:
    plan = db.scalars(
        select(RemediationPlan)
        .where(RemediationPlan.id == plan_id)
        .options(
            selectinload(RemediationPlan.items).selectinload(RemediationItem.chapter),
            selectinload(RemediationPlan.items).selectinload(RemediationItem.skill),
            selectinload(RemediationPlan.personalized_lessons).selectinload(PersonalizedLesson.sources),
            selectinload(RemediationPlan.course),
        )
    ).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Parcours introuvable")
    if not is_admin(user) and plan.student_id != user.id:
        raise HTTPException(status_code=403, detail="Parcours non autorise")
    return plan


def get_source_attempt(db: Session, plan: RemediationPlan) -> AssessmentAttempt:
    attempt = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.id == plan.source_attempt_id)
        .options(
            selectinload(AssessmentAttempt.assessment),
            selectinload(AssessmentAttempt.answers).selectinload(AssessmentAnswer.question),
        )
    ).first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Tentative source introuvable")
    return attempt


def lesson_options():
    return (
        selectinload(PersonalizedLesson.student),
        selectinload(PersonalizedLesson.course),
        selectinload(PersonalizedLesson.subject),
        selectinload(PersonalizedLesson.chapter),
        selectinload(PersonalizedLesson.skill),
        selectinload(PersonalizedLesson.source_attempt).selectinload(AssessmentAttempt.assessment),
        selectinload(PersonalizedLesson.sources).selectinload(PersonalizedLessonSource.document),
        selectinload(PersonalizedLesson.remediation_items),
        selectinload(PersonalizedLesson.plan).selectinload(RemediationPlan.items),
        selectinload(PersonalizedLesson.plan).selectinload(RemediationPlan.personalized_lessons),
    )


def find_existing_lesson(db: Session, plan_id: int, chapter_id: int | None, skill_id: int | None) -> PersonalizedLesson | None:
    conditions = [PersonalizedLesson.remediation_plan_id == plan_id, PersonalizedLesson.active.is_(True)]
    conditions.append(PersonalizedLesson.chapter_id.is_(None) if chapter_id is None else PersonalizedLesson.chapter_id == chapter_id)
    conditions.append(PersonalizedLesson.skill_id.is_(None) if skill_id is None else PersonalizedLesson.skill_id == skill_id)
    return db.scalars(select(PersonalizedLesson).where(and_(*conditions)).options(*lesson_options())).first()


def link_remediation_items(db: Session, plan_id: int, lesson: PersonalizedLesson, chapter_id: int | None, skill_id: int | None) -> None:
    items = db.scalars(
        select(RemediationItem).where(
            RemediationItem.remediation_plan_id == plan_id,
            or_(RemediationItem.chapter_id == chapter_id, RemediationItem.skill_id == skill_id),
        )
    ).all()
    for item in items:
        if item.chapter_id == chapter_id or item.skill_id == skill_id:
            item.personalized_lesson_id = lesson.id
            if item.item_type in {"chapter", "lesson", "explanation"}:
                item.item_type = "lesson"


def update_plan_status_from_lessons(plan: RemediationPlan) -> None:
    required_items_done = all(item.completed for item in plan.items if item.required)
    lessons_done = all(lesson.status == "completed" for lesson in plan.personalized_lessons if lesson.active)
    if required_items_done and lessons_done:
        plan.status = "completed"
        plan.completed_at = plan.completed_at or datetime.utcnow()


def next_plan_step(plan: RemediationPlan, lessons: list[PersonalizedLesson], items: list[RemediationItem]) -> dict:
    for lesson in lessons:
        if lesson.status != "completed":
            return {"type": "lesson", "id": lesson.id, "title": lesson.title}
    for item in items:
        if item.required and not item.completed:
            return {"type": item.item_type, "id": item.id, "title": item.reason}
    return {"type": "personalized_assessment", "title": "Passer le test personnalise"}


def first_knowledge_check(blocks: list[dict]) -> dict | None:
    for block in blocks:
        if block.get("type") == "knowledge_check" and isinstance(block.get("content"), dict):
            return block["content"]
    return None


def build_reason(answers: list[AssessmentAnswer], topic: str) -> str:
    count = len(answers)
    plural = "s" if count > 1 else ""
    return f"{count} erreur{plural} liee{plural} a {topic} a ete detectee dans votre evaluation initiale."


def first_block_content(blocks: list[dict], types: set[str]) -> str:
    for block in blocks:
        if block.get("type") in types:
            text = block_content_text(block)
            if text:
                return text
    return ""


def collect_list_items(blocks: list[dict]) -> list[str]:
    items = []
    for block in blocks:
        content = block.get("content")
        if block.get("type") in {"bullet_list", "numbered_list"} and isinstance(content, list):
            items.extend(clean_text(item) for item in content if clean_text(item))
        elif block.get("type") in {"definition", "key_point", "warning"}:
            text = block_content_text(block)
            if text:
                items.append(shorten_text(text, 160))
    return dedupe(items)[:6]


def first_result_preview(results: list[dict]) -> str:
    for result in results:
        text = clean_text(result.get("text") or result.get("text_preview") or "")
        if text:
            return shorten_text(text, 520)
    return "Cette notion doit etre revue a partir du chapitre cible et des corrections de l'evaluation."


def attach_block_sources(blocks: list[dict], sources: list[dict]) -> list[dict]:
    first = sources[0] if sources else {}
    for block in blocks:
        if first.get("document_id"):
            block["generated_from_pdf"] = True
            block["source_document_id"] = first.get("document_id")
            block["source_page_start"] = first.get("page_start")
            block["source_page_end"] = first.get("page_end")
    return blocks


def block_content_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        return clean_text(" ".join(str(item) for item in content))
    if isinstance(content, dict):
        return clean_text(content.get("question") or content.get("answer") or "")
    return clean_text(content)


def format_source_text(source: dict) -> str:
    page = source.get("page_start")
    page_label = f"page {page}" if page else "page non precisee"
    return f"{source.get('source_type', 'source')} - {page_label}"


def sanitize_mermaid(content: Any) -> str:
    text = clean_text(content)
    if not re.match(r"^(flowchart|graph|mindmap|timeline|sequenceDiagram|classDiagram|stateDiagram|erDiagram)\b", text):
        return ""
    if re.search(r"<script|javascript:|click\s+\w+", text, flags=re.IGNORECASE):
        return ""
    return text[:1200]


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def shorten_text(value: Any, max_length: int) -> str:
    text = clean_text(value)
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit(" ", 1)[0].rstrip(" ,;:.") + "."


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def is_admin(user: UserProfile) -> bool:
    return user.role == UserRole.ADMIN.value


def create_deduplicated_notification(db: Session, user_id: int, type_: str, title: str, message: str) -> None:
    existing = db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == type_,
            Notification.title == title,
            Notification.message == message,
        )
    ).first()
    if existing:
        return
    db.add(
        Notification(
            id=f"notif-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            user_id=user_id,
            type=type_,
            title=title,
            message=message,
            read=False,
        )
    )
