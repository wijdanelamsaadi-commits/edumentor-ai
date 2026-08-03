from app.rag.vector_store import _expand_long_list_results, _rerank_results
from app.services.learning_service import (
    _build_work_explanation_answer,
    _detect_french_bac_intent,
    _extract_work_characters,
    _format_chat_sources,
    _select_results_for_intent,
)


WORK_CONTENT = """
LA BOITE À MERVEILLES
Les personnages et leur statut :
Personnages principaux :
- Mohammed, le personnage principal, l’enfant de six ans.
- Lalla Zoubida, la mère.
- Si Abdeslem, le père.
Personnages secondaires :
- Kenza, la chouafa.
- Rahma, une voisine.
- Fatma Bziouya, une voisine.
La structure de l’œuvre :
CHAPITRES THÉMATIQUE
"""


def _work_result(score=0.55):
    return {
        "score": score,
        "content": WORK_CONTENT,
        "text_preview": WORK_CONTENT[:320],
        "document_type": "work_sheet",
        "chapter_title": "La Boîte à merveilles — fiche de lecture",
        "display_source": "Sigma Français 1er Bac — La Boîte à merveilles, p. 16",
        "work": "La Boîte à merveilles",
        "verified": "supplementary_unverified",
        "source_tier": "supplementary",
    }


def _exam_result(score=0.80):
    text = "Examen régional. Donnez le titre de l’œuvre. Correction : La Boîte à merveilles."
    return {
        "score": score,
        "content": text,
        "text_preview": text,
        "document_type": "regional_exam_question",
        "chapter_title": "Examen régional de français",
        "display_source": "Examen régional 2021 — question 1",
        "work": "La Boîte à merveilles",
        "verified": "official_verified",
        "source_tier": "official",
    }


def test_character_question_is_work_explanation():
    assert _detect_french_bac_intent("Quels sont les personnages de La Boîte à merveilles ?") == "work_explanation"


def test_character_query_reranks_work_sheet_before_exam_question():
    results = _rerank_results(
        "Quels sont les personnages de La Boîte à merveilles ?",
        [_exam_result(), _work_result()],
    )
    assert results[0]["document_type"] == "work_sheet"


def test_work_selector_keeps_matching_work_sheet():
    selected = _select_results_for_intent(
        "Quels sont les personnages de La Boîte à merveilles ?",
        "work_explanation",
        [_exam_result(), _work_result()],
    )
    assert selected
    assert selected[0]["document_type"] == "work_sheet"


def test_extracts_principal_and_secondary_characters():
    characters = _extract_work_characters(WORK_CONTENT)
    assert any("Mohammed" in item for item in characters["principaux"])
    assert any("Lalla Zoubida" in item for item in characters["principaux"])
    assert any("Kenza" in item for item in characters["secondaires"])


def test_work_answer_contains_real_characters_not_exam_metadata():
    answer = _build_work_explanation_answer(
        "Quels sont les personnages de La Boîte à merveilles ?",
        [_work_result()],
        [],
        "",
    )
    assert "Personnages principaux" in answer
    assert "Mohammed" in answer
    assert "Lalla Zoubida" in answer
    assert "Donnez le titre de l’œuvre" not in answer
    assert "Barème" not in answer


def test_long_character_list_expands_neighboring_sigma_chunks_in_order():
    first = {
        "chunk_id": "bam-p16-c1",
        "document_id": 42,
        "score": 0.91,
        "content": """LA BOITE A MERVEILLES
Personnages principaux :
- Mohammed, le personnage principal, l'enfant de six ans.
- Lalla Zoubida, la mere.
- Si Abdeslem, le pere.
Personnages secondaires :
- Kenza, la chouafa.
- Rahma, une voisine.""",
        "text_preview": "Personnages principaux et secondaires",
        "document_type": "work_characters",
        "source_name": "Sigma Francais 1er Bac",
        "work": "La Boite a merveilles",
        "page_start": 16,
        "page_end": 16,
        "chunk_index": 1,
    }
    second = {
        **first,
        "chunk_id": "bam-p16-c2",
        "content": """- Fatma Bziouya, une voisine.
- Lalla Aicha, une ancienne voisine et amie de la mere de Mohammed.
- Zineb, la fille de Rahma.
- Salma, la marieuse professionnelle.
- Driss El Aouad, le mari de Rahma.""",
        "chunk_index": 2,
    }
    third = {
        **first,
        "chunk_id": "bam-p17-c1",
        "content": """- Moulay Arbi, le mari de Lalla Aicha.
- Abdellah, epicier et conteur.
- Si Abderrahman, le coiffeur du pere et de l'enfant.
- Le fquih, le maitre de l'ecole coranique.
- Driss le teigneux, l'apprenti du pere.
- Si El Arafi, le voyant.
La structure de l'oeuvre :""",
        "page_start": 17,
        "page_end": 17,
        "chunk_index": 3,
    }
    antigone = {
        **first,
        "chunk_id": "antigone-p21-c1",
        "document_id": 43,
        "work": "Antigone",
        "content": "Antigone, Creon et Ismene sont les personnages de la piece.",
        "page_start": 21,
        "page_end": 21,
        "chunk_index": 1,
    }

    expanded = _expand_long_list_results(
        "Quels sont les personnages principaux et secondaires de La Boite a merveilles ?",
        [first, second, third, antigone],
        collection=None,
    )
    assert [item["chunk_id"] for item in expanded[:3]] == ["bam-p16-c1", "bam-p16-c2", "bam-p17-c1"]
    assert all(item["work"] == "La Boite a merveilles" for item in expanded[:3])

    answer = _build_work_explanation_answer(
        "Quels sont les personnages principaux et secondaires de La Boite a merveilles ?",
        expanded[:3],
        [],
        "",
    )
    for expected in ("Mohammed", "Lalla Zoubida", "Si Abdeslem", "Kenza", "Rahma", "Lalla Aicha"):
        assert expected in answer
    assert "Creon" not in answer
    assert "Classez les personnages suivants" in answer

    sources = _format_chat_sources([
        {**item, "display_source": f"Sigma Francais 1er Bac — La Boite a merveilles, p. {item['page_start']}"}
        for item in expanded[:3]
    ])
    assert len(sources) == 1
    assert sources[0]["page_start"] == 16
    assert sources[0]["page_end"] == 17
    assert "16–17" in sources[0]["display_source"]