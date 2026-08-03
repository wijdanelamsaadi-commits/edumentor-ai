from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable

from pypdf import PdfReader
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.persistence import Course, RagDocument, Subject
from app.rag.vector_store import COLLECTION_NAME, EMBEDDING_MODEL_NAME, delete_document_vectors, index_chunks
from app.services import rag_document_service
from app.services.french_regional_corpus_service import resolve_french_regional_course, resolve_french_subject

SIGMA_PREFIX = "Sigma Français 1er Bac"
SIGMA_SOURCE_TYPE = "third_party_pedagogical_guide"
SIGMA_SOURCE_TIER = "supplementary"
SIGMA_SOURCE_PRIORITY = 20

BACKEND_DIR = Path(__file__).resolve().parents[2]
FRENCH_DOCS_DIR = BACKEND_DIR / "docs" / "french_regional"
SIGMA_SOURCE_PDF = FRENCH_DOCS_DIR / "sources" / "sigma_francais_1er_bac.pdf"
SIGMA_OUTPUT_DIR = FRENCH_DOCS_DIR / "sigma"
SIGMA_REPORT_PATH = FRENCH_DOCS_DIR / "SIGMA_PDF_REPORT.md"


@dataclass(frozen=True)
class SigmaSection:
    key: str
    title: str
    page_start: int
    page_end: int
    document_type: str
    competence: str = ""
    work: str = ""
    author: str = ""
    year: int | None = None


@dataclass(frozen=True)
class SigmaChunk:
    chunk_key: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SigmaDocument:
    relative_path: Path
    title: str
    text: str
    metadata: dict[str, Any]
    chunks: list[SigmaChunk]
    page_count: int


LESSON_SECTIONS = (
    SigmaSection("champs_lexicaux", "Les champs lexicaux", 6, 6, "language_lesson", "Langue"),
    SigmaSection("registres_litteraires", "Les registres littéraires", 7, 7, "literary_register_lesson", "Compréhension"),
    SigmaSection("phrase_complexe", "La phrase complexe", 8, 8, "grammar_lesson", "Langue"),
    SigmaSection("enonciation", "L'énonciation : discours et récit", 9, 10, "enunciation_lesson", "Langue"),
    SigmaSection("figures_de_style", "Les figures de style", 11, 11, "figure_of_style_lesson", "Figures de style"),
    SigmaSection("registres_de_langue", "Les registres de langue", 12, 12, "language_register_lesson", "Langue"),
    SigmaSection("discours_rapporte", "Le discours direct et indirect", 13, 14, "reported_speech_lesson", "Langue"),
)

WORK_SECTIONS = (
    SigmaSection(
        "la_boite_a_merveilles",
        "La Boîte à merveilles — fiche de lecture",
        16,
        20,
        "work_sheet",
        "Compréhension",
        "La Boîte à merveilles",
        "Ahmed Sefrioui",
    ),
    SigmaSection(
        "antigone",
        "Antigone — fiche de lecture",
        21,
        24,
        "work_sheet",
        "Compréhension",
        "Antigone",
        "Jean Anouilh",
    ),
    SigmaSection(
        "le_dernier_jour_d_un_condamne",
        "Le Dernier Jour d'un condamné — fiche de lecture",
        25,
        29,
        "work_sheet",
        "Compréhension",
        "Le Dernier Jour d'un condamné",
        "Victor Hugo",
    ),
)

EXAM_SECTIONS = (
    SigmaSection("examens_2016", "Examens régionaux 2016 — recueil Sigma", 31, 60, "regional_exam_question", "Méthodologie", year=2016),
    SigmaSection("examens_2015", "Examens régionaux 2015 — recueil Sigma", 62, 78, "regional_exam_question", "Méthodologie", year=2015),
    SigmaSection("examens_2014", "Examens régionaux 2014 — recueil Sigma", 80, 99, "regional_exam_question", "Méthodologie", year=2014),
    SigmaSection("examens_2013", "Examens régionaux 2013 — recueil Sigma", 101, 116, "regional_exam_question", "Méthodologie", year=2013),
    SigmaSection("examens_2012", "Examens régionaux 2012 — recueil Sigma", 118, 133, "regional_exam_question", "Méthodologie", year=2012),
    SigmaSection("examens_2011", "Examens régionaux 2011 — recueil Sigma", 135, 160, "regional_exam_question", "Méthodologie", year=2011),
)

