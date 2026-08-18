from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.persistence import Course, CourseChapter, CourseExample, CourseObjective, CourseSkill, UserProfile
from app.schemas.lesson_content import validate_structured_blocks
from app.services import professor_service

DOCS_DIR = Path(get_settings().get("docs_dir") or Path(__file__).resolve().parents[2] / "docs") / "courses"


def build_content_from_pdf(db: Session, current_user: UserProfile, course_id: int) -> dict:
    course = professor_service.get_professor_owned_course(db, current_user, course_id)
    if not course.pdf_url:
        raise HTTPException(status_code=400, detail="Aucun PDF n'est associe a ce cours")
    pdf_path = DOCS_DIR / Path(course.pdf_url).name
    if not _is_safe_doc_path(pdf_path) or not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Le support PDF associe est introuvable")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Le support associe n'est pas un PDF valide")

    before = {
        "course_id": course.id,
        "content_import_status": course.content_import_status,
        "chapter_count": len(course.chapters),
    }
    course.content_import_status = "processing"
    course.content_import_error = None
    db.commit()

    try:
        pages = extract_pdf_pages(pdf_path)
        if not any(page["text"].strip() for page in pages):
            raise HTTPException(status_code=400, detail="Aucun texte exploitable n'a ete extrait du PDF")
        draft = structure_pdf_for_course(course, pages, Path(course.pdf_url).name)
        apply_import_draft(course, draft)
        course.published = False
        course.status = "draft"
        course.content_import_status = "ready_for_review"
        course.content_import_error = None
        course.content_imported_at = datetime.utcnow()
        db.commit()
        db.refresh(course)
        result = {
            "course_id": course.id,
            "status": course.content_import_status,
            "chapters": [
                {"id": chapter.id, "title": chapter.title, "blocks": len(chapter.structured_content or [])}
                for chapter in course.chapters
            ],
            "summary": course.summary,
            "objectives": [objective.text for objective in course.objectives],
            "generated_from_pdf": True,
        }
        professor_service.create_audit_log(db, current_user, "import_course_content_from_pdf", "course", course.id, before, result)
        db.commit()
        return result
    except HTTPException as exc:
        course.content_import_status = "failed"
        course.content_import_error = str(exc.detail)
        db.commit()
        raise
    except Exception as exc:
        course.content_import_status = "failed"
        course.content_import_error = "Import PDF impossible. Verifiez que le document est lisible."
        db.commit()
        raise HTTPException(status_code=500, detail=course.content_import_error) from exc


def get_import_status(db: Session, current_user: UserProfile, course_id: int) -> dict:
    course = professor_service.get_professor_owned_course(db, current_user, course_id)
    return {
        "course_id": course.id,
        "status": course.content_import_status,
        "error": course.content_import_error,
        "imported_at": course.content_imported_at.isoformat() if course.content_imported_at else None,
    }


def extract_pdf_pages(pdf_path: Path) -> list[dict[str, Any]]:
    candidates_by_page = []
    fitz_pages = extract_with_pymupdf(pdf_path)
    pypdf_pages = extract_with_pypdf(pdf_path)
    plumber_pages = extract_with_pdfplumber(pdf_path)
    page_count = max(len(fitz_pages), len(pypdf_pages), len(plumber_pages))
    pages = []
    for index in range(page_count):
        candidates = [
            {"engine": "pymupdf", "text": fitz_pages[index] if index < len(fitz_pages) else ""},
            {"engine": "pypdf", "text": pypdf_pages[index] if index < len(pypdf_pages) else ""},
            {"engine": "pdfplumber", "text": plumber_pages[index] if index < len(plumber_pages) else ""},
        ]
        scored = []
        for candidate in candidates:
            text = normalize_text(candidate["text"])
            scored.append({**candidate, "text": text, "quality": score_text_quality(text)})
        best = max(scored, key=lambda item: item["quality"]["score"])
        if best["quality"]["score"] < 20:
            ocr_text = extract_with_ocr_page(pdf_path, index)
            if ocr_text:
                ocr_quality = score_text_quality(ocr_text)
                if ocr_quality["score"] > best["quality"]["score"]:
                    best = {"engine": "ocr", "text": normalize_text(ocr_text), "quality": ocr_quality}
        pages.append({"page_number": index + 1, "text": best["text"], "engine": best["engine"], "quality": best["quality"]})
        candidates_by_page.append(scored)
    return pages


