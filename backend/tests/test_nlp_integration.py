from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth_dependencies, nlp_routes
from app.models.persistence import UserProfile


def build_nlp_client(current_user: UserProfile | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(nlp_routes.router, prefix="/api")
    if current_user is not None:
        app.dependency_overrides[auth_dependencies.get_current_user] = lambda: current_user
        app.dependency_overrides[nlp_routes.get_current_user] = lambda: current_user
    return TestClient(app)


def professor() -> UserProfile:
    return UserProfile(id=991, email="prof-nlp@example.com", full_name="Prof NLP", role="professor", status="active")


def test_nlp_models_status_is_protected():
    response = build_nlp_client().get("/api/nlp/models/status")

    assert response.status_code == 401


def test_nlp_models_status_hides_holdout():
    response = build_nlp_client(professor()).get("/api/nlp/models/status")
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["holdout_loaded"] is False
    assert data["chapters_loaded"] >= 70


def test_nlp_units_lists_safe_metadata_only():
    response = build_nlp_client(professor()).get("/api/nlp/units")
    body = response.json()["data"]
    first = body["units"][0]

    assert response.status_code == 200
    assert body["total"] >= 70
    assert {"unit_id", "work_id", "work_title", "unit_type", "unit_number", "unit_title", "themes"} <= set(first)
    assert "base_summary" not in first
    assert "holdout" not in str(body).lower()


def test_nlp_units_filter_by_work_id():
    response = build_nlp_client(professor()).get("/api/nlp/units?work_id=ANT")
    units = response.json()["data"]["units"]

    assert response.status_code == 200
    assert units
    assert all(unit["work_id"] == "ANT" for unit in units)


def test_nlp_units_searches_title_and_theme():
    response = build_nlp_client(professor()).get("/api/nlp/units?search=Antigone")
    units = response.json()["data"]["units"]

    assert response.status_code == 200
    assert units
    assert any("Antigone" in unit["work_title"] or "Antigone" in unit["unit_title"] for unit in units)


def test_nlp_figures_endpoint():
    response = build_nlp_client(professor()).post(
        "/api/nlp/figures",
        json={"text": "La nuit murmure a l'oreille d'Antigone."},
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["contains_figure"] is True
    assert data["figure_type"]


def test_nlp_exam_competence_endpoint():
    response = build_nlp_client(professor()).post(
        "/api/nlp/exam-competence",
        json={"text": "Expliquez la valeur symbolique de cette scene."},
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["competence"] == "interpretation"


def test_nlp_qa_generate_with_valid_unit():
    response = build_nlp_client(professor()).post(
        "/api/nlp/qa/generate",
        json={"unit_id": "ANT_SEQ01", "task": "comprehension", "level": "intermediaire"},
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["question"]
    assert data["correction"]
    assert data["requires_human_validation"] is True


def test_nlp_qa_generate_invalid_unit_returns_422():
    response = build_nlp_client(professor()).post(
        "/api/nlp/qa/generate",
        json={"unit_id": "UNKNOWN_UNIT", "task": "comprehension", "level": "intermediaire"},
    )

    assert response.status_code == 422
    assert "unit_id inconnu" in response.text