ALL_SECTIONS = LESSON_SECTIONS + WORK_SECTIONS + EXAM_SECTIONS
IGNORED_PAGES = tuple(sorted(set(range(1, 6)) | {15, 30, 61, 79, 100, 117, 134}))

REGION_NAMES = (
    "Casablanca-Settat",
    "Marrakech-Safi",
    "Fès-Meknès",
    "Rabat-Salé-Kénitra",
    "Tanger-Tétouan-Al Hoceïma",
    "Béni Mellal-Khénifra",
    "Souss-Massa",
    "Oriental",
    "Drâa-Tafilalet",
    "Guelmim-Oued Noun",
    "Laâyoune-Sakia El Hamra",
    "Dakhla-Oued Ed-Dahab",
    "Grand Casablanca",
    "Doukkala-Abda",
    "Gharb-Chrarda-Béni Hssen",
    "Meknès-Tafilalet",
    "Tadla-Azilal",
    "Chaouia-Ouardigha",
)

MOJIBAKE_REPLACEMENTS = {
    "¿gure": "figure",
    "¿gures": "figures",
    "dé¿ni": "défini",
    "signi¿cation": "signification",
    "In¿nitif": "Infinitif",
    "in¿nitif": "infinitif",
    "réÀéchir": "réfléchir",
    "a¿n": "afin",
    "¿ls": "fils",
    "¿ancée": "fiancée",
    "efferts": "efforts",
    "Dour": "Jour",
    "Condamne ": "Condamné ",
}


