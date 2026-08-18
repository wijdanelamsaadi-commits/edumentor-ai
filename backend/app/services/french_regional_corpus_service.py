from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.persistence import Course, RagDocument, Subject
from app.rag.vector_store import COLLECTION_NAME, EMBEDDING_MODEL_NAME, delete_document_vectors, index_chunks
from app.services import rag_document_service

DATASET_DIR = Path(__file__).resolve().parents[2] / "data" / "regional_exams_v1"
CORPUS_DIR = Path(__file__).resolve().parents[2] / "docs" / "french_regional"
REPORT_PATH = CORPUS_DIR / "CORPUS_REPORT.md"
CORPUS_PREFIX = "Corpus francais 1ere Bac"


@dataclass(frozen=True)
class CorpusChunk:
    chunk_key: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CorpusDocument:
    relative_path: Path
    title: str
    text: str
    metadata: dict[str, Any]
    chunks: list[CorpusChunk]


FIGURE_DEFINITIONS = {
    "comparaison": "Une comparaison rapproche deux elements avec un outil comme comme, tel, pareil a ou semblable a.",
    "metaphore": "Une metaphore rapproche deux elements sans outil de comparaison pour creer une image forte.",
    "personnification": "Une personnification attribue une action, un sentiment ou une attitude humaine a un objet, un animal ou une idee.",
    "antithese": "Une antithese oppose deux idees ou deux mots de sens contraire dans une meme phrase.",
    "gradation": "Une gradation enchaine des mots ou des idees selon une intensite croissante ou decroissante.",
    "hyperbole": "Une hyperbole exagere une realite pour produire une impression forte.",
    "enumeration": "Une enumeration accumule plusieurs mots ou groupes de mots appartenant a une meme idee.",
    "repetition": "Une repetition reprend un mot ou une expression pour insister sur une idee.",
    "anaphore": "Une anaphore repete un mot ou un groupe de mots au debut de plusieurs phrases ou propositions.",
    "metonymie": "Une metonymie remplace un mot par un autre qui entretient avec lui un lien logique.",
}


