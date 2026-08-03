from __future__ import annotations

from app.rag.vector_store import _rerank_results
from app.services.learning_service import _build_french_rag_answer, _select_results_for_intent


def _lesson_result(score: float = 0.62) -> dict:
    return {
        "score": score,
        "document_type": "language_lesson",
        "chapter_title": "Les champs lexicaux",
        "display_source": "Sigma Français 1er Bac — Cours 1, p. 6",
        "source_tier": "supplementary",
        "verified": "supplementary_unverified",
        "text_preview": (
            "Source pédagogique complémentaire: Les champs lexicaux. Page 6. "
            "Un champ lexical est l’ensemble des mots appartenant à une même réalité ou à une même idée. "
            "Ces mots peuvent être des synonymes, appartenir à la même famille ou au même domaine."
        ),
    }


def _exam_result(score: float = 0.78) -> dict:
    return {
        "score": score,
        "document_type": "regional_exam_question",
        "chapter_title": "Examen régional Marrakech-Safi 2017",
        "display_source": "Examen régional Marrakech-Safi 2017 — question 5",
        "source_tier": "validated",
        "verified": "official_verified",
        "text_preview": (
            "Examen: Marrakech-Safi 2017 Oeuvre: La Boîte à merveilles Question 5: "
            "Relevez quatre mots appartenant au champ lexical du sommeil. "
            "Competence: Langue Type: response_short Bareme: 1.0 point(s)."
        ),
    }


def test_definition_query_prefers_lesson_over_exam_metadata() -> None:
    ranked = _rerank_results("Qu’est-ce qu’un champ lexical ?", [_exam_result(), _lesson_result()])
    assert ranked[0]["document_type"] == "language_lesson"


def test_language_result_selection_keeps_lesson_first() -> None:
    selected = _select_results_for_intent(
        "Qu’est-ce qu’un champ lexical ?",
        "language_help",
        [_exam_result(), _lesson_result()],
    )
    assert selected[0]["document_type"] == "language_lesson"


def test_language_answer_is_pedagogical_not_a_raw_chunk_dump() -> None:
    answer = _build_french_rag_answer(
        "Qu’est-ce qu’un champ lexical ?",
        "Intermédiaire",
        [_lesson_result(), _exam_result()],
        "language_help",
        [],
    )
    normalized = answer.lower()
    assert "un champ lexical est" in normalized
    assert "même idée" in normalized
    assert "comment le reconnaître" in normalized
    assert "bareme" not in normalized
    assert "competence:" not in normalized
    assert "type: response_short" not in normalized
    assert "examen:" not in normalized
