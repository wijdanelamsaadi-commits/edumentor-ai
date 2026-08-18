from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.models.persistence import (
    DiagnosticAnswer,
    DiagnosticQuestion,
    DiagnosticResult,
    DiagnosticSession,
    DifficultyLevel,
    Subject,
)

QUESTION_BANK_PATH = Path(__file__).resolve().parents[2] / "data" / "edumentor_questions.json"

DEMO_QUESTION_BANKS = {}

FRENCH_QUESTION_BANK = [
    ("debutant", "ComprÃ©hension", "Qui est le narrateur principal dans La BoÃ®te Ã  merveilles ", ["Sidi Mohammed", "CrÃ©on", "Victor Hugo", "Antigone"], "Sidi Mohammed", "La BoÃ®te Ã  merveilles est racontÃ©e Ã  la premiÃ¨re personne par Sidi Mohammed."),
    ("debutant", "ComprÃ©hension", "Quelle oeuvre est Ã©crite par Ahmed Sefrioui ", ["La BoÃ®te Ã  merveilles", "Antigone", "Le Dernier Jour d'un condamnÃ©", "Les MisÃ©rables"], "La BoÃ®te Ã  merveilles", "Ahmed Sefrioui est l'auteur de La BoÃ®te Ã  merveilles."),
    ("debutant", "Figures de style", "Dans une comparaison, on trouve souvent un outil comme...", ["comme", "mais", "donc", "car"], "comme", "La comparaison rapproche deux Ã©lÃ©ments avec un outil comparatif."),
    ("debutant", "Langue", "Un antonyme est un mot de sens...", ["contraire", "identique", "flou", "technique"], "contraire", "Un antonyme exprime le sens opposÃ© d'un autre mot."),
    ("debutant", "MÃ©thodologie", "Pour justifier une rÃ©ponse, il faut s'appuyer sur...", ["un indice du texte", "une idÃ©e inventÃ©e", "un autre cours", "une opinion sans preuve"], "un indice du texte", "La justification doit venir du passage Ã©tudiÃ©."),
    ("intermediaire", "ComprÃ©hension", "Dans Antigone, le conflit central oppose principalement...", ["Antigone et CrÃ©on", "Sidi Mohammed et Zineb", "Victor Hugo et le lecteur", "Lalla AÃ¯cha et Rahma"], "Antigone et CrÃ©on", "La piÃ¨ce met en scÃ¨ne l'opposition entre la loi de CrÃ©on et le choix d'Antigone."),
    ("intermediaire", "Production Ã©crite", "Un paragraphe argumentatif doit contenir surtout...", ["une idÃ©e, un argument et un exemple", "une liste sans ordre", "une seule citation", "un titre dÃ©coratif"], "une idÃ©e, un argument et un exemple", "La production Ã©crite exige une organisation claire et justifiÃ©e."),
    ("intermediaire", "Langue", "Le champ lexical regroupe des mots liÃ©s Ã ...", ["une mÃªme idÃ©e", "une mÃªme rime seulement", "un calcul", "une date"], "une mÃªme idÃ©e", "Le champ lexical rassemble des mots autour d'un thÃ¨me commun."),
    ("intermediaire", "Figures de style", "Attribuer une action humaine Ã  un objet correspond Ã ...", ["la personnification", "la synonymie", "la conjugaison", "la ponctuation"], "la personnification", "La personnification donne une caractÃ©ristique humaine Ã  un Ãªtre non humain ou Ã  une chose."),
    ("intermediaire", "MÃ©thodologie", "Avant de rÃ©pondre, il faut d'abord repÃ©rer...", ["les mots-clÃ©s de la consigne", "la couleur de la page", "le nombre de lignes uniquement", "le nom du navigateur"], "les mots-clÃ©s de la consigne", "Les mots-clÃ©s indiquent ce que la question demande exactement."),
    ("avance", "ComprÃ©hension", "Le Dernier Jour d'un condamnÃ© est principalement un roman qui...", ["dÃ©nonce la peine de mort", "raconte une aventure comique", "dÃ©crit une enfance marocaine", "prÃ©sente une lÃ©gende antique"], "dÃ©nonce la peine de mort", "Victor Hugo utilise la voix du condamnÃ© pour critiquer la peine capitale."),
    ("avance", "Production Ã©crite", "Dans une conclusion argumentative, il faut surtout...", ["rÃ©pondre clairement au sujet", "ajouter un nouvel argument long", "changer de thÃ¨me", "copier la consigne"], "rÃ©pondre clairement au sujet", "La conclusion ferme le raisonnement et rappelle la position dÃ©fendue."),
    ("avance", "Figures de style", "Une antithÃ¨se met en relation...", ["deux idÃ©es opposÃ©es", "deux mots synonymes", "deux dates", "deux consignes identiques"], "deux idÃ©es opposÃ©es", "L'antithÃ¨se rapproche des termes ou idÃ©es contraires pour crÃ©er un contraste."),
    ("avance", "Langue", "Au discours indirect, la parole rapportÃ©e devient gÃ©nÃ©ralement...", ["intÃ©grÃ©e dans une phrase principale", "un titre", "un calcul", "un nom propre uniquement"], "intÃ©grÃ©e dans une phrase principale", "Le discours indirect reformule la parole en l'insÃ©rant dans une phrase."),
    ("avance", "MÃ©thodologie", "Une rÃ©ponse complÃ¨te au rÃ©gional doit Ãªtre...", ["claire, prÃ©cise et justifiÃ©e", "longue mais hors sujet", "sans lien avec le texte", "uniquement personnelle"], "claire, prÃ©cise et justifiÃ©e", "La clartÃ©, la prÃ©cision et la justification permettent d'obtenir tous les points."),
    ("debutant", "ComprÃ©hension", "Qui est l'auteur d'Antigone Ã©tudiÃ©e au programme ", ["Jean Anouilh", "Ahmed Sefrioui", "Victor Hugo", "MoliÃ¨re"], "Jean Anouilh", "L'Antigone du programme est une piÃ¨ce de Jean Anouilh."),
    ("intermediaire", "ComprÃ©hension", "Dans La BoÃ®te Ã  merveilles, Lalla Zoubida est...", ["la mÃ¨re de Sidi Mohammed", "la soeur d'Antigone", "la fille de CrÃ©on", "une narratrice externe"], "la mÃ¨re de Sidi Mohammed", "Lalla Zoubida est la mÃ¨re du narrateur Sidi Mohammed."),
    ("avance", "MÃ©thodologie", "Pour analyser un extrait, l'ordre le plus efficace est...", ["situation, personnages, indices, interprÃ©tation", "rÃ©ponse, hasard, conclusion, lecture", "copie, opinion, hors sujet, fin", "calcul, rÃ©sultat, formule, unitÃ©"], "situation, personnages, indices, interprÃ©tation", "Cette dÃ©marche Ã©vite le hors sujet et construit une analyse progressive."),
    ("debutant", "Langue", "Un synonyme est un mot de sens...", ["proche", "contraire", "absent", "numÃ©rique"], "proche", "Un synonyme exprime une idÃ©e proche d'un autre mot."),
    ("intermediaire", "Production Ã©crite", "Un connecteur logique sert Ã ...", ["organiser les idÃ©es", "remplacer le texte", "supprimer l'argument", "donner une note"], "organiser les idÃ©es", "Les connecteurs rendent la progression du raisonnement plus claire."),
]