def sync_french_regional_corpus(
    db: Session,
    *,
    dry_run: bool = False,
    reset_french_only: bool = False,
    index: bool = True,
) -> dict[str, Any]:
    dataset = load_regional_dataset()
    subject = resolve_french_subject(db)
    course = resolve_french_regional_course(db, subject)
    documents = build_corpus_documents(db, dataset, course, subject)
    chunks_preview = [chunk for document in documents for chunk in document.chunks]

    summary: dict[str, Any] = {
        "status": "dry_run" if dry_run else "completed",
        "subject_id": subject.id if subject else None,
        "course_id": course.id if course else None,
        "documents": len(documents),
        "chunks": len(chunks_preview),
        "document_types": dict(Counter(str(doc.metadata.get("document_type", "unknown")) for doc in documents)),
        "works": dict(Counter(str(chunk.metadata.get("work", "")) for chunk in chunks_preview if chunk.metadata.get("work"))),
        "competences": dict(Counter(str(chunk.metadata.get("competence", "")) for chunk in chunks_preview if chunk.metadata.get("competence"))),
        "indexed_chunks": 0,
        "updated_documents": 0,
        "created_documents": 0,
        "reset_vectors": 0,
        "corpus_dir": str(CORPUS_DIR),
    }

    if dry_run:
        return summary

    if subject is None or course is None:
        raise RuntimeError("Impossible de trouver dynamiquement la matiere Francais et son cours regional publie.")

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    if reset_french_only:
        summary["reset_vectors"] = reset_french_vectors(db, subject.id)

    for document in documents:
        path = (CORPUS_DIR / document.relative_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        chunks_path = path.with_suffix(path.suffix + ".chunks.json")
        chunks_payload = [
            {"chunk_key": chunk.chunk_key, "text": chunk.text, "metadata": chunk.metadata}
            for chunk in document.chunks
        ]
        path.write_text(document.text, encoding="utf-8")
        chunks_path.write_text(json.dumps(chunks_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        checksum = checksum_payload(document.relative_path.as_posix(), document.text, chunks_payload)
        rag_document, created = upsert_rag_document(db, course, subject, document, path, checksum, chunks_count=len(chunks_payload))
        if created:
            summary["created_documents"] += 1
        else:
            summary["updated_documents"] += 1

        if index:
            delete_document_vectors(rag_document.id)
            chunks = rag_document_service.build_document_chunks(db, rag_document)
            summary["indexed_chunks"] += index_chunks(chunks)
            rag_document.chunk_count = len(chunks)
            rag_document.index_status = "ready"
            rag_document.index_error = None
            rag_document.indexed_at = datetime.utcnow()
            rag_document.updated_at = datetime.utcnow()

    write_corpus_report(dataset, documents, summary)
    db.commit()
    return summary


def load_regional_dataset() -> dict[str, Any]:
    path = DATASET_DIR / "regional_exams_v1.json"
    if not path.exists():
        raise FileNotFoundError(f"Dataset regional introuvable: {path}")
    return repair_mojibake(json.loads(path.read_text(encoding="utf-8")))


def resolve_french_subject(db: Session) -> Subject | None:
    return db.scalars(
        select(Subject)
        .where(
            Subject.active.is_(True),
            or_(
                Subject.slug == "francais",
                Subject.name.ilike("%fran%"),
                Subject.slug.ilike("%fran%"),
            ),
        )
        .order_by(Subject.display_order, Subject.id)
    ).first()


def resolve_french_regional_course(db: Session, subject: Subject | None) -> Course | None:
    query = (
        select(Course)
        .options(selectinload(Course.subject), selectinload(Course.chapters))
        .where(Course.published.is_(True), Course.status == "published")
    )
    if subject is not None:
        query = query.where(Course.subject_id == subject.id)
    courses = list(db.scalars(query.order_by(Course.display_order.desc(), Course.id.desc())))
    if not courses:
        return None
    regional = [
        course for course in courses
        if "regional" in normalize_text(" ".join([course.title, course.summary or "", course.description or ""]))
    ]
    return regional[0] if regional else courses[0]


def build_corpus_documents(db: Session, dataset: dict[str, Any], course: Course | None, subject: Subject | None) -> list[CorpusDocument]:
    exams = list(dataset.get("exams") or [])
    documents: list[CorpusDocument] = []
    documents.extend(build_exam_documents(exams, course, subject))
    documents.extend(build_work_documents(exams, course, subject))
    documents.extend(build_figure_documents(exams, course, subject))
    documents.append(build_language_document(exams, course, subject))
    documents.append(build_methodology_document(exams, course, subject))
    documents.append(build_writing_document(exams, course, subject))
    course_document = build_course_chapter_document(course, subject)
    if course_document is not None:
        documents.append(course_document)
    return documents


def build_exam_documents(exams: list[dict[str, Any]], course: Course | None, subject: Subject | None) -> list[CorpusDocument]:
    documents: list[CorpusDocument] = []
    for exam in exams:
        title = str(exam.get("title") or exam.get("exam_id"))
        work = str(exam.get("work_title") or "")
        chunks: list[CorpusChunk] = []
        base_metadata = base_metadata_for(course, subject, "regional_exam_text", title)
        base_metadata.update({
            "work": work,
            "author": exam.get("work_author", ""),
            "exam_id": exam.get("exam_id", ""),
            "year": exam.get("year", ""),
            "region": exam.get("region", ""),
            "session": exam.get("session", ""),
            "verified": "official_verified",
            "display_source": title,
        })
        support_text = clean_text(exam.get("support_text", ""))
        chunks.append(CorpusChunk(
            "support-text",
            "\n".join([
                f"Document: {title}",
                f"Oeuvre: {work}",
                f"Auteur: {exam.get('work_author', '')}",
                "Type: texte support officiel ou fourni dans le dataset.",
                "",
                support_text,
            ]),
            dict(base_metadata),
        ))
        for question in exam.get("questions", []):
            q_metadata = dict(base_metadata)
            q_metadata.update({
                "document_type": "regional_exam_question",
                "question_id": question.get("question_id", ""),
                "competence": question.get("competence", ""),
                "question_type": question.get("question_type", ""),
                "points": question.get("points", ""),
                "verified": "teacher_validation_required" if question.get("requires_teacher_validation") else "official_or_verified",
                "display_source": f"{title} - question {question.get('official_number', question.get('order_index', ''))}",
            })
            chunks.append(CorpusChunk(
                f"question-{question.get('question_id') or question.get('order_index')}",
                format_question_chunk(exam, question),
                q_metadata,
            ))
        text = "\n\n".join([f"# {title}", format_exam_intro(exam), *[chunk.text for chunk in chunks]])
        documents.append(CorpusDocument(
            Path("regional_exams") / f"{slugify(exam.get('exam_id') or title)}.md",
            title,
            text,
            base_metadata,
            chunks,
        ))
    return documents


def build_work_documents(exams: list[dict[str, Any]], course: Course | None, subject: Subject | None) -> list[CorpusDocument]:
    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for exam in exams:
        by_work[str(exam.get("work_title") or "Oeuvre inconnue")].append(exam)

    documents: list[CorpusDocument] = []
    for work, work_exams in by_work.items():
        author = str(work_exams[0].get("work_author") or "")
        genre = str(work_exams[0].get("work_genre") or "")
        title = f"{work} - fiche de revision"
        metadata = base_metadata_for(course, subject, "work_sheet", title)
        metadata.update({"work": work, "author": author, "verified": "source_synthesis", "display_source": title})
        chunks = [
            CorpusChunk(
                "overview",
                "\n".join([
                    f"Oeuvre: {work}",
                    f"Auteur: {author}",
                    f"Genre: {genre}",
                    "Source: informations bibliographiques et questions presentes dans les examens regionaux du dataset.",
                    "",
                    "Passages disponibles dans les examens:",
                    *[f"- {exam.get('title')}: {shorten(clean_text(exam.get('support_text', '')), 700)}" for exam in work_exams],
                ]),
                metadata | {"document_type": "work_sheet"},
            ),
            CorpusChunk(
                "revision-points",
                "\n".join([
                    f"Fiche de revision: {work}",
                    "Elements explicitement travailles par les examens:",
                    *revision_points_for_work(work_exams),
                    "",
                    "Attention: cette fiche ne remplace pas l'oeuvre complete et ne donne pas de numero de page.",
                ]),
                metadata | {"document_type": "work_summary"},
            ),
        ]
        text = "\n\n".join([f"# {title}", *[chunk.text for chunk in chunks]])
        documents.append(CorpusDocument(Path("works") / slugify(work) / "fiche_revision.md", title, text, metadata, chunks))
    return documents


def build_figure_documents(exams: list[dict[str, Any]], course: Course | None, subject: Subject | None) -> list[CorpusDocument]:
    documents: list[CorpusDocument] = []
    figure_examples = collect_figure_examples(exams)
    for figure, definition in FIGURE_DEFINITIONS.items():
        title = f"Figures de style - {figure}"
        metadata = base_metadata_for(course, subject, "figure_of_style", title)
        metadata.update({"competence": "Figures de style", "verified": "pedagogical_created", "display_source": title})
        examples = figure_examples.get(figure) or ["Exemple pedagogique cree: relever l'image, nommer la figure, puis expliquer son effet."]
        chunks = [
            CorpusChunk(
                figure,
                "\n".join([
                    f"Figure de style: {figure}",
                    f"Definition: {definition}",
                    "Indices: observer les mots qui rapprochent, opposent, exagerent ou donnent une action humaine.",
                    "Effet recherche: expliquer ce que la figure ajoute au sens et a l'impression produite.",
                    "Exemples disponibles:",
                    *[f"- {item}" for item in examples[:6]],
                    "Fiabilite: les definitions sont pedagogiques; les exemples issus d'examens sont signales comme tels.",
                ]),
                metadata,
            )
        ]
        text = f"# {title}\n\n" + chunks[0].text
        documents.append(CorpusDocument(Path("figures_of_style") / f"{slugify(figure)}.md", title, text, metadata, chunks))
    return documents


def build_language_document(exams: list[dict[str, Any]], course: Course | None, subject: Subject | None) -> CorpusDocument:
    title = "Langue - notions des examens regionaux"
    metadata = base_metadata_for(course, subject, "language_lesson", title)
    metadata.update({"competence": "Langue", "verified": "source_synthesis", "display_source": title})
    language_questions = questions_by_competence(exams, "Langue")
    chunks = [CorpusChunk("language-questions", format_competence_chunk("Langue", language_questions), metadata)]
    return CorpusDocument(Path("language") / "notions_examens_regionaux.md", title, "# " + title + "\n\n" + chunks[0].text, metadata, chunks)


def build_methodology_document(exams: list[dict[str, Any]], course: Course | None, subject: Subject | None) -> CorpusDocument:
    title = "Methodologie - reussir les questions du regional"
    metadata = base_metadata_for(course, subject, "methodology", title)
    metadata.update({"competence": "Methodologie", "verified": "pedagogical_created_from_exam_patterns", "display_source": title})
    questions = questions_by_competence(exams, "Methodologie")
    text = "\n".join([
        "Methodologie pour le regional de francais 1ere Bac.",
        "Competences observees dans les examens: situer un passage, identifier l'oeuvre, l'auteur, le genre, justifier vrai/faux, relever une phrase et comprendre la consigne.",
        "",
        "Conseils:",
        "- Lire la consigne et reperer le verbe d'action.",
        "- Repondre courtement quand la question est factuelle.",
        "- Justifier avec un indice du texte quand la consigne le demande.",
        "- Respecter le bareme et eviter de transformer une question simple en paragraphe long.",
        "",
        format_competence_chunk("Methodologie", questions),
    ])
    chunks = [CorpusChunk("methodology-core", text, metadata)]
    return CorpusDocument(Path("methodology") / "reussir_questions_regional.md", title, "# " + title + "\n\n" + text, metadata, chunks)


def build_writing_document(exams: list[dict[str, Any]], course: Course | None, subject: Subject | None) -> CorpusDocument:
    title = "Production ecrite - methode et criteres"
    metadata = base_metadata_for(course, subject, "writing_guide", title)
    metadata.update({"competence": "Production ecrite", "verified": "source_synthesis", "display_source": title})
    questions = questions_by_competence(exams, "Production ecrite")
    text = "\n".join([
        "Guide pour traiter la production ecrite du regional.",
        "Les sujets du dataset demandent une reponse personnelle coherente: il faut exprimer une opinion, organiser les arguments et respecter la consigne.",
        "",
        "Methode:",
        "- Comprendre le theme et la position demandee.",
        "- Annoncer clairement l'opinion dans l'introduction.",
        "- Developper deux arguments avec exemples.",
        "- Utiliser des connecteurs logiques.",
        "- Conclure sans ajouter une idee nouvelle.",
        "",
        "Sources et criteres observes:",
        format_competence_chunk("Production ecrite", questions),
    ])
    chunks = [
        CorpusChunk("writing-method", text, metadata),
        CorpusChunk("writing-rubric", "Bareme: conserver les criteres presents dans les examens; les productions personnelles necessitent une validation enseignante.", metadata | {"document_type": "scoring_rubric"}),
    ]
    return CorpusDocument(Path("writing") / "production_ecrite_methode.md", title, "# " + title + "\n\n" + "\n\n".join(chunk.text for chunk in chunks), metadata, chunks)


def build_course_chapter_document(course: Course | None, subject: Subject | None) -> CorpusDocument | None:
    if course is None:
        return None
    chunks: list[CorpusChunk] = []
    title = f"{course.title} - chapitres du cours"
    metadata = base_metadata_for(course, subject, "work_summary", title)
    metadata.update({"verified": "imported_source", "display_source": title})
    for chapter in sorted(course.chapters, key=lambda item: (item.position or 0, item.id or 0)):
        parts = [f"Chapitre: {chapter.title}", clean_text(chapter.content or "")]
        structured = chapter.structured_content
        if isinstance(structured, dict):
            parts.append(json.dumps(structured, ensure_ascii=False))
        elif isinstance(structured, list):
            parts.extend(json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item) for item in structured[:20])
        text = "\n".join(part for part in parts if part.strip())
        if len(text.strip()) < 40:
            continue
        chunks.append(CorpusChunk(
            f"chapter-{chapter.id}",
            text,
            metadata | {
                "chapter_title": chapter.title,
                "chapter_id": chapter.id,
                "document_type": "work_summary",
                "display_source": f"{course.title} - {chapter.title}",
            },
        ))
    if not chunks:
        return None
    return CorpusDocument(Path("works") / "cours_importe" / "chapitres.md", title, "# " + title + "\n\n" + "\n\n".join(chunk.text for chunk in chunks), metadata, chunks)


def format_exam_intro(exam: dict[str, Any]) -> str:
    return "\n".join([
        f"Annee: {exam.get('year')}",
        f"Region: {exam.get('region')}",
        f"Session: {exam.get('session')}",
        f"Oeuvre: {exam.get('work_title')}",
        f"Auteur: {exam.get('work_author')}",
    ])


def format_question_chunk(exam: dict[str, Any], question: dict[str, Any]) -> str:
    answer_label = "Correction officielle ou verifiee"
    if question.get("requires_teacher_validation") or question.get("question_type") in {"production_ecrite", "response_long"}:
        answer_label = "Elements attendus ou exemple de reponse; validation enseignante recommandee"
    parts = [
        f"Examen: {exam.get('title')}",
        f"Oeuvre: {exam.get('work_title')}",
        f"Question {question.get('official_number')}: {question.get('prompt')}",
        f"Competence: {question.get('competence')}",
        f"Type: {question.get('question_type')}",
        f"Bareme: {question.get('points')} point(s)",
    ]
    choices = question.get("choices") or []
    if choices:
        parts.append("Choix: " + " | ".join(str(choice) for choice in choices))
    expected = question.get("expected_elements") or []
    if expected:
        parts.append("Elements attendus: " + "; ".join(str(item) for item in expected))
    if question.get("correct_answer"):
        parts.append(f"{answer_label}: {question.get('correct_answer')}")
    if question.get("explanation"):
        parts.append(f"Explication: {question.get('explanation')}")
    return "\n".join(parts)


def revision_points_for_work(exams: list[dict[str, Any]]) -> list[str]:
    points: list[str] = []
    for exam in exams:
        points.append(f"{exam.get('region')} {exam.get('year')}: passage support travaille en examen.")
        for question in exam.get("questions", [])[:6]:
            competence = question.get("competence")
            prompt = shorten(question.get("prompt", ""), 180)
            points.append(f"{competence}: {prompt}")
    return unique_lines(points)[:30]


def collect_figure_examples(exams: list[dict[str, Any]]) -> dict[str, list[str]]:
    examples: dict[str, list[str]] = defaultdict(list)
    for exam in exams:
        support = clean_text(exam.get("support_text", ""))
        if "djellaba" in normalize_text(support) and "dormait" in normalize_text(support):
            examples["personnification"].append(f"{exam.get('title')}: la djellaba blanche qui dormait au fond du coffre.")
        for question in exam.get("questions", []):
            searchable = normalize_text(" ".join([question.get("prompt", ""), question.get("correct_answer", ""), question.get("explanation", ""), " ".join(question.get("tags") or [])]))
            for figure in FIGURE_DEFINITIONS:
                if figure in searchable:
                    examples[figure].append(f"{exam.get('title')}: {shorten(question.get('prompt', ''), 220)}")
    return {key: unique_lines(value) for key, value in examples.items()}


def questions_by_competence(exams: list[dict[str, Any]], competence: str) -> list[dict[str, Any]]:
    normalized_target = normalize_text(competence)
    rows: list[dict[str, Any]] = []
    for exam in exams:
        for question in exam.get("questions", []):
            if normalize_text(question.get("competence", "")) == normalized_target:
                rows.append({"exam": exam, "question": question})
    return rows


def format_competence_chunk(competence: str, rows: list[dict[str, Any]]) -> str:
    lines = [f"Competence: {competence}", "Questions observees dans les examens:"]
    for row in rows[:40]:
        exam = row["exam"]
        question = row["question"]
        answer = question.get("correct_answer") or "; ".join(question.get("expected_elements") or [])
        if question.get("requires_teacher_validation"):
            answer = f"Elements attendus / validation enseignante: {answer}"
        lines.append(f"- {exam.get('region')} {exam.get('year')} ({exam.get('work_title')}), question {question.get('official_number')}: {question.get('prompt')} Reponse: {answer}")
    return "\n".join(lines)


def base_metadata_for(course: Course | None, subject: Subject | None, document_type: str, title: str) -> dict[str, Any]:
    return {
        "language": "fr",
        "level": "1ere_bac_maroc",
        "subject": "francais",
        "program": "regional",
        "document_type": document_type,
        "work": "",
        "author": "",
        "exam_id": "",
        "year": "",
        "region": "",
        "session": "",
        "question_id": "",
        "competence": "",
        "question_type": "",
        "points": "",
        "chapter_title": "",
        "source_file": title,
        "verified": "",
        "course_id": course.id if course else -1,
        "subject_id": subject.id if subject else -1,
        "display_source": title,
        "source_label": title,
    }


def repair_mojibake(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: repair_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_mojibake(item) for item in value]
    if not isinstance(value, str):
        return value
    if not any(marker in value for marker in ("Ã", "â", "Â")):
        return value
    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value


def upsert_rag_document(
    db: Session,
    course: Course,
    subject: Subject,
    corpus_document: CorpusDocument,
    path: Path,
    checksum: str,
    *,
    chunks_count: int,
) -> tuple[RagDocument, bool]:
    stored_filename = corpus_document.relative_path.as_posix()
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
    document.original_filename = f"{CORPUS_PREFIX} - {corpus_document.title}"
    document.stored_filename = stored_filename
    document.file_path = str(path)
    document.file_size = path.stat().st_size
    document.mime_type = "text/markdown"
    document.checksum_sha256 = checksum
    document.page_count = 1
    document.chunk_count = chunks_count
    document.embedding_model = EMBEDDING_MODEL_NAME
    document.collection_name = COLLECTION_NAME
    document.index_status = "pending"
    document.index_error = None
    document.active = True
    document.updated_at = datetime.utcnow()
    db.flush()
    return document, created


def reset_french_vectors(db: Session, subject_id: int) -> int:
    deleted = 0
    documents = db.scalars(
        select(RagDocument).where(
            RagDocument.subject_id == subject_id,
            RagDocument.mime_type == "text/markdown",
            RagDocument.original_filename.ilike(f"{CORPUS_PREFIX}%"),
        )
    ).all()
    for document in documents:
        deleted += delete_document_vectors(document.id)
        document.index_status = "pending"
        document.chunk_count = 0
        document.indexed_at = None
    db.flush()
    return deleted


def write_corpus_report(dataset: dict[str, Any], documents: list[CorpusDocument], summary: dict[str, Any]) -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    chunks = [chunk for document in documents for chunk in document.chunks]
    exams = dataset.get("exams") or []
    lines = [
        "# Rapport du corpus RAG francais 1ere Bac",
        "",
        f"Generation: {datetime.utcnow().isoformat()}Z",
        f"Version dataset: {dataset.get('version', 'inconnue')}",
        f"Documents: {len(documents)}",
        f"Chunks: {len(chunks)}",
        f"Chunks indexes: {summary.get('indexed_chunks', 0)}",
        "",
        "## Repartition par oeuvre",
        *[f"- {name}: {count}" for name, count in sorted(Counter(chunk.metadata.get("work") for chunk in chunks if chunk.metadata.get("work")).items())],
        "",
        "## Repartition par competence",
        *[f"- {name}: {count}" for name, count in sorted(Counter(chunk.metadata.get("competence") for chunk in chunks if chunk.metadata.get("competence")).items())],
        "",
        "## Repartition par type de document",
        *[f"- {name}: {count}" for name, count in sorted(Counter(chunk.metadata.get("document_type") for chunk in chunks).items())],
        "",
        "## Examens inclus",
        *[f"- {exam.get('title')} - {exam.get('work_title')} - {len(exam.get('questions') or [])} questions" for exam in exams],
        "",
        "## Fiabilite",
        "- Les textes supports et questions proviennent du dataset regional_exams_v1.",
        "- Les corrections marquees comme ouvertes ou production ecrite restent des elements attendus et demandent une validation enseignante.",
        "- Les fiches methodologiques et definitions de figures sont du contenu pedagogique cree a partir des besoins du programme.",
        "",
        "## Limites",
        "- Aucun numero de page n'est invente pour les documents Markdown.",
        "- Le corpus ne remplace pas les oeuvres completes.",
        "- Le corpus actif est limite aux ressources de francais 1ere Bac et aux examens regionaux.",
        "",
        "## Requetes de test",
        "- Qui est l'auteur de La Boite a merveilles ?",
        "- Comment situer le passage de l'Achoura ?",
        "- Quelle figure de style trouve-t-on dans \"la djellaba dormait\" ?",
        "- Donne-moi une question regionale sur Antigone.",
        "- Comment repondre a une question Vrai ou Faux ?",
        "- Quels sont les criteres d'une production ecrite ?",
        "- Corrige : Sidi Mohamed est un narrateur externe.",
        "- Donne-moi un exercice sur ma competence la plus faible.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def checksum_payload(relative_path: str, text: str, chunks_payload: list[dict[str, Any]]) -> str:
    payload = json.dumps({"path": relative_path, "text": text, "chunks": chunks_payload}, ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def normalize_text(value: Any) -> str:
    text = str(value or "")
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(normalized.split())


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def shorten(value: Any, max_length: int) -> str:
    text = clean_text(value)
    if len(text) <= max_length:
        return text
    cut = text[:max_length].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:")


def slugify(value: Any) -> str:
    normalized = normalize_text(value)
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return slug or "document"


def unique_lines(items: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for item in items:
        clean = clean_text(item)
        key = normalize_text(clean)
        if clean and key not in seen:
            seen.add(key)
            rows.append(clean)
    return rows