def sync_sigma_french_pdf(
    db: Session,
    *,
    pdf_path: Path | str | None = None,
    dry_run: bool = False,
    reset_sigma_only: bool = False,
    index: bool = True,
    write_report: bool = True,
) -> dict[str, Any]:
    source_pdf = Path(pdf_path or SIGMA_SOURCE_PDF).expanduser().resolve()
    if not source_pdf.exists():
        raise FileNotFoundError(f"PDF Sigma introuvable: {source_pdf}")

    subject = resolve_french_subject(db)
    course = resolve_french_regional_course(db, subject)
    documents, extraction = build_sigma_documents(source_pdf, course, subject)
    chunks = [chunk for document in documents for chunk in document.chunks]

    summary: dict[str, Any] = {
        "status": "dry_run" if dry_run else "completed",
        "source_pdf": str(source_pdf),
        "pdf_pages": extraction["pdf_pages"],
        "pages_indexed": extraction["pages_indexed"],
        "pages_ignored": extraction["pages_ignored"],
        "documents": len(documents),
        "chunks": len(chunks),
        "subject_id": subject.id if subject else None,
        "course_id": course.id if course else None,
        "document_types": dict(Counter(str(chunk.metadata.get("document_type", "unknown")) for chunk in chunks)),
        "works": dict(Counter(str(chunk.metadata.get("work", "")) for chunk in chunks if chunk.metadata.get("work"))),
        "years": dict(Counter(str(chunk.metadata.get("year", "")) for chunk in chunks if chunk.metadata.get("year"))),
        "created_documents": 0,
        "updated_documents": 0,
        "indexed_chunks": 0,
        "reset_documents": 0,
        "reset_vectors": 0,
        "output_dir": str(SIGMA_OUTPUT_DIR),
        "report_path": str(SIGMA_REPORT_PATH),
    }

    if dry_run:
        return summary
    if subject is None or course is None:
        raise RuntimeError("Impossible de résoudre dynamiquement la matière Français et le cours régional.")

    SIGMA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if reset_sigma_only:
        reset_summary = reset_sigma_documents(db, course.id)
        summary.update(reset_summary)

    for document in documents:
        path = (FRENCH_DOCS_DIR / document.relative_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path = path.with_suffix(path.suffix + ".chunks.json")
        chunks_payload = [
            {"chunk_key": chunk.chunk_key, "text": chunk.text, "metadata": chunk.metadata}
            for chunk in document.chunks
        ]
        path.write_text(document.text, encoding="utf-8")
        sidecar_path.write_text(json.dumps(chunks_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        checksum = checksum_payload(document.relative_path.as_posix(), document.text, chunks_payload)
        rag_document, created = upsert_sigma_document(
            db,
            course,
            subject,
            document,
            path,
            checksum,
        )
        if created:
            summary["created_documents"] += 1
        else:
            summary["updated_documents"] += 1

        if index:
            delete_document_vectors(rag_document.id)
            built_chunks = rag_document_service.build_document_chunks(db, rag_document)
            summary["indexed_chunks"] += index_chunks(built_chunks)
            rag_document.chunk_count = len(built_chunks)
            rag_document.index_status = "ready"
            rag_document.index_error = None
            rag_document.indexed_at = datetime.utcnow()
            rag_document.updated_at = datetime.utcnow()

    if write_report:
        write_sigma_report(documents, extraction, summary)
    db.commit()
    return summary


def build_sigma_documents(
    pdf_path: Path,
    course: Course | None,
    subject: Subject | None,
) -> tuple[list[SigmaDocument], dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    page_texts = [(page.extract_text() or "") for page in reader.pages]
    documents: list[SigmaDocument] = []
    pages_indexed: set[int] = set()

    for section in ALL_SECTIONS:
        documents.append(build_section_document(section, page_texts, pdf_path.name, course, subject))
        pages_indexed.update(range(section.page_start, section.page_end + 1))

    extraction = {
        "pdf_pages": len(page_texts),
        "pages_indexed": len(pages_indexed),
        "pages_ignored": [page for page in range(1, len(page_texts) + 1) if page not in pages_indexed],
    }
    return documents, extraction


def build_section_document(
    section: SigmaSection,
    page_texts: list[str],
    source_file: str,
    course: Course | None,
    subject: Subject | None,
) -> SigmaDocument:
    chunks: list[SigmaChunk] = []
    markdown_pages: list[str] = []

    for page_number in range(section.page_start, section.page_end + 1):
        raw_text = page_texts[page_number - 1] if page_number <= len(page_texts) else ""
        clean = clean_sigma_page(raw_text, page_number)
        if len(normalize_text(clean)) < 35:
            continue

        page_work = section.work or infer_work(clean)
        page_author = section.author or author_for_work(page_work)
        page_region = infer_region(clean)
        page_session = infer_session(clean)
        page_document_type = infer_work_document_type(clean, section, page_number)
        if page_document_type == section.document_type:
            page_document_type = infer_exam_document_type(clean, section.document_type)
        page_competence = infer_competence(clean, section.competence)
        chapter_title = detect_page_title(clean, section.title)

        markdown_pages.append(f"## Page {page_number} — {chapter_title}\n\n{clean}")
        pieces = split_semantic_text(clean)
        for piece_index, piece in enumerate(pieces, start=1):
            metadata = base_sigma_metadata(
                course,
                subject,
                source_file,
                section,
                page_number,
                chapter_title,
            )
            metadata.update(
                {
                    "document_type": page_document_type,
                    "work": page_work,
                    "author": page_author,
                    "region": page_region,
                    "session": page_session,
                    "competence": page_competence,
                    "display_source": display_source_for(section, page_number, chapter_title),
                    "source_label": display_source_for(section, page_number, chapter_title),
                }
            )
            chunks.append(
                SigmaChunk(
                    chunk_key=f"p{page_number}-c{piece_index}",
                    text=f"Source pédagogique complémentaire: {section.title}. Page {page_number}.\n{piece}",
                    metadata=metadata,
                )
            )

    text = "\n\n".join(
        [
            f"# {section.title}",
            "",
            "> Source pédagogique complémentaire. Les corrections du recueil ne sont pas présentées comme des corrections officielles.",
            "",
            *markdown_pages,
        ]
    )
    metadata = base_sigma_metadata(course, subject, source_file, section, section.page_start, section.title)
    relative_path = Path("sigma") / category_for(section) / f"{section.key}.md"
    return SigmaDocument(
        relative_path=relative_path,
        title=section.title,
        text=text,
        metadata=metadata,
        chunks=chunks,
        page_count=max(0, section.page_end - section.page_start + 1),
    )


def base_sigma_metadata(
    course: Course | None,
    subject: Subject | None,
    source_file: str,
    section: SigmaSection,
    page_number: int,
    chapter_title: str,
) -> dict[str, Any]:
    return {
        "language": "fr",
        "level": "1ere_bac_maroc",
        "subject": "francais",
        "program": "regional",
        "source_name": SIGMA_PREFIX,
        "source_type": SIGMA_SOURCE_TYPE,
        "source_tier": SIGMA_SOURCE_TIER,
        "source_priority": SIGMA_SOURCE_PRIORITY,
        "copyright_restricted": True,
        "document_type": section.document_type,
        "section_id": section.key,
        "work": section.work,
        "author": section.author,
        "exam_id": f"sigma_{section.year}_{page_number}" if section.year else "",
        "year": section.year or "",
        "region": "",
        "session": "",
        "question_id": "",
        "competence": section.competence,
        "question_type": "",
        "points": "",
        "chapter_title": chapter_title,
        "source_file": source_file,
        "verified": "supplementary_unverified",
        "official_status": "not_officially_verified",
        "course_id": course.id if course else -1,
        "subject_id": subject.id if subject else -1,
        "page_number": page_number,
        "page_start": page_number,
        "page_end": page_number,
        "display_source": display_source_for(section, page_number, chapter_title),
        "source_label": display_source_for(section, page_number, chapter_title),
    }


def upsert_sigma_document(
    db: Session,
    course: Course,
    subject: Subject,
    sigma_document: SigmaDocument,
    path: Path,
    checksum: str,
) -> tuple[RagDocument, bool]:
    stored_filename = sigma_document.relative_path.as_posix()
    document = db.scalars(
        select(RagDocument).where(
            RagDocument.course_id == course.id,
            RagDocument.stored_filename == stored_filename,
        )
    ).first()
    created = document is None
    if document is None:
        document = RagDocument(course_id=course.id, checksum_sha256=checksum)
        db.add(document)
    elif document.checksum_sha256 != checksum:
        delete_document_vectors(document.id)

    document.subject_id = subject.id
    document.professor_id = course.professor_id
    document.original_filename = f"{SIGMA_PREFIX} - {sigma_document.title}"
    document.stored_filename = stored_filename
    document.file_path = str(path)
    document.file_size = path.stat().st_size
    document.mime_type = "text/markdown"
    document.checksum_sha256 = checksum
    document.page_count = sigma_document.page_count
    document.chunk_count = len(sigma_document.chunks)
    document.embedding_model = EMBEDDING_MODEL_NAME
    document.collection_name = COLLECTION_NAME
    document.index_status = "pending"
    document.index_error = None
    document.active = True
    document.updated_at = datetime.utcnow()
    db.flush()
    return document, created


def reset_sigma_documents(db: Session, course_id: int) -> dict[str, int]:
    documents = db.scalars(
        select(RagDocument).where(
            RagDocument.course_id == course_id,
            or_(
                RagDocument.original_filename.ilike(f"{SIGMA_PREFIX}%"),
                RagDocument.stored_filename.ilike("sigma/%"),
            ),
        )
    ).all()
    deleted_vectors = 0
    for document in documents:
        deleted_vectors += delete_document_vectors(document.id)
        document.active = False
        document.index_status = "outdated"
        document.chunk_count = 0
        document.indexed_at = None
        document.updated_at = datetime.utcnow()
    db.flush()
    return {"reset_documents": len(documents), "reset_vectors": deleted_vectors}


def write_sigma_report(
    documents: list[SigmaDocument],
    extraction: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    chunks = [chunk for document in documents for chunk in document.chunks]
    ignored = extraction.get("pages_ignored") or []
    lines = [
        "# Rapport d'indexation — Sigma Français 1er Bac",
        "",
        f"Génération: {datetime.utcnow().isoformat()}Z",
        f"Pages du PDF: {extraction.get('pdf_pages', 0)}",
        f"Pages exploitées: {extraction.get('pages_indexed', 0)}",
        f"Pages ignorées: {len(ignored)} ({format_page_ranges(ignored)})",
        f"Documents structurés: {len(documents)}",
        f"Chunks: {len(chunks)}",
        f"Chunks indexés: {summary.get('indexed_chunks', 0)}",
        "",
        "## Sections",
        *[f"- {document.title}: {document.page_count} page(s), {len(document.chunks)} chunk(s)" for document in documents],
        "",
        "## Répartition par type de document",
        *[f"- {name}: {count}" for name, count in sorted(Counter(chunk.metadata.get('document_type', 'unknown') for chunk in chunks).items())],
        "",
        "## Répartition par œuvre",
        *[f"- {name}: {count}" for name, count in sorted(Counter(chunk.metadata.get('work') for chunk in chunks if chunk.metadata.get('work')).items())],
        "",
        "## Répartition par année d'examen",
        *[f"- {name}: {count}" for name, count in sorted(Counter(str(chunk.metadata.get('year')) for chunk in chunks if chunk.metadata.get('year')).items())],
        "",
        "## Statut de la source",
        "- Source tierce pédagogique complémentaire.",
        "- Les corrigés du recueil ne sont pas présentés comme des corrigés officiels.",
        "- Les sources officielles ou déjà vérifiées conservent une priorité supérieure dans le reranking.",
        "- Le PDF complet n'est pas exposé publiquement par ce script.",
        "- Les réponses doivent être synthétiques; les longues reproductions verbatim sont à éviter.",
        "",
        "## Limites",
        "- L'extraction PDF peut contenir des coquilles typographiques présentes dans l'ouvrage ou dans la couche texte.",
        "- Les anciens examens sont indexés par page et par année; leur région n'est renseignée que lorsqu'elle est détectée clairement.",
        "- Une divergence avec une source officielle doit être tranchée en faveur de la source officielle.",
    ]
    SIGMA_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def clean_sigma_page(raw_text: str, page_number: int) -> str:
    text = unicodedata.normalize("NFKC", str(raw_text or ""))
    for source, target in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(source, target)

    cleaned_lines: list[str] = []
    seen_adjacent = ""
    for raw_line in text.replace("\r", "\n").splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue
        line = re.sub(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+", " ", line)
        line = " ".join(line.split()).strip()
        if not line:
            continue
        normalized = normalize_text(line)
        if should_drop_line(line, normalized, page_number):
            continue
        line = collapse_repeated_phrase(line)
        normalized_after = normalize_text(line)
        if normalized_after == seen_adjacent:
            continue
        seen_adjacent = normalized_after
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([.!?])(?=[A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜ])", r"\1 ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def should_drop_line(line: str, normalized: str, page_number: int) -> bool:
    if not normalized:
        return True
    if "for more visit" in normalized or "l9ray.com" in normalized:
        return True
    if normalized in {"francais", "toutes series", str(page_number), f"{page_number} {page_number}"}:
        return True
    if re.fullmatch(r"(?:francais\s*){2,}", normalized):
        return True
    if len(normalized) <= 3 and normalized.isdigit():
        return True
    if "collection sigma" in normalized and len(normalized) < 80:
        return True
    return False


def collapse_repeated_phrase(line: str) -> str:
    # Common extraction pattern: "Cours 1 : Cours 1 : ..."
    match = re.match(r"^(.{3,80}?)\s+\1(?:\s+|$)(.*)$", line, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)} {match.group(2)}".strip()
    words = line.split()
    half = len(words) // 2
    if len(words) >= 4 and len(words) % 2 == 0 and words[:half] == words[half:]:
        return " ".join(words[:half])
    return line


def split_semantic_text(text: str, max_chars: int = 1800, overlap_chars: int = 140) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= max_chars:
        return [normalized]

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", normalized) if paragraph.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", normalized) if sentence.strip()]

    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars or not current:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        pieces.append(current)
        overlap = current[-overlap_chars:].strip() if overlap_chars else ""
        current = f"{overlap}\n\n{paragraph}".strip()
    if current:
        pieces.append(current)
    return [piece for piece in pieces if len(normalize_text(piece)) >= 25]


def detect_page_title(text: str, fallback: str) -> str:
    for line in text.splitlines()[:10]:
        candidate = line.strip(" -:•\t")
        if 4 <= len(candidate) <= 140 and not candidate[0].isdigit():
            normalized = normalize_text(candidate)
            if any(token in normalized for token in ("cours", "corrige", "texte", "production ecrite", "generalites", "schema narratif", "themes", "etude de texte")):
                return candidate
    return fallback


def infer_work_document_type(text: str, section: SigmaSection, page_number: int) -> str:
    if section not in WORK_SECTIONS:
        return section.document_type
    normalized = normalize_text(text)
    if (
        "personnages principaux" in normalized
        or "personnages secondaires" in normalized
        or (
            section.key == "la_boite_a_merveilles"
            and page_number in {16, 17}
            and any(name in normalized for name in ("mohammed", "lalla zoubida", "si abdeslem", "kenza", "rahma"))
        )
    ):
        return "work_characters"
    if any(token in normalized for token in ("structure de l oeuvre", "chapitres thematique", "schema narratif")):
        return "work_structure"
    if "resume" in normalized:
        return "work_summary"
    return section.document_type


def infer_exam_document_type(text: str, fallback: str) -> str:
    normalized = normalize_text(text)
    if "corrige" in normalized and "production ecrite" in normalized:
        return "writing_correction"
    if "corrige" in normalized:
        return "regional_exam_correction"
    if "production ecrite" in normalized:
        return "writing_topic"
    if "texte" in normalized and not re.search(r"\b[1-9][-) .]", normalized):
        return "regional_exam_text"
    return fallback


def infer_competence(text: str, fallback: str) -> str:
    normalized = normalize_text(text)
    if "production ecrite" in normalized:
        return "Production écrite"
    if any(token in normalized for token in ("figure de style", "metaphore", "personnification", "comparaison", "antithese")):
        return "Figures de style"
    if any(token in normalized for token in ("discours direct", "discours indirect", "phrase complexe", "grammaire", "conjug")):
        return "Langue"
    if any(token in normalized for token in ("situez", "justifiez", "methode", "consigne", "bareme")):
        return "Méthodologie"
    return fallback or "Compréhension"


def infer_work(text: str) -> str:
    normalized = normalize_text(text)
    scores = {
        "La Boîte à merveilles": sum(token in normalized for token in ("la boite a merveilles", "sidi mohammed", "lalla zoubida", "ahmed sefrioui")),
        "Antigone": sum(token in normalized for token in ("antigone", "creon", "ismene", "jean anouilh", "hemon")),
        "Le Dernier Jour d'un condamné": sum(token in normalized for token in ("dernier jour d un condamne", "victor hugo", "condamne", "bicetre", "guillotine")),
    }
    work, score = max(scores.items(), key=lambda item: item[1])
    return work if score > 0 else ""


def author_for_work(work: str) -> str:
    return {
        "La Boîte à merveilles": "Ahmed Sefrioui",
        "Antigone": "Jean Anouilh",
        "Le Dernier Jour d'un condamné": "Victor Hugo",
    }.get(work, "")


def infer_region(text: str) -> str:
    normalized = normalize_text(text)
    for region in REGION_NAMES:
        if normalize_text(region) in normalized:
            return region
    return ""


def infer_session(text: str) -> str:
    normalized = normalize_text(text)
    if "rattrapage" in normalized:
        return "Rattrapage"
    if "session normale" in normalized or "session juin" in normalized or "juin" in normalized:
        return "Normale"
    return ""


def display_source_for(section: SigmaSection, page_number: int, chapter_title: str) -> str:
    short_title = chapter_title if chapter_title and chapter_title != section.title else section.title
    return f"{SIGMA_PREFIX} — {short_title}, p. {page_number}"


def category_for(section: SigmaSection) -> str:
    if section in LESSON_SECTIONS:
        return "lessons"
    if section in WORK_SECTIONS:
        return "works"
    return "regional_exams"


def checksum_payload(relative_path: str, text: str, chunks_payload: list[dict[str, Any]]) -> str:
    payload = json.dumps({"path": relative_path, "text": text, "chunks": chunks_payload}, ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if unicodedata.category(character) != "Mn")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(text.split())


def format_page_ranges(pages: Iterable[int]) -> str:
    values = sorted(set(int(page) for page in pages))
    if not values:
        return "aucune"
    ranges: list[str] = []
    start = previous = values[0]
    for page in values[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)
