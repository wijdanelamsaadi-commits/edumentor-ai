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

DEMO_QUESTION_BANKS = {
    "informatique": [
        ("debutant", "Programmation", "A quoi sert une variable en programmation ?", ["A stocker une valeur", "A eteindre l'ordinateur", "A dessiner une image", "A supprimer un fichier"], "A stocker une valeur", "Une variable garde une information que le programme peut reutiliser."),
        ("debutant", "Python", "Quelle instruction affiche un message en Python ?", ["echo()", "print()", "show()", "write()"], "print()", "print() affiche une valeur dans la console Python."),
        ("debutant", "Algorithmes", "Qu'est-ce qu'un algorithme ?", ["Une suite d'etapes pour resoudre un probleme", "Un type d'ecran", "Un fichier PDF", "Une erreur"], "Une suite d'etapes pour resoudre un probleme", "Un algorithme decrit clairement les actions a executer."),
        ("intermediaire", "Erreurs", "Quelle erreur arrive quand Python ne comprend pas la structure du code ?", ["Erreur de syntaxe", "Erreur reseau", "Erreur physique", "Erreur de clavier"], "Erreur de syntaxe", "Une erreur de syntaxe vient d'une instruction mal ecrite."),
        ("intermediaire", "Conditions", "Quel mot-cle permet de tester une condition en Python ?", ["if", "for", "class", "import"], "if", "if execute un bloc seulement si une condition est vraie."),
        ("intermediaire", "Boucles", "A quoi sert une boucle for ?", ["Repeter des instructions", "Créer un PDF", "Changer la langue", "Fermer le systeme"], "Repeter des instructions", "Une boucle for parcourt une sequence et repete un traitement."),
        ("avance", "Complexite", "Que mesure la complexite algorithmique ?", ["Le cout en temps ou memoire", "La couleur du code", "Le poids du clavier", "Le nombre de fichiers PDF"], "Le cout en temps ou memoire", "La complexite estime les ressources necessaires quand la taille des donnees augmente."),
        ("avance", "Structures", "Quelle structure associe une cle a une valeur en Python ?", ["dictionnaire", "tuple seulement", "chaine", "commentaire"], "dictionnaire", "Un dictionnaire permet de retrouver une valeur a partir d'une cle."),
    ],
    "mathematiques": [
        ("debutant", "Calcul", "Combien vaut 7 x 8 ?", ["54", "56", "64", "78"], "56", "7 multiplie par 8 donne 56."),
        ("debutant", "Equations", "Quelle est la solution de x + 3 = 8 ?", ["3", "5", "8", "11"], "5", "On retire 3 des deux cotes : x = 5."),
        ("debutant", "Logique", "Si une affirmation est vraie, sa negation est...", ["vraie", "fausse", "identique", "impossible"], "fausse", "La negation inverse la valeur logique."),
        ("intermediaire", "Fonctions", "Dans f(x)=2x+1, combien vaut f(3) ?", ["6", "7", "8", "9"], "7", "On remplace x par 3 : 2 x 3 + 1 = 7."),
        ("intermediaire", "Statistiques", "La moyenne de 10, 12 et 14 est...", ["10", "12", "14", "36"], "12", "La moyenne vaut (10+12+14)/3 = 12."),
        ("intermediaire", "Pourcentages", "20% de 50 vaut...", ["5", "10", "20", "25"], "10", "20% correspond a 0,2 ; 0,2 x 50 = 10."),
        ("avance", "Fonctions", "La derivee de x^2 est...", ["x", "2x", "x^3", "2"], "2x", "La derivee de x^n vaut n x^(n-1)."),
        ("avance", "Probabilites", "Une probabilite doit toujours etre comprise entre...", ["-1 et 1", "0 et 1", "1 et 10", "0 et 1000"], "0 et 1", "Une probabilite normalisee varie de 0 a 1."),
    ],
    "physique": [
        ("debutant", "Unites", "Quelle est l'unite de la vitesse dans le systeme international ?", ["m/s", "kg", "N", "J"], "m/s", "La vitesse exprime une distance parcourue par unite de temps."),
        ("debutant", "Vitesse", "Si une voiture parcourt 100 km en 2 h, sa vitesse moyenne est...", ["25 km/h", "50 km/h", "100 km/h", "200 km/h"], "50 km/h", "Vitesse = distance / temps = 100 / 2."),
        ("debutant", "Energie", "Quelle grandeur mesure la capacite a produire un travail ?", ["energie", "masse", "temperature", "longueur"], "energie", "L'energie est la grandeur associee a la capacite d'effectuer un travail."),
        ("intermediaire", "Force", "Selon Newton, une force peut modifier...", ["le mouvement d'un objet", "le nom d'un fichier", "une adresse email", "une couleur"], "le mouvement d'un objet", "Une force peut accelerer, ralentir ou deformer un objet."),
        ("intermediaire", "Electricite", "Quelle relation relie tension, resistance et intensite ?", ["U = R x I", "P = m x g", "v = d + t", "E = h / t"], "U = R x I", "La loi d'Ohm relie U, R et I."),
        ("intermediaire", "Puissance", "La puissance electrique peut s'ecrire...", ["P = U x I", "P = U + I", "P = R / t", "P = m x v"], "P = U x I", "La puissance consommee depend de la tension et de l'intensite."),
        ("avance", "Energie cinetique", "L'energie cinetique depend directement de...", ["la masse et le carre de la vitesse", "la couleur", "le volume seul", "la temperature seule"], "la masse et le carre de la vitesse", "Ec = 1/2 m v^2."),
        ("avance", "Champ electrique", "Un champ electrique agit principalement sur...", ["les charges electriques", "les sons", "la lumiere uniquement", "les textes"], "les charges electriques", "Une charge placee dans un champ electrique subit une force."),
    ],
}


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
    if "intelligence-artificielle" in subject_by_slug:
        seed_ai_questions(db, subject_by_slug["intelligence-artificielle"], difficulty_by_slug)

    for subject_slug, questions in DEMO_QUESTION_BANKS.items():
        subject = subject_by_slug.get(subject_slug)
        if subject is None:
            continue
        if db.query(DiagnosticQuestion).filter_by(subject_id=subject.id).count() > 0:
            continue
        for difficulty_slug, topic, question, choices, correct_answer, explanation in questions:
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
    db.commit()


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
    subject = db.scalars(select(Subject).where(Subject.slug == "intelligence-artificielle")).first()
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
