from __future__ import annotations

from pathlib import Path

from app.services.sigma_french_pdf_service import (
    ALL_SECTIONS,
    IGNORED_PAGES,
    SIGMA_SOURCE_PDF,
    build_sigma_documents,
    clean_sigma_page,
    infer_exam_document_type,
    infer_work,
)


def test_sigma_section_plan_covers_expected_material() -> None:
    assert len(ALL_SECTIONS) == 16
    assert 1 in IGNORED_PAGES
    assert 15 in IGNORED_PAGES
    assert 30 in IGNORED_PAGES
    assert 134 in IGNORED_PAGES


def test_clean_sigma_page_removes_repeated_watermark_and_arabic_noise() -> None:
    raw = "Français Français\nالتربية الإسلامية\n11 11\nCours 5 : Cours 5 : Figures de style\nFor more visit: L9ray.com"
    cleaned = clean_sigma_page(raw, 11)
    assert "L9ray" not in cleaned
    assert "التربية" not in cleaned
    assert cleaned.count("Cours 5") == 1
    assert "Figures de style" in cleaned


def test_inference_helpers() -> None:
    assert infer_work("Sidi Mohammed et Lalla Zoubida") == "La Boîte à merveilles"
    assert infer_work("Créon parle à Antigone") == "Antigone"
    assert infer_work("Victor Hugo décrit le condamné") == "Le Dernier Jour d'un condamné"
    assert infer_exam_document_type("CORRIGÉ DE L'EXAMEN", "regional_exam_question") == "regional_exam_correction"
    assert infer_exam_document_type("II - Production écrite", "regional_exam_question") == "writing_topic"


def test_real_pdf_builds_structured_documents_when_present() -> None:
    pdf = Path(SIGMA_SOURCE_PDF)
    if not pdf.exists():
        return
    documents, extraction = build_sigma_documents(pdf, None, None)
    assert extraction["pdf_pages"] == 160
    assert len(documents) == 16
    assert sum(len(document.chunks) for document in documents) > 100
    assert any(document.relative_path.as_posix().endswith("figures_de_style.md") for document in documents)
    assert any(document.relative_path.as_posix().endswith("antigone.md") for document in documents)