def apply_diagnostic_migration(engine: Engine) -> dict[str, int]:
    DiagnosticQuestion.__table__.create(engine, checkfirst=True)
    DiagnosticSession.__table__.create(engine, checkfirst=True)
    DiagnosticAnswer.__table__.create(engine, checkfirst=True)
    ensure_diagnostic_question_generation_columns(engine)
    ensure_diagnostic_session_context_columns(engine)
    ensure_import_job_current_columns(engine)
    ensure_diagnostic_result_columns(engine)

    with Session(engine) as db:
        seed_diagnostic_questions(db)
        attach_legacy_results_to_ai(db)
        backfill_imported_diagnostic_context(db)
        return {
            "diagnostic_questions": db.query(DiagnosticQuestion).count(),
            "diagnostic_sessions": db.query(DiagnosticSession).count(),
            "diagnostic_results": db.query(DiagnosticResult).count(),
        }


def ensure_diagnostic_question_generation_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("diagnostic_questions"):
        return

    columns = {column["name"] for column in inspector.get_columns("diagnostic_questions")}
    json_type = "JSONB" if engine.dialect.name == "postgresql" else "JSON"
    definitions = {
        "classroom_id": "INTEGER",
        "import_job_id": "INTEGER",
        "academic_year": "VARCHAR(80)",
        "source_course_id": "INTEGER",
        "source_chapter_id": "INTEGER",
        "source_block_id": "VARCHAR(160)",
        "generation_method": "VARCHAR(80)",
        "source_hash": "VARCHAR(64)",
        "question_hash": "VARCHAR(64)",
        "imported_package_hash": "VARCHAR(64)",
        "source_snapshot": json_type,
    }

    with engine.begin() as connection:
        for column, definition in definitions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE diagnostic_questions ADD COLUMN {column} {definition}"))
        for column in definitions:
            if column == "source_snapshot":
                continue
            create_index_if_missing(connection, f"ix_diagnostic_questions_{column}", "diagnostic_questions", column)


