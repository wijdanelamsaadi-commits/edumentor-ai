from __future__ import annotations

from app.services.adaptive_generation_benchmark_service import build_metrics, metric_to_row, recommended_solution


def _content(summary_words: int, explanation_words: int, support_words: int, key_points: int, vocabulary: int) -> dict:
    return {
        "summary": " ".join(f"resume{i}" for i in range(summary_words)),
        "explanation": " ".join(f"explication{i}" for i in range(explanation_words)),
        "key_points": [{"title": f"Point {i}", "content": "contenu contextualise"} for i in range(key_points)],
        "vocabulary": [{"term": f"Terme {i}", "definition": "definition contextuelle suffisante"} for i in range(vocabulary)],
        "guided_example": {"title": "Exemple", "content": "exemple guide complet"},
        "learning_support": {"method": " ".join(f"support{i}" for i in range(support_words)), "steps": [], "pitfalls": [], "memory_tip": ""},
        "practice_question": {"question": "Question claire ?", "expected_answer": "Reponse attendue developpee", "explanation": "Correction expliquee"},
    }


def test_benchmark_metrics_use_beginner_thresholds():
    metric = build_metrics(
        level="debutant",
        solution="Groq",
        model="openai/gpt-oss-20b",
        execution_type="api",
        status="completed",
        duration_seconds=1.0,
        calls=2,
        http_statuses=[200, 200],
        json_valid=True,
        repairs=0,
        content=_content(80, 140, 80, 4, 4),
        errors=[],
        resources={"cpu": "test"},
        cost="test",
        strengths=[],
        limits=[],
    )

    assert metric["level"] == "debutant"
    assert metric["level_requirements_respected"] is True


def test_benchmark_metrics_use_intermediate_thresholds():
    metric = build_metrics(
        level="intermediaire",
        solution="Ollama local",
        model="qwen3:1.7b",
        execution_type="local",
        status="completed",
        duration_seconds=1.0,
        calls=2,
        http_statuses=["local"],
        json_valid=True,
        repairs=0,
        content=_content(109, 200, 100, 5, 5),
        errors=[],
        resources={"cpu": "test"},
        cost="test",
        strengths=[],
        limits=[],
    )

    assert metric["level"] == "intermediaire"
    assert metric["level_requirements_respected"] is False


def test_benchmark_row_contains_level_and_recommendation():
    metric = build_metrics(
        level="debutant",
        solution="Groq",
        model="openai/gpt-oss-20b",
        execution_type="api",
        status="completed",
        duration_seconds=1.0,
        calls=2,
        http_statuses=[200, 200],
        json_valid=True,
        repairs=0,
        content=_content(80, 140, 80, 4, 4),
        errors=[],
        resources={"cpu": "test"},
        cost="test",
        strengths=[],
        limits=[],
    )
    recommendation, justification = recommended_solution([metric])
    row = metric_to_row(metric, recommendation, justification)

    assert row["Niveau"] == "debutant"
    assert row["Choix recommande"] == "Groq"