def extract_with_pymupdf(pdf_path: Path) -> list[str]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []
    pages = []
    with fitz.open(str(pdf_path)) as document:
        for page in document:
            pages.append(page.get_text("text") or "")
    return pages


def extract_with_pypdf(pdf_path: Path) -> list[str]:
    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def extract_with_pdfplumber(pdf_path: Path) -> list[str]:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return []
    pages = []
    with pdfplumber.open(str(pdf_path)) as document:
        for page in document.pages:
            pages.append(page.extract_text() or "")
    return pages


def extract_with_ocr_page(pdf_path: Path, page_index: int) -> str:
    try:
        import fitz  # type: ignore
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    try:
        with fitz.open(str(pdf_path)) as document:
            page = document[page_index]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            return pytesseract.image_to_string(image, lang="fra+eng")
    except Exception:
        return ""


def score_text_quality(text: str) -> dict[str, Any]:
    clean = text.strip()
    if not clean:
        return {"score": 0, "length": 0, "alpha_ratio": 0, "one_letter_words": 0, "broken_words": 0}
    letters = sum(1 for char in clean if char.isalpha())
    alpha_ratio = letters / max(1, len(clean))
    words = re.findall(r"\b\w+\b", clean, flags=re.UNICODE)
    one_letter_words = sum(1 for word in words if len(word) == 1)
    broken_patterns = sum(clean.lower().count(pattern) for pattern in ["py hon", "in roduc", "programma ion", "u iliser", "i re", "h p"])
    replacement_chars = clean.count("\ufffd") + clean.count("ï¿½")
    abnormal_spaces = len(re.findall(r"\b\w{1,2}\s+\w{1,2}\s+\w{1,2}\b", clean))
    score = min(len(clean) / 40, 50) + alpha_ratio * 35
    score -= min(one_letter_words * 0.8, 18)
    score -= broken_patterns * 12
    score -= replacement_chars * 5
    score -= min(abnormal_spaces * 0.5, 10)
    return {
        "score": round(max(0, score), 2),
        "length": len(clean),
        "alpha_ratio": round(alpha_ratio, 3),
        "one_letter_words": one_letter_words,
        "broken_words": broken_patterns,
        "replacement_chars": replacement_chars,
        "abnormal_spaces": abnormal_spaces,
    }


def structure_pdf_for_course(course: Course, pages: list[dict[str, Any]], document_id: str) -> dict:
    full_text = "\n".join(page["text"] for page in pages)
    lower = full_text.lower()
    compact = re.sub(r"\s+", "", lower)
    if ("python" in compact or "pyhon" in compact or "py hon" in lower) and ("programmation" in compact or "programma" in lower or "programmer" in lower):
        raise HTTPException(
            status_code=422,
            detail=(
                "Support hors pÃ©rimÃ¨tre refusÃ© : EduMentor AI accepte uniquement "
                "les contenus liÃ©s au rÃ©gional de franÃ§ais de 1Ã¨re Bac Maroc."
            ),
        )
    return build_generic_structure(course, pages, document_id)


def build_generic_structure(course: Course, pages: list[dict[str, Any]], document_id: str) -> dict:
    candidates = detect_headings(pages)
    selected = candidates[:5] or [{"title": course.title, "page": pages[0]["page_number"]}]
    chapters = []
    for index, item in enumerate(selected, start=1):
        page = next((page for page in pages if page["page_number"] == item["page"]), pages[0])
        excerpt = first_sentences(page["text"], 5)
        chapters.append({
            "title": item["title"],
            "duration": "25 min",
            "estimated_duration": "25 min",
            "content": excerpt,
            "structured_content": validate_structured_blocks([
                block("heading", item["title"], "", document_id, item["page"], item["page"]),
                block("paragraph", None, excerpt, document_id, item["page"], item["page"]),
                block("summary", "RÃ©sumÃ©", summarize_excerpt(excerpt), document_id, item["page"], item["page"]),
            ]),
            "status": "active" if index == 1 else "locked",
            "openable": index == 1,
        })
    return {
        "summary": first_sentences("\n".join(page["text"] for page in pages), 3),
        "objectives": [f"Comprendre : {chapter['title']}" for chapter in chapters[:5]],
        "skills": ["Lire un support pÃ©dagogique", "Identifier les notions clÃ©s du document"],
        "examples": [],
        "chapters": chapters,
    }