def ensure_diagnostic_session_context_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("diagnostic_sessions"):
        return

    columns = {column["name"] for column in inspector.get_columns("diagnostic_sessions")}
    definitions = {
        "import_job_id": "INTEGER",
        "imported_package_hash": "VARCHAR(64)",
        "status": "VARCHAR(40) DEFAULT 'started'",
    }
    with engine.begin() as connection:
        for column, definition in definitions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE diagnostic_sessions ADD COLUMN {column} {definition}"))
        for column in definitions:
            create_index_if_missing(connection, f"ix_diagnostic_sessions_{column}", "diagnostic_sessions", column)


def ensure_import_job_current_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("pedagogical_package_import_jobs"):
        return

    columns = {column["name"] for column in inspector.get_columns("pedagogical_package_import_jobs")}
    definitions = {
        "subject_id": "INTEGER",
        "education_level_id": "INTEGER",
        "academic_year": "VARCHAR(80)",
        "is_current": "BOOLEAN DEFAULT FALSE",
    }
    with engine.begin() as connection:
        for column, definition in definitions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE pedagogical_package_import_jobs ADD COLUMN {column} {definition}"))
        for column in definitions:
            create_index_if_missing(connection, f"ix_pedagogical_package_import_jobs_{column}", "pedagogical_package_import_jobs", column)


def ensure_diagnostic_result_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("diagnostic_results"):
        return

    columns = {column["name"] for column in inspector.get_columns("diagnostic_results")}
    json_type = "JSONB" if engine.dialect.name == "postgresql" else "JSON"
    definitions = {
        "subject_id": "INTEGER",
        "education_level_id": "INTEGER",
        "detected_difficulty_level_id": "INTEGER",
        "results_by_topic": json_type,
        "results_by_difficulty": json_type,
        "recommendations": json_type,
        "justification": "TEXT",
    }

    with engine.begin() as connection:
        for column, definition in definitions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE diagnostic_results ADD COLUMN {column} {definition}"))
        create_index_if_missing(connection, "ix_diagnostic_results_subject_id", "diagnostic_results", "subject_id")
        create_index_if_missing(connection, "ix_diagnostic_results_education_level_id", "diagnostic_results", "education_level_id")
        create_index_if_missing(connection, "ix_diagnostic_results_detected_difficulty_level_id", "diagnostic_results", "detected_difficulty_level_id")


def create_index_if_missing(connection, index_name: str, table_name: str, column_name: str) -> None:
    dialect = connection.engine.dialect.name
    if dialect == "postgresql":
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"))
    elif dialect == "sqlite":
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"))


def seed_diagnostic_questions(db: Session) -> None:
    subject_by_slug = {subject.slug: subject for subject in db.scalars(select(Subject))}
    difficulty_by_slug = {difficulty.slug: difficulty for difficulty in db.scalars(select(DifficultyLevel))}
    if "francais" in subject_by_slug:
        seed_french_questions(db, subject_by_slug["francais"], difficulty_by_slug)
    db.commit()


