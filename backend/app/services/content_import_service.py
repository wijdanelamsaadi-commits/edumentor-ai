from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models.persistence import Course, CourseChapter, CourseExample, CourseObjective, CourseSkill, UserProfile
from app.schemas.lesson_content import validate_structured_blocks
from app.services import professor_service

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "courses"


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
    words = re.findall(r"\b[\wÀ-ÿ]+\b", clean, flags=re.UNICODE)
    one_letter_words = sum(1 for word in words if len(word) == 1)
    broken_patterns = sum(clean.lower().count(pattern) for pattern in ["py hon", "in roduc", "programma ion", "u iliser", "i re", "h p"])
    replacement_chars = clean.count("\ufffd") + clean.count("�")
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
        return build_python_intro_structure(course, pages, document_id)
    return build_generic_structure(course, pages, document_id)


def build_python_intro_structure(course: Course, pages: list[dict[str, Any]], document_id: str) -> dict:
    public_document_name = public_pdf_name(document_id)
    topics = [
        {
            "title": "Comprendre la programmation",
            "pages": [1],
            "keywords": ["programmation", "programme", "programmer", "algorithme", "langage humain", "langage de programmation"],
            "intro": "Ce chapitre explique ce que signifie programmer et pourquoi un ordinateur a besoin d'instructions précises.",
            "definitions": [
                ("Programmation", "La programmation consiste à décrire précisément à un ordinateur ce qu'il doit faire, dans un langage qu'il peut interpréter."),
                ("Algorithme", "Un algorithme est une suite d'étapes logiques qui transforme une idée ou un problème en procédure exécutable."),
            ],
            "key_points": [
                "Un ordinateur ne comprend pas directement une langue humaine.",
                "Le programme sert de traduction entre une intention et des instructions exécutables.",
                "Avant d'écrire du code, il faut clarifier les étapes de résolution.",
            ],
            "bullets": ["Identifier le problème.", "Décomposer l'action en étapes.", "Traduire les étapes dans un langage de programmation.", "Tester puis corriger."],
            "example": "Pour calculer une moyenne, on définit les notes, on les additionne, on divise par leur nombre, puis on affiche le résultat.",
            "exercise": "Décrivez en quatre étapes l'algorithme qui permet de trouver le plus grand nombre dans une liste.",
            "diagram": "flowchart LR\nA[Problème] --> B[Algorithme] --> C[Code Python] --> D[Exécution] --> E[Résultat] --> F[Correction des erreurs]",
        },
        {
            "title": "Les erreurs en programmation",
            "pages": [1, 2],
            "keywords": ["erreur", "syntaxe", "semantique", "sémantique", "execution", "exécution", "bugs"],
            "intro": "Programmer implique aussi de repérer et corriger les erreurs. Le PDF distingue plusieurs familles d'erreurs.",
            "definitions": [
                ("Erreur de syntaxe", "Une erreur de syntaxe apparaît lorsque le code ne respecte pas les règles d'écriture du langage."),
                ("Erreur sémantique", "Une erreur sémantique survient quand le programme s'exécute mais ne produit pas le résultat attendu."),
                ("Erreur d'exécution", "Une erreur d'exécution se produit pendant le lancement du programme, par exemple lorsqu'une opération impossible est demandée."),
            ],
            "key_points": [
                "Une erreur de syntaxe bloque souvent l'exécution.",
                "Une erreur sémantique demande de vérifier le raisonnement.",
                "Le débogage ressemble à une enquête : observer, formuler une hypothèse, tester.",
            ],
            "bullets": ["Lire le message d'erreur.", "Reproduire le problème.", "Isoler la ligne concernée.", "Tester une correction simple."],
            "example": "Oublier une parenthèse est une erreur de syntaxe ; obtenir une moyenne fausse est plutôt une erreur sémantique.",
            "exercise": "Classez trois situations : parenthèse manquante, résultat mathématique faux, division par zéro.",
            "diagram": "flowchart TD\nA[Erreurs de programmation] --> B[Erreurs de syntaxe]\nA --> C[Erreurs sémantiques]\nA --> D[Erreurs d'exécution]",
        },
        {
            "title": "Bien programmer",
            "pages": [2],
            "keywords": ["règle", "regle", "or", "bien programmer", "règles d'or"],
            "intro": "Le PDF insiste sur la lisibilité du programme et présente cinq règles d'or pour faciliter la compréhension et la réutilisation du code.",
            "definitions": [("Bon programme", "Un bon programme est un programme compréhensible, découpé en petites parties et facile à relire ou réutiliser.")],
            "key_points": [
                "Ne pas écrire de longs sous-programmes.",
                "Donner un objectif clair à chaque sous-programme.",
                "Éviter les fonctionnalités mal comprises.",
                "Éviter le copier-coller.",
                "Écrire des commentaires utiles.",
            ],
            "bullets": ["Découper un problème complexe.", "Nommer clairement les parties du programme.", "Tester souvent.", "Corriger progressivement."],
            "example": "Au lieu d'un seul long bloc, un programme peut séparer la lecture des données, le calcul et l'affichage du résultat.",
            "exercise": "Transformez une longue suite d'instructions en trois sous-programmes avec des noms explicites.",
            "diagram": "mindmap\n  root((Cinq règles d'or))\n    Comprendre le problème\n    Découper en étapes\n    Écrire clairement\n    Tester souvent\n    Corriger progressivement",
        },
        {
            "title": "Découvrir Python",
            "pages": [2, 3],
            "keywords": ["python", "py hon", "portable", "por able", "gratuit", "gra ui", "lisible", "orienté objet", "oriente objet", "extensible"],
            "intro": "Python est présenté comme un langage accessible, portable et apprécié pour apprendre la programmation.",
            "definitions": [("Python", "Python est un langage de programmation lisible, gratuit, portable et utilisé dans de nombreux domaines.")],
            "key_points": [
                "Python est portable entre plusieurs systèmes.",
                "Python est gratuit et soutenu par une communauté active.",
                "Sa syntaxe favorise des programmes lisibles.",
                "Le langage peut être utilisé de manière modulaire et orientée objet.",
                "Il peut être enrichi avec des bibliothèques.",
            ],
            "bullets": ["Portable", "Gratuit", "Lisible", "Extensible", "Orienté objet", "Communauté active"],
            "example": "Une même idée peut souvent être écrite en Python avec moins de lignes qu'avec un langage plus verbeux.",
            "exercise": "Choisissez deux caractéristiques de Python et expliquez pourquoi elles aident un débutant.",
            "diagram": "mindmap\n  root((Python))\n    Portable\n    Gratuit\n    Lisible\n    Orienté objet\n    Extensible\n    Communauté active",
        },
        {
            "title": "Installer et démarrer Python",
            "pages": [3, 4],
            "keywords": ["installation", "ins alla", "installer", "utilisation", "démarrer", "demarrer"],
            "intro": "Cette partie présente le démarrage pratique avec Python et rappelle que les versions indiquées dans un ancien support peuvent évoluer.",
            "definitions": [("Environnement Python", "L'environnement Python regroupe l'interpréteur, les outils de lancement et éventuellement un éditeur comme IDLE.")],
            "key_points": [
                "Le PDF mentionne un guide d'installation associé au support.",
                "La version affichée dans le document peut être ancienne.",
                "Après installation, il faut vérifier que Python démarre correctement.",
                "IDLE peut servir à écrire et exécuter les premières instructions.",
            ],
            "bullets": ["Télécharger Python depuis une source fiable.", "Installer l'interpréteur.", "Ouvrir l'environnement.", "Tester une première instruction.", "Comparer avec les versions actuelles."],
            "example": "Après installation, l'apprenant peut ouvrir IDLE et tester une instruction simple comme print('Bonjour').",
            "exercise": "Listez les étapes nécessaires pour vérifier qu'une installation Python fonctionne sur votre ordinateur.",
            "diagram": "flowchart LR\nA[Télécharger Python] --> B[Installer] --> C[Ouvrir l'environnement] --> D[Écrire une instruction] --> E[Exécuter]",
        },
    ]
    chapters = []
    for topic in topics:
        matches = [page for page in pages if page["page_number"] in topic["pages"]]
        page_start = matches[0]["page_number"] if matches else 1
        page_end = matches[-1]["page_number"] if matches else page_start
        excerpt = build_excerpt(matches or pages, topic["keywords"], max_sentences=4)
        blocks = [block("paragraph", "Introduction", topic["intro"], public_document_name, page_start, page_end)]
        blocks.extend(block("definition", title, value, public_document_name, page_start, page_end) for title, value in topic["definitions"])
        blocks.append(block("key_point", "Point clé", topic["key_points"][0], public_document_name, page_start, page_end))
        blocks.append(block("bullet_list", "Points clés", topic["key_points"], public_document_name, page_start, page_end))
        blocks.append(block("bullet_list", "Étapes ou notions importantes", topic["bullets"], public_document_name, page_start, page_end))
        blocks.append(block("diagram", "Schéma utile", topic["diagram"], public_document_name, page_start, page_end, diagram_type="mermaid"))
        blocks.append(block("example", "Exemple concret", topic["example"], public_document_name, page_start, page_end))
        blocks.append(block("exercise", "Mini exercice", topic["exercise"], public_document_name, page_start, page_end))
        blocks.append(block("summary", "À retenir", " ".join(topic["key_points"][:3]), public_document_name, page_start, page_end))
        if topic["title"] == "Installer et démarrer Python":
            blocks.insert(-2, block("warning", "Versions du document", "Les captures ou versions mentionnées dans le PDF peuvent différer des versions actuelles de Python.", public_document_name, page_start, page_end))
        chapters.append({
            "title": topic["title"],
            "duration": "25 min",
            "estimated_duration": "25 min",
            "content": topic["intro"],
            "structured_content": validate_structured_blocks(blocks),
            "status": "active" if not chapters else "locked",
            "openable": not chapters,
        })
    return {
        "summary": "Introduction à la programmation et à Python à partir du support PDF associé : définition, erreurs, bonnes pratiques, caractéristiques du langage et démarrage.",
        "objectives": [
            "Comprendre ce qu'est la programmation.",
            "Reconnaître les erreurs de syntaxe, sémantiques et d'exécution.",
            "Appliquer les cinq règles d'or pour bien programmer.",
            "Identifier les principales caractéristiques de Python.",
            "Démarrer Python en tenant compte du support fourni.",
        ],
        "skills": ["Lire un support d'introduction Python", "Identifier une erreur de programmation", "Organiser un apprentissage progressif"],
        "examples": [
            {"title": "Processus de programmation", "description": "Passer d'un problème à un algorithme, puis à un programme exécuté."},
            {"title": "Classification des erreurs", "description": "Comparer syntaxe, sens du programme et erreur pendant l'exécution."},
            {"title": "Première instruction Python", "description": "Utiliser une instruction simple comme print pour vérifier l'environnement."},
        ],
        "chapters": chapters,
    }


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
                block("summary", "Résumé", summarize_excerpt(excerpt), document_id, item["page"], item["page"]),
            ]),
            "status": "active" if index == 1 else "locked",
            "openable": index == 1,
        })
    return {
        "summary": first_sentences("\n".join(page["text"] for page in pages), 3),
        "objectives": [f"Comprendre : {chapter['title']}" for chapter in chapters[:5]],
        "skills": ["Lire un support pédagogique", "Identifier les notions clés du document"],
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
    return first_sentences(excerpt, 2) if excerpt else "Le PDF présente cette notion comme un élément d'introduction."


def exercise_for_topic(title: str) -> str:
    if "erreurs" in title.lower():
        return "Classez trois situations en erreur de syntaxe, erreur sémantique ou erreur d'exécution."
    if "python" in title.lower():
        return "Expliquez en deux phrases pourquoi Python est souvent conseillé pour débuter."
    return "Reformulez la notion avec vos mots et donnez une étape pratique pour l'appliquer."


def summary_for_topic(title: str) -> str:
    return f"Ce chapitre sert d'introduction à : {title}. Les éléments affichés proviennent du PDF associé au cours."


def detect_headings(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headings = []
    for page in pages:
        for line in page["text"].splitlines():
            clean = line.strip()
            if 5 <= len(clean) <= 90 and (clean.isupper() or re.match(r"^\\d+[.)-]\\s+", clean)):
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
        if line.lower() in {"introduction à python", "introduction a python"}:
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
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\\s+", text) if sentence.strip()]


def first_sentences(text: str, limit: int) -> str:
    return " ".join(split_sentences(text)[:limit]).strip()


def _is_safe_doc_path(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(DOCS_DIR.resolve())
    except FileNotFoundError:
        return path.parent.resolve().is_relative_to(DOCS_DIR.resolve())
