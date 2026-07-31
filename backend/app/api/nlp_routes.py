from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth_dependencies import get_current_user
from app.models.persistence import UserProfile
from app.nlp_runtime.schemas import (
    AdaptationRequest,
    AnalyzeAllRequest,
    ContentTypeRequest,
    CorrectionRequest,
    GenericResponse,
    QuestionGenerationRequest,
    TextRequest,
)
from app.nlp_runtime.services.adaptation import adapt_text
from app.nlp_runtime.services.content import predict_content_type
from app.nlp_runtime.services.figures_exam import (
    analyze_figure,
    classify_exam_competence,
)
from app.nlp_runtime.services.level import predict_level
from app.nlp_runtime.services.qa import correct_question, generate_pair
from app.nlp_runtime.services.registry import get_registry
from app.nlp_runtime.services.unified import analyze_all


router = APIRouter(
    prefix="/nlp",
    tags=["EduMentor NLP"],
)


def _response(
    data: dict,
    warnings: list[str] | None = None,
) -> GenericResponse:
    return GenericResponse(
        ok=True,
        data=data,
        warnings=warnings or [],
    )


def _safe(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/models/status",
    response_model=GenericResponse,
)
def model_status(
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    return _response(get_registry().status())


@router.get(
    "/units",
    response_model=GenericResponse,
)
def pedagogical_units(
    work_id: str = Query(default=""),
    search: str = Query(default=""),
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    registry = get_registry()
    clean_work_id = work_id.strip().lower()
    clean_search = search.strip().lower()
    units = []
    for unit in registry.chapter_index.values():
        if clean_work_id and str(unit.get("work_id", "")).lower() != clean_work_id:
            continue
        searchable = " ".join(
            str(unit.get(key, ""))
            for key in ("unit_id", "work_id", "work_title", "unit_title", "themes")
        ).lower()
        if clean_search and clean_search not in searchable:
            continue
        units.append({
            "unit_id": unit.get("unit_id"),
            "work_id": unit.get("work_id"),
            "work_title": unit.get("work_title"),
            "unit_type": unit.get("unit_type"),
            "unit_number": unit.get("unit_number"),
            "unit_title": unit.get("unit_title"),
            "themes": split_pipe(unit.get("themes", "")),
        })
    units.sort(key=lambda item: (item["work_title"] or "", item["unit_number"] or 0, item["unit_id"] or ""))
    return _response({
        "total": len(units),
        "units": units,
    })


@router.post(
    "/level",
    response_model=GenericResponse,
)
def level_endpoint(
    payload: TextRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    return _response(predict_level(get_registry(), payload.text))


@router.post(
    "/content-type",
    response_model=GenericResponse,
)
def content_type_endpoint(
    payload: ContentTypeRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    return _response(
        predict_content_type(
            get_registry(),
            text=payload.text,
            instruction=payload.instruction,
            ui_section=payload.ui_section,
            context=payload.context,
            pair_role=payload.pair_role,
            competence=payload.competence,
            language_skill=payload.language_skill,
            bloom_verb=payload.bloom_verb,
        )
    )


@router.post(
    "/adapt",
    response_model=GenericResponse,
)
def adapt_endpoint(
    payload: AdaptationRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    data = adapt_text(
        get_registry(),
        source_text=payload.source_text,
        source_level=payload.source_level.value,
        target_level=payload.target_level.value,
        content_type=payload.content_type,
        unit_title=payload.unit_title,
        adaptation_id=payload.adaptation_id,
    )
    return _response(
        data,
        warnings=["Validation pédagogique humaine obligatoire."],
    )


@router.post(
    "/qa/generate",
    response_model=GenericResponse,
)
def qa_generate_endpoint(
    payload: QuestionGenerationRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    data = _safe(
        generate_pair,
        get_registry(),
        unit_id=payload.unit_id,
        task=payload.task.value,
        level=payload.level.value,
    )
    return _response(
        data,
        warnings=["Question et correction à relire avant publication."],
    )


@router.post(
    "/qa/correct",
    response_model=GenericResponse,
)
def qa_correct_endpoint(
    payload: CorrectionRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    data = _safe(
        correct_question,
        get_registry(),
        question=payload.question,
        task=payload.task.value if payload.task else None,
        level=payload.level.value if payload.level else None,
        unit_id=payload.unit_id,
        pair_id=payload.pair_id,
    )
    return _response(
        data,
        warnings=["Correction automatique à valider par un enseignant."],
    )


@router.post(
    "/figures",
    response_model=GenericResponse,
)
def figures_endpoint(
    payload: TextRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    return _response(analyze_figure(get_registry(), payload.text))


@router.post(
    "/exam-competence",
    response_model=GenericResponse,
)
def exam_competence_endpoint(
    payload: TextRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    return _response(
        classify_exam_competence(get_registry(), payload.text)
    )


@router.post(
    "/analyze-all",
    response_model=GenericResponse,
)
def analyze_all_endpoint(
    payload: AnalyzeAllRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> GenericResponse:
    _ = current_user
    data = analyze_all(
        get_registry(),
        text=payload.text,
        instruction=payload.instruction,
        ui_section=payload.ui_section,
        context=payload.context,
        pair_role=payload.pair_role,
        competence=payload.competence,
        language_skill=payload.language_skill,
        bloom_verb=payload.bloom_verb,
        treat_as_exam_question=payload.treat_as_exam_question,
    )
    return _response(
        data,
        warnings=[
            "Les scores automatiques ne remplacent pas la validation pedagogique."
        ],
    )


def split_pipe(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split("|") if part.strip()]