def apply_import_draft(course: Course, draft: dict) -> None:
    course.summary = draft.get("summary") or course.summary
    course.objectives = [CourseObjective(text=item, position=index) for index, item in enumerate(draft.get("objectives", []), start=1)]
    course.skills = [CourseSkill(text=item, position=index) for index, item in enumerate(draft.get("skills", []), start=1)]
    course.examples = [
        CourseExample(title=item.get("title", f"Exemple {index}"), description=item.get("description", ""), position=index)
        for index, item in enumerate(draft.get("examples", []), start=1)
    ]
    course.chapters = [
        CourseChapter(
            title=item["title"],
            duration=item.get("duration", "25 min"),
            estimated_duration=item.get("estimated_duration", item.get("duration", "25 min")),
            content=item.get("content", ""),
            structured_content=item.get("structured_content", []),
            status=item.get("status", "locked"),
            openable=item.get("openable", False),
            completed=False,
            active=True,
            position=index,
        )
        for index, item in enumerate(draft.get("chapters", []), start=1)
    ]


def block(block_type: str, title: str | None, content: Any, document_id: str, page_start: int, page_end: int, diagram_type: str | None = None) -> dict:
    data = {
        "type": block_type,
        "title": title,
        "content": content,
        "source_document_id": document_id,
        "source_page_start": page_start,
        "source_page_end": page_end,
        "generated_from_pdf": True,
    }
    if diagram_type:
        data["diagram_type"] = diagram_type
    return data


def find_pages_for_keywords(pages: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
    return [page for page in pages if any(keyword.lower() in page["text"].lower() for keyword in keywords)]


def build_excerpt(pages: list[dict[str, Any]], keywords: list[str], max_sentences: int = 5) -> str:
    fragments = []
    for page in pages:
        sentences = split_sentences(page["text"])
        fragments.extend(sentence for sentence in sentences if any(keyword.lower() in sentence.lower() for keyword in keywords))
    return " ".join(fragments[:max_sentences]) or first_sentences(" ".join(page["text"] for page in pages), max_sentences)


def summarize_excerpt(excerpt: str) -> str:
    return first_sentences(excerpt, 2) if excerpt else "Le PDF prÃ©sente cette notion comme un Ã©lÃ©ment d'introduction."


def exercise_for_topic(title: str) -> str:
    if "erreurs" in title.lower():
        return "Repérez deux erreurs fréquentes dans une réponse de régional et proposez une correction."
    return "Reformulez la notion avec vos mots, puis appliquez-la à une phrase ou à un court extrait."


def summary_for_topic(title: str) -> str:
    return f"Ce chapitre sert d'introduction Ã  : {title}. Les Ã©lÃ©ments affichÃ©s proviennent du PDF associÃ© au cours."


def detect_headings(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headings = []
    for page in pages:
        for line in page["text"].splitlines():
            clean = line.strip()
            if 5 <= len(clean) <= 90 and (clean.isupper() or re.match(r"^\d+[.)-]\s+", clean)):
                headings.append({"title": clean.strip(" .-"), "page": page["page_number"]})
    return headings


def normalize_text(text: str) -> str:
    clean = text.replace("\x00", "")
    clean = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", clean)
    clean = re.sub(r"[ \t]+", " ", clean)
    lines = [line.strip() for line in clean.splitlines()]
    filtered: list[str] = []
    for line in lines:
        if not line:
            filtered.append("")
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue
        if line.lower() in {"introduction Ã  python", "introduction a python"}:
            continue
        filtered.append(line)
    clean = "\n".join(filtered)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def public_pdf_name(document_id: str) -> str:
    name = Path(document_id).name
    match = re.match(r"^professor_\d+_course_\d+_[0-9a-f]{32}_(.+\.pdf)$", name, flags=re.IGNORECASE)
    return match.group(1) if match else name


def split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(<=[.!])\\s+", text) if sentence.strip()]


def first_sentences(text: str, limit: int) -> str:
    return " ".join(split_sentences(text)[:limit]).strip()


def _is_safe_doc_path(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(DOCS_DIR.resolve())
    except FileNotFoundError:
        return path.parent.resolve().is_relative_to(DOCS_DIR.resolve())