def seed_french_questions(db: Session, subject: Subject, difficulty_by_slug: dict[str, DifficultyLevel]) -> None:
    if db.query(DiagnosticQuestion).filter_by(subject_id=subject.id).count() > 0:
        return
    for difficulty_slug, topic, question, choices, correct_answer, explanation in FRENCH_QUESTION_BANK:
        difficulty = difficulty_by_slug.get(difficulty_slug)
        if difficulty is None:
            continue
        db.add(DiagnosticQuestion(
            subject_id=subject.id,
            difficulty_level_id=difficulty.id,
            topic=topic,
            question=question,
            choices=choices,
            correct_answer=correct_answer,
            explanation=explanation,
            active=True,
        ))


def seed_ai_questions(db: Session, subject: Subject, difficulty_by_slug: dict[str, DifficultyLevel]) -> None:
    if db.query(DiagnosticQuestion).filter_by(subject_id=subject.id).count() > 0:
        return
    if not QUESTION_BANK_PATH.exists():
        return
    with QUESTION_BANK_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    questions = data.get("questions", [])
    for index, item in enumerate(questions):
        choices = item.get("options") or []
        correct_index = int(item.get("correct_index", 0) or 0)
        correct_answer = choices[correct_index] if 0 <= correct_index < len(choices) else ""
        difficulty = get_seed_difficulty(index, difficulty_by_slug)
        if difficulty is None:
            continue
        db.add(DiagnosticQuestion(
            subject_id=subject.id,
            difficulty_level_id=difficulty.id,
            topic=item.get("theme"),
            question=item.get("question") or "",
            choices=choices,
            correct_answer=correct_answer,
            explanation=item.get("explanation") or "",
            active=True,
        ))


def get_seed_difficulty(index: int, difficulty_by_slug: dict[str, DifficultyLevel]) -> DifficultyLevel | None:
    if index < 20:
        return difficulty_by_slug.get("debutant")
    if index < 45:
        return difficulty_by_slug.get("intermediaire")
    return difficulty_by_slug.get("avance")


def attach_legacy_results_to_ai(db: Session) -> None:
    subject = db.scalars(select(Subject).where(Subject.slug == "francais")).first()
    if subject is None:
        return
    db.query(DiagnosticResult).filter(DiagnosticResult.subject_id.is_(None)).update(
        {DiagnosticResult.subject_id: subject.id},
        synchronize_session=False,
    )
    db.commit()


def backfill_imported_diagnostic_context(db: Session) -> None:
    from app.models.persistence import Course, PedagogicalPackageImportJob

    jobs = list(db.scalars(
        select(PedagogicalPackageImportJob)
        .where(PedagogicalPackageImportJob.status == "completed", PedagogicalPackageImportJob.course_id.is_not(None))
        .order_by(PedagogicalPackageImportJob.completed_at.asc(), PedagogicalPackageImportJob.id.asc())
    ))
    latest_by_context: dict[tuple[int, int | None, int | None, str | None], PedagogicalPackageImportJob] = {}
    for job in jobs:
        course = db.get(Course, job.course_id)
        if course is None:
            continue
        source_summary = job.source_summary or {}
        target = source_summary.get("target") if isinstance(source_summary, dict) else {}
        academic_year = job.academic_year or (target or {}).get("academic_year")
        if job.subject_id is None:
            job.subject_id = course.subject_id
        if job.education_level_id is None:
            job.education_level_id = course.education_level_id
        if job.academic_year is None:
            job.academic_year = academic_year
        db.query(DiagnosticQuestion).filter(
            DiagnosticQuestion.source_course_id == job.course_id,
            DiagnosticQuestion.imported_package_hash == job.json_sha256,
        ).update({
            DiagnosticQuestion.import_job_id: job.id,
            DiagnosticQuestion.classroom_id: job.classroom_id,
            DiagnosticQuestion.academic_year: academic_year,
        }, synchronize_session=False)
        if job.subject_id is not None:
            latest_by_context[(job.classroom_id, job.subject_id, job.education_level_id, academic_year)] = job

    current_ids = {job.id for job in latest_by_context.values()}
    for job in jobs:
        job.is_current = job.id in current_ids
        if not job.is_current:
            db.query(DiagnosticQuestion).filter(DiagnosticQuestion.import_job_id == job.id).update(
                {DiagnosticQuestion.active: False},
                synchronize_session=False,
            )
    db.commit()
