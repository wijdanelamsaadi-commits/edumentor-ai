from fastapi import HTTPException
import logging
import re
import unicodedata
from uuid import uuid4
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.persistence import Course, Subject, UserProfile
from app.rag.engine import rag_status
from app.rag.vector_store import semantic_search
from app.services import rag_document_service, student_weakness_model_service
from app.services.groq_service import generate_general_answer
from app.services.mock_data import COURSES, LEARNER, QUIZZES, RECOMMENDATIONS

logger = logging.getLogger(__name__)


def login_demo_user() -> dict:
    return {"access_token": "demo-token", "token_type": "bearer", "learner": LEARNER}


def get_dashboard() -> dict:
    average_progress = round(sum(course["progress"] for course in COURSES) / len(COURSES))
    return {
        "learner": LEARNER,
        "average_progress": average_progress,
        "active_courses": len(COURSES),
        "last_score": 76,
        "recommendations": RECOMMENDATIONS,
    }


def get_courses() -> list[dict]:
    return COURSES


def get_course_detail(course_id: int) -> dict:
    course = _find_course(course_id)
    information = course.get("information", {})
    return {
        **course,
        "information": {
            "level": information.get("level", course["level"]),
            "duration": information.get("duration", course["duration"]),
            "language": information.get("language", "Francais"),
            "last_update": information.get("last_update", "12/05/2024"),
            "chapter_count": information.get("chapter_count", len(course.get("chapters", []))),
        },
    }


def evaluate_diagnostic(answers: list[str]) -> dict:
    advanced_terms = {"avance", "projet", "complexe", "autonome"}
    beginner_terms = {"definition", "bases", "simple", "debut"}
    joined = " ".join(answers).lower()

    if any(term in joined for term in advanced_terms):
        level = "Avance"
    elif any(term in joined for term in beginner_terms):
        level = "Debutant"
    else:
        level = "Intermediaire"

    return {
        "level": level,
        "recommendations": _recommendations_for_level(level),
    }


def get_quiz(course_id: int) -> dict:
    if course_id not in QUIZZES:
        raise HTTPException(status_code=404, detail="Quiz introuvable")
    quiz = QUIZZES[course_id]
    course = _find_course(course_id)
    return {
        "course_id": quiz["course_id"],
        "course_title": course["title"],
        "questions": [
            {"question": item["question"], "choices": item["choices"]} for item in quiz["questions"]
        ],
    }


def grade_quiz(course_id: int, answers: list[str]) -> dict:
    if course_id not in QUIZZES:
        raise HTTPException(status_code=404, detail="Quiz introuvable")

    questions = QUIZZES[course_id]["questions"]
    corrections = []
    correct = 0

    for index, question in enumerate(questions):
        user_answer = answers[index] if index < len(answers) else ""
        is_correct = user_answer == question["answer"]
        if is_correct:
            correct += 1
        corrections.append(
            {
                "question": question["question"],
                "user_answer": user_answer,
                "correct_answer": question["answer"],
                "is_correct": is_correct,
                "explanation": question.get("explanation", ""),
            }
        )

    score = round((correct / len(questions)) * 100)
    return {
        "score": score,
        "correct_answers": correct,
        "total_questions": len(questions),
        "corrections": corrections,
        "recommendation": "Continuer le module suivant" if score >= 70 else "Revoir le resume et refaire les exercices",
    }


def _legacy_rag_chat(message: str, level: str) -> dict:
    results = semantic_search(message, limit=3)

    if not results:
        return {
            "answer": (
                "Je n'ai pas trouvé cette information dans les documents PDF disponibles. "
                "Essayez de reformuler la question ou de cibler un cours précis."
            ),
            "sources": [],
            "mode": "rag_semantic",
        }

    return {
        "answer": _build_pedagogical_rag_answer(message, level, results),
        "sources": [
            {
                "file_name": result["file_name"],
                "course_name": result["course_name"],
                "page_number": result["page_number"],
            }
            for result in results
        ],
        "mode": "rag_semantic",
    }


def _build_pedagogical_rag_answer(message: str, level: str, results: list[dict]) -> str:
    normalized_level = _normalize_level(level)
    topic = _detect_topic(message, results)
    profile = _topic_profile(topic)
    source_lines = _format_source_lines(results)
    definition = _definition_for_level(topic, profile, normalized_level)
    explanation = _explanation_for_level(topic, profile, normalized_level)
    example = _example_for_level(topic, profile, normalized_level)
    summary = _summary_for_level(profile, normalized_level)
    exercise = _exercise_for_level(topic, normalized_level)

    return "\n\n".join(
        [
            f"# Définition simple\n\n{definition}",
            f"# Explication détaillée\n\n{explanation}",
            f"# Exemple concret\n\n{example}",
            "# Résumé\n\n" + "\n".join(f"- {item}" for item in summary),
            f"# Mini exercice\n\n{exercise}",
            "# Sources utilisées\n\n" + "\n".join(source_lines),
        ]
    )


def get_profile() -> dict:
    return {
        "learner": LEARNER,
        "progression": {
            "global": 41,
            "courses_completed": 1,
            "courses_in_progress": 2,
            "average_score": 76,
        },
        "recommendations": RECOMMENDATIONS,
    }


def get_rag_status() -> dict:
    return rag_status()


def _find_course(course_id: int) -> dict:
    for course in COURSES:
        if course["id"] == course_id:
            return course
    raise HTTPException(status_code=404, detail="Cours introuvable")


def _recommendations_for_level(level: str) -> list[str]:
    if level == "Debutant":
        return ["Commencer par Introduction IA", "Faire les exercices guides avant le quiz"]
    if level == "Avance":
        return ["Explorer le module RAG", "Construire un mini-projet avec sources"]
    return ["Approfondir Machine Learning", "Reviser les points faibles avec le chatbot"]


def _detect_topic(message: str, results: list[dict]) -> str:
    normalized_message = _normalize_text(message)
    searchable = " ".join(
        [
            normalized_message,
            *(_normalize_text(result.get("course_name", "")) for result in results),
            *(_normalize_text(result.get("file_name", "")) for result in results),
        ]
    )

    if "prompt" in searchable:
        return "prompt_engineering"
    if "rag" in searchable or "recuperation" in searchable:
        return "rag"
    if "deep learning" in searchable or "apprentissage profond" in searchable:
        return "deep_learning"
    if "machine learning" in searchable and ("ia" in searchable or "intelligence artificielle" in searchable):
        return "ia_vs_ml"
    if "machine learning" in searchable:
        return "machine_learning"
    if "ia" in searchable or "intelligence artificielle" in searchable:
        return "ia"

    return "general"


def _topic_profile(topic: str) -> dict:
    profiles = {
        "rag": {
            "label": "RAG",
            "definition": "Le RAG est une méthode qui aide un chatbot à répondre en s'appuyant sur des documents au lieu de répondre uniquement avec sa mémoire interne.",
            "detail": "Le système transforme les documents en passages courts, cherche les passages les plus proches de la question, puis construit une réponse à partir de ces éléments. Cela rend la réponse plus contextualisée et permet d'afficher les sources utilisées.",
            "example": "Si un étudiant demande ce qu'est le RAG, le chatbot recherche les passages du cours RAG, reformule l'idée principale, puis indique le PDF et la page qui ont servi à répondre.",
            "advanced": "Techniquement, le RAG combine récupération d'information, embeddings, base vectorielle et génération de réponse. Ses limites principales sont la qualité des documents, le découpage des chunks et la pertinence du classement des passages.",
            "summary": [
                "Le RAG relie une question à des documents pédagogiques.",
                "Les PDF sont découpés en chunks pour faciliter la recherche.",
                "La recherche sémantique retrouve les passages proches du sens de la question.",
                "Les sources rendent la réponse plus vérifiable.",
            ],
        },
        "deep_learning": {
            "label": "Deep Learning",
            "definition": "Le Deep Learning est une famille de méthodes de Machine Learning qui utilise des réseaux de neurones avec plusieurs couches.",
            "detail": "Ces couches apprennent progressivement des représentations : les premières détectent des informations simples, puis les couches suivantes construisent des représentations plus abstraites. Cette approche est très utilisée pour les images, le texte, le son et les modèles de langage.",
            "example": "Pour reconnaître une image, un modèle de Deep Learning peut apprendre à repérer des formes simples, puis des objets plus complexes, avant de proposer une classe finale.",
            "advanced": "Les performances dépendent fortement des données, de l'architecture du réseau, de l'optimisation et de la régularisation. Le coût de calcul, l'explicabilité et le risque de surapprentissage font partie des limites importantes.",
            "summary": [
                "Le Deep Learning repose sur des réseaux de neurones profonds.",
                "Chaque couche apprend une représentation plus riche.",
                "Il est efficace sur des données complexes comme images, textes et sons.",
                "Il demande souvent beaucoup de données et de calcul.",
            ],
        },
        "ia_vs_ml": {
            "label": "différence entre IA et Machine Learning",
            "definition": "L'IA est le domaine général qui vise à créer des systèmes capables de réaliser des tâches intelligentes. Le Machine Learning est une partie de l'IA où le système apprend à partir de données.",
            "detail": "Une solution d'IA peut utiliser des règles, de la logique, de la recherche ou de l'apprentissage. Le Machine Learning se concentre sur les modèles qui détectent des régularités dans les données pour prédire, classer ou recommander.",
            "example": "Un chatbot à règles qui suit un scénario simple relève de l'IA. Un modèle qui apprend à classer des e-mails comme spam ou non-spam à partir d'exemples relève du Machine Learning.",
            "advanced": "Le Machine Learning n'est pas toute l'IA : il en est une approche. Ses résultats dépendent de la qualité des données, du choix du modèle, des métriques d'évaluation et de la généralisation sur des cas non vus.",
            "summary": [
                "L'IA est le domaine large.",
                "Le Machine Learning est une sous-partie de l'IA.",
                "Le Machine Learning apprend à partir de données.",
                "Toutes les solutions d'IA ne sont pas forcément apprenantes.",
            ],
        },
        "machine_learning": {
            "label": "Machine Learning",
            "definition": "Le Machine Learning permet à un programme d'apprendre des régularités dans des données pour prendre une décision ou faire une prédiction.",
            "detail": "On entraîne un modèle avec des exemples, puis on l'évalue sur de nouvelles données. Selon le problème, il peut s'agir de classification, de régression, de regroupement ou de recommandation.",
            "example": "Avec des historiques de notes et d'activités, un modèle peut estimer quels étudiants risquent d'avoir besoin d'un accompagnement supplémentaire.",
            "advanced": "Un bon pipeline inclut préparation des données, choix d'algorithme, validation, métriques adaptées et surveillance des biais. La généralisation est plus importante que la performance sur les seules données d'entraînement.",
            "summary": [
                "Le modèle apprend à partir d'exemples.",
                "Il sert à prédire, classer ou recommander.",
                "La qualité des données influence fortement le résultat.",
                "L'évaluation permet de vérifier si le modèle généralise.",
            ],
        },
        "prompt_engineering": {
            "label": "Prompt Engineering",
            "definition": "Le Prompt Engineering consiste à formuler une consigne claire pour obtenir une meilleure réponse d'un modèle d'IA.",
            "detail": "Un bon prompt précise le rôle attendu, le contexte, la tâche, le format de sortie et les contraintes. Cela aide le modèle à produire une réponse plus utile, plus structurée et plus adaptée au besoin.",
            "example": "Au lieu d'écrire 'explique le RAG', on peut demander : 'Explique le RAG à un débutant, avec une définition, un exemple et trois points à retenir'.",
            "advanced": "Les prompts peuvent intégrer exemples, critères d'évaluation, contraintes de ton et structure de sortie. Ils ne garantissent pas la vérité : il faut garder des sources, vérifier les réponses et limiter les ambiguïtés.",
            "summary": [
                "Un prompt est une consigne donnée au modèle.",
                "La précision du prompt influence la qualité de la réponse.",
                "Le contexte et le format attendu sont importants.",
                "Les réponses doivent être vérifiées avec des sources fiables.",
            ],
        },
        "ia": {
            "label": "Intelligence Artificielle",
            "definition": "L'Intelligence Artificielle regroupe des méthodes qui permettent à une machine d'accomplir des tâches qui demandent habituellement de l'intelligence humaine.",
            "detail": "Elle peut servir à comprendre un texte, reconnaître une image, recommander un contenu, dialoguer avec un utilisateur ou aider à prendre une décision.",
            "example": "Dans EduMentor AI, l'IA aide à adapter les contenus au niveau de l'apprenant et à répondre aux questions via le chatbot.",
            "advanced": "Un système d'IA doit être évalué selon sa performance, sa robustesse, ses biais, son explicabilité et son impact sur l'utilisateur.",
            "summary": [
                "L'IA vise à automatiser des tâches intelligentes.",
                "Elle peut utiliser des règles, des modèles ou des données.",
                "Elle sert à analyser, prédire, recommander ou dialoguer.",
                "Son usage doit rester contrôlé et vérifiable.",
            ],
        },
        "general": {
            "label": "le sujet demandé",
            "definition": "Le sujet correspond à une notion du cours retrouvée dans les documents pédagogiques.",
            "detail": "Le chatbot a recherché les passages les plus proches de la question, puis les reformule pour construire une réponse plus claire.",
            "example": "Si la question vise une notion précise, le système s'appuie sur les pages les plus pertinentes pour expliquer l'idée avec un exemple.",
            "advanced": "La qualité de la réponse dépend de la précision de la question, du contenu disponible dans les PDF et de la pertinence des passages retrouvés.",
            "summary": [
                "La réponse est basée sur les documents pédagogiques.",
                "Les passages sont retrouvés par recherche sémantique.",
                "Le contenu est reformulé pour être plus compréhensible.",
                "Les sources permettent de vérifier l'information.",
            ],
        },
    }

    return profiles.get(topic, profiles["general"])


def _definition_for_level(topic: str, profile: dict, level: str) -> str:
    if level == "avance":
        return f"{profile['definition']} Dans un contexte avancé, il faut aussi considérer ses hypothèses, ses limites et la manière dont il est évalué."
    return profile["definition"]


def _explanation_for_level(topic: str, profile: dict, level: str) -> str:
    if level == "debutant":
        return f"{profile['detail']} L'idée importante est de comprendre le principe général avant les détails techniques."
    if level == "avance":
        return f"{profile['detail']} {profile['advanced']}"
    return profile["detail"]


def _example_for_level(topic: str, profile: dict, level: str) -> str:
    if level == "debutant":
        return f"Exemple simple : {profile['example']}"
    if level == "avance":
        return f"Exemple technique : {profile['example']} On peut ensuite analyser la qualité du résultat avec des critères comme la pertinence, la couverture et les erreurs possibles."
    return profile["example"]


def _summary_for_level(profile: dict, level: str) -> list[str]:
    summary = list(profile["summary"])
    if level == "avance":
        summary.append("Il faut toujours vérifier les limites, les données utilisées et la qualité de l'évaluation.")
    return summary[:5]


def _exercise_for_level(topic: str, level: str) -> str:
    label = _topic_profile(topic)["label"]

    if level == "debutant":
        return f"En une phrase, explique avec tes mots ce que signifie {label}, puis donne un exemple très simple."
    if level == "avance":
        return f"Analyse une limite possible de {label} dans EduMentor AI, puis propose une amélioration technique mesurable."
    return f"Donne un exemple d'utilisation de {label} dans une plateforme d'apprentissage, puis indique quel résultat tu voudrais mesurer."


def _format_source_lines(results: list[dict]) -> list[str]:
    unique_sources: list[dict] = []
    seen: set[tuple[str, int | None]] = set()

    for result in results:
        key = (result.get("file_name") or result.get("pdf_name") or "", result.get("page_start") or result.get("page_number"))
        if key in seen:
            continue
        seen.add(key)
        unique_sources.append(result)

    lines = []
    for source in unique_sources:
        file_name = source.get("file_name") or source.get("pdf_name") or "support PDF"
        course_name = source.get("course_title") or source.get("course_name") or "cours"
        page = source.get("page_start") or source.get("page_number")
        lines.append(f"- {file_name} - {course_name} - page {page}")
    return lines


def _normalize_level(level: str) -> str:
    normalized = _normalize_text(level)

    if "debut" in normalized or (normalized.startswith("d") and "butant" in normalized):
        return "debutant"
    if "avanc" in normalized:
        return "avance"
    return "intermediaire"


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(character for character in normalized if unicodedata.category(character) != "Mn")


def rag_chat(
    message: str,
    level: str,
    context: list[dict] | None = None,
    db: Session | None = None,
    course_id: int | None = None,
    subject_id: int | None = None,
    client_message_id: str | None = None,
    preferred_language: str | None = None,
    current_user: UserProfile | None = None,
) -> dict:
    request_id = client_message_id or uuid4().hex
    current_message = message.strip()
    social_answer = _social_answer(message)
    if social_answer:
        _log_chat_request(request_id, current_user, current_message, "social", 0, "social")
        return {
            "answer": social_answer,
            "sources": [],
            "mode": "social",
            "request_id": request_id,
            "client_message_id": client_message_id,
            "used_rag": False,
            "used_general_llm": False,
        }

    contextual_message = _contextual_message(current_message, context or [])
    search_query = _search_query_for_current_message(current_message, context or [])
    detected_language = preferred_language or _detect_language(message)
    intent = _detect_french_bac_intent(current_message)
    pedagogical_profile = _student_pedagogical_profile(db, current_user) if db is not None and current_user is not None else []

    if intent == "out_of_scope":
        _log_chat_request(request_id, current_user, current_message, intent, 0, "out_of_scope")
        return {
            "answer": _out_of_scope_answer(detected_language),
            "sources": [],
            "mode": "out_of_scope",
            "request_id": request_id,
            "client_message_id": client_message_id,
            "course_id": course_id,
            "subject_id": subject_id,
            "intent": intent,
            "confidence": 0,
            "relevance": 0,
            "used_rag": False,
            "used_general_llm": False,
        }

    if intent == "targeted_practice":
        _log_chat_request(request_id, current_user, current_message, intent, 0, "targeted_practice")
        return {
            "answer": _targeted_practice_answer(level, pedagogical_profile),
            "sources": [],
            "mode": "targeted_practice",
            "request_id": request_id,
            "client_message_id": client_message_id,
            "course_id": course_id,
            "subject_id": subject_id,
            "intent": intent,
            "confidence": 0,
            "relevance": 0,
            "used_rag": False,
            "used_general_llm": False,
        }

    results: list[dict] = []
    resolved_course_id: int | None = None
    resolved_subject_id: int | None = None
    if db is not None:
        scope = _resolve_french_chat_scope(db, course_id, subject_id, current_user)
        resolved_course_id = scope.get("course_id")
        resolved_subject_id = scope.get("subject_id")
        results = rag_document_service.filtered_semantic_search(
            db,
            search_query,
            course_id=resolved_course_id,
            subject_id=resolved_subject_id,
            top_k=3,
            published_only=True,
        ) if (resolved_course_id or resolved_subject_id) else []
    elif _is_french_bac_related_question(current_message):
        results = []
    threshold = get_settings()["rag_score_threshold"]
    relevant_results = [result for result in results if float(result.get("score", 0)) >= threshold]
    relevant_results = _select_results_for_intent(current_message, intent, relevant_results)

    if relevant_results:
        mode = "rag_course" if resolved_course_id else "rag_subject" if resolved_subject_id else "rag_semantic"
        _log_chat_request(request_id, current_user, current_message, intent, len(relevant_results), mode)
        return {
            "answer": _build_french_rag_answer(current_message, level, relevant_results, intent, pedagogical_profile),
            "sources": [_format_chat_source(result) for result in relevant_results],
            "mode": mode,
            "request_id": request_id,
            "client_message_id": client_message_id,
            "course_id": resolved_course_id,
            "subject_id": resolved_subject_id or relevant_results[0].get("subject_id"),
            "intent": intent,
            "confidence": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
            "relevance": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
            "used_rag": True,
            "used_general_llm": False,
            "fallback_reason": None,
        }

    if _is_french_bac_related_question(current_message):
        _log_chat_request(request_id, current_user, current_message, intent, 0, "general_french")
        return {
            "answer": generate_general_answer(
                contextual_message,
                detected_language,
                level,
                pedagogical_profile=pedagogical_profile,
                intent=intent,
            ),
            "sources": [],
            "mode": "general_french",
            "request_id": request_id,
            "client_message_id": client_message_id,
            "label": _general_label(detected_language),
            "course_id": resolved_course_id or course_id,
            "subject_id": resolved_subject_id or subject_id,
            "intent": intent,
            "confidence": 0,
            "relevance": 0,
            "used_rag": False,
            "used_general_llm": True,
            "fallback_reason": "not_found_in_french_supports",
        }

    _log_chat_request(request_id, current_user, current_message, "out_of_scope", 0, "out_of_scope")
    return {
        "answer": _out_of_scope_answer(detected_language),
        "sources": [],
        "mode": "out_of_scope",
        "request_id": request_id,
        "client_message_id": client_message_id,
        "course_id": course_id,
        "subject_id": subject_id,
        "intent": "out_of_scope",
        "confidence": 0,
        "relevance": 0,
        "used_rag": False,
        "used_general_llm": False,
    }


def _validate_chat_scope(db: Session, course_id: int | None, subject_id: int | None) -> None:
    if course_id is None:
        return
    course = db.get(Course, course_id)
    if course is None or not course.published:
        raise HTTPException(status_code=404, detail="Cours introuvable ou non publie")
    if subject_id is not None and course.subject_id != subject_id:
        raise HTTPException(status_code=422, detail="Le cours ne correspond pas a la matiere selectionnee")


def _resolve_french_chat_scope(
    db: Session,
    course_id: int | None,
    subject_id: int | None,
    current_user: UserProfile | None,
) -> dict[str, int | None]:
    from app.services import course_service

    french_subject = _find_french_subject(db)
    requested_course = db.get(Course, course_id) if course_id else None
    if requested_course and _is_french_course(requested_course, french_subject):
        if course_service.can_access_course(db, requested_course, current_user):
            return {"course_id": requested_course.id, "subject_id": requested_course.subject_id}

    if subject_id and french_subject and subject_id == french_subject.id:
        return {"course_id": None, "subject_id": subject_id}

    preferred_course = _find_preferred_french_course(db, current_user, french_subject)
    if preferred_course is not None:
        return {"course_id": preferred_course.id, "subject_id": preferred_course.subject_id}

    if french_subject is not None:
        return {"course_id": None, "subject_id": french_subject.id}

    return {"course_id": None, "subject_id": None}


def _find_french_subject(db: Session) -> Subject | None:
    return db.scalars(
        select(Subject)
        .where(
            Subject.active.is_(True),
            or_(
                Subject.slug == "francais",
                Subject.name.ilike("%francais%"),
                Subject.name.ilike("%fran%C3%A7ais%"),
                Subject.name.ilike("%français%"),
            ),
        )
        .order_by(Subject.id)
        .limit(1)
    ).first()


def _find_preferred_french_course(db: Session, current_user: UserProfile | None, french_subject: Subject | None) -> Course | None:
    from app.services import course_service

    query = select(Course).where(Course.published.is_(True), Course.status.in_(["published", "active"]))
    if french_subject is not None:
        query = query.where(Course.subject_id == french_subject.id)
    query = query.order_by(Course.display_order, Course.id)
    courses = list(db.scalars(query))
    courses = [course for course in courses if _is_french_course(course, french_subject)]
    accessible = [course for course in courses if course_service.can_access_course(db, course, current_user)]
    if not accessible:
        return None
    regional = [
        course for course in accessible
        if "regional" in _normalize_text(" ".join([course.title or "", course.summary or "", course.description or ""]))
    ]
    return (regional or accessible)[0]


def _is_french_course(course: Course, french_subject: Subject | None = None) -> bool:
    if french_subject is not None and course.subject_id == french_subject.id:
        return True
    searchable = _normalize_text(" ".join([
        course.title or "",
        course.summary or "",
        course.description or "",
        course.level or "",
        str((course.information or {}).get("language") or ""),
    ]))
    return any(term in searchable for term in ("francais", "français", "regional", "bac", "antigone", "sefrioui", "victor hugo"))


def _student_pedagogical_profile(db: Session, current_user: UserProfile) -> list[dict]:
    try:
        prediction = student_weakness_model_service.predict_student_weaknesses(db, current_user)
    except Exception:
        return []

    competencies = prediction.get("competencies") if isinstance(prediction, dict) else []
    if not isinstance(competencies, list):
        return []

    allowed = {"Compréhension", "Langue", "Figures de style", "Production écrite", "Méthodologie"}
    normalized_allowed = {_normalize_text(item): item for item in allowed}
    profile: list[dict] = []
    for row in competencies:
        if not isinstance(row, dict):
            continue
        normalized_competence = _normalize_text(str(row.get("competence") or ""))
        if normalized_competence not in normalized_allowed:
            continue
        status = _public_weakness_status(row.get("status"))
        score = row.get("score_percentage")
        profile.append(
            {
                "competence": normalized_allowed[normalized_competence],
                "status": status,
                "score_percentage": round(float(score), 1) if isinstance(score, (int, float)) else None,
                "recommendation": str(row.get("recommendation") or "").strip(),
            }
        )
    return profile


def _public_weakness_status(status: object) -> str:
    normalized = _normalize_text(str(status or ""))
    if "faible" in normalized:
        return "faible"
    if "renforcer" in normalized:
        return "a renforcer"
    if "maitris" in normalized or "maitris" in normalized:
        return "maitrise"
    return "non evalue"


def _detect_french_bac_intent(message: str) -> str:
    if _is_old_ai_topic(message):
        return "out_of_scope"
    normalized = _normalize_text(message)
    if any(term in normalized for term in ("point faible", "points faibles", "competence la plus faible", "fais moi travailler", "entrainement cible", "reviser mes difficultes")):
        return "targeted_practice"
    if any(term in normalized for term in ("corrige", "correction", "ma reponse", "ma réponse", "ameliore ma reponse", "note ma reponse")):
        return "answer_correction"
    if any(term in normalized for term in ("figure de style", "metaphore", "comparaison", "personnification", "antithese", "hyperbole", "anaphore", "oxymore")):
        return "figure_of_style"
    if any(term in normalized for term in ("production ecrite", "rediger", "redaction", "introduction", "conclusion", "argument", "plan")):
        return "writing_assistance"
    if any(term in normalized for term in ("situer", "passage", "methode", "methodologie", "bareme", "gestion du temps", "consigne")):
        return "methodology_help"
    if any(term in normalized for term in ("regional", "examen")):
        return "regional_exam"
    if any(term in normalized for term in ("grammaire", "conjugaison", "langue", "vocabulaire", "discours direct", "discours indirect", "champ lexical")):
        return "language_help"
    if any(term in normalized for term in ("resume", "résume", "explique", "passage", "antigone", "creon", "créon", "boite a merveilles", "boîte à merveilles", "sidi mohamed", "sefrioui", "dernier jour", "condamne", "victor hugo", "jean anouilh")):
        return "work_explanation"
    if _is_french_bac_related_question(message):
        return "course_rag"
    return "out_of_scope"


def _is_old_ai_topic(message: str) -> bool:
    normalized = _normalize_text(message)
    blocked_terms = {
        "python",
        "machine learning",
        "deep learning",
        "prompt engineering",
        "overfitting",
        "underfitting",
        "backpropagation",
        "reinforcement learning",
        "diffusion model",
        "diffusion models",
        "intelligence artificielle",
        "artificial intelligence",
        "llm",
        "embedding",
        "chroma",
        "rag",
    }
    return any(term in normalized for term in blocked_terms)


def _is_french_bac_related_question(message: str) -> bool:
    normalized = _normalize_text(message)
    french_terms = {
        "francais",
        "français",
        "1ere bac",
        "premiere bac",
        "regional",
        "examen",
        "antigone",
        "creon",
        "boite a merveilles",
        "boîte à merveilles",
        "sidi mohamed",
        "dernier jour",
        "condamne",
        "victor hugo",
        "jean anouilh",
        "sefrioui",
        "figure de style",
        "metaphore",
        "comparaison",
        "personnification",
        "langue",
        "grammaire",
        "vocabulaire",
        "production ecrite",
        "redaction",
        "comprehension",
        "methodologie",
        "consigne",
        "corrige",
    }
    return any(term in normalized for term in french_terms)


def _targeted_practice_answer(level: str, pedagogical_profile: list[dict]) -> str:
    target = _weakest_competence(pedagogical_profile)
    competence = target.get("competence") or "Compréhension"
    recommendation = target.get("recommendation") or "Relisez attentivement la consigne puis justifiez votre reponse avec un indice du texte."
    if competence == "Langue":
        exercise = "Transformez cette phrase au discours indirect : Le professeur dit : \"Relisez le passage avant de repondre.\""
    elif competence == "Figures de style":
        exercise = "Identifiez la figure de style dans : \"La ville dormait sous un ciel lourd\", puis expliquez son effet."
    elif competence == "Production écrite":
        exercise = "Redigez une introduction courte sur le theme de la solidarite en annonçant clairement votre point de vue."
    elif competence == "Méthodologie":
        exercise = "Lisez une consigne d'examen, soulignez le verbe de consigne, puis indiquez le type de réponse attendu."
    else:
        exercise = "Lisez un court passage d'une oeuvre au programme, puis relevez le personnage principal, l'evenement important et l'idee dominante."
    return "\n\n".join([
        "### Entrainement cible",
        f"Nous allons travailler en priorite la competence : **{competence}**.",
        "### Exercice",
        exercise,
        "### Conseil",
        recommendation,
    ])


def _weakest_competence(pedagogical_profile: list[dict]) -> dict:
    priority = {"faible": 0, "a renforcer": 1, "non evalue": 2, "maitrise": 3}
    rows = pedagogical_profile or []
    if not rows:
        return {"competence": "Compréhension", "status": "non evalue", "score_percentage": None}
    return sorted(rows, key=lambda item: (priority.get(str(item.get("status")), 4), item.get("score_percentage") if item.get("score_percentage") is not None else 999))[0]


def _build_french_rag_answer(
    message: str,
    level: str,
    results: list[dict],
    intent: str,
    pedagogical_profile: list[dict],
) -> str:
    facts = _extract_french_facts(message, results)
    topic = _french_topic(message, results)
    profile_tip = _profile_tip_for_message(message, pedagogical_profile)
    if intent == "answer_correction":
        return "\n\n".join([
            "### Ce qui est correct",
            facts[0] if facts else "Votre réponse contient une piste utile, mais elle doit être vérifiée avec le texte.",
            "### Ce qui doit être amélioré",
            "Ajoutez un indice précis du passage et reliez-le clairement à l’œuvre ou à la consigne.",
            "### Proposition corrigée",
            "Formulez une réponse courte, puis justifiez-la par un élément observé dans le texte.",
            "### Conseil",
            profile_tip or "Pour progresser, commencez toujours par repérer les mots de la consigne.",
        ])
    if intent == "figure_of_style":
        return "\n\n".join([
            "### Figure",
            facts[0] if facts else "La figure doit être identifiée à partir des mots exacts de la phrase.",
            "### Indice dans la phrase",
            "Repérez le rapprochement, l’exagération ou le fait qu’un objet reçoit une action humaine.",
            "### Effet recherché",
            "Expliquez ce que cette image ajoute au sens du passage.",
        ])
    if intent == "writing_assistance":
        return "\n\n".join([
            "### Compréhension du sujet",
            f"Le sujet demande de traiter clairement le thème lié à {topic}.",
            "### Problématique",
            "Transformez le thème en une question simple : pourquoi cette valeur est-elle importante et comment apparaît-elle dans la vie quotidienne ou dans une œuvre ?",
            "### Plan proposé",
            "- Introduction courte avec le thème et la problématique\n- Deux arguments organisés\n- Conclusion qui reprend l’idée principale",
            "### Exemple d’introduction",
            "La solidarité est une valeur essentielle, car elle aide les personnes à affronter les difficultés ensemble. On peut donc se demander comment elle renforce les liens entre les individus.",
            "### Arguments possibles",
            "\n".join(f"- {fact}" for fact in (facts[:3] or ["Appuyez chaque argument sur un exemple clair."])),
            "### Conseils de rédaction",
            profile_tip or "Utilisez des connecteurs logiques et évitez les phrases trop longues.",
        ])
    if intent in {"methodology_help", "regional_exam"}:
        return "\n\n".join([
            "### Méthode",
            "Situer un passage consiste à présenter rapidement l’œuvre, le moment de l’histoire et l’événement qui entoure l’extrait.",
            "### Étapes",
            "- Nommer l’œuvre et l’auteur si la question le demande.\n- Dire ce qui se passe juste avant le passage.\n- Identifier les personnages présents ou concernés.\n- Relier le passage à l’événement principal ou au thème dominant.",
            "### Exemple de formulation",
            "Ce passage se situe après un événement important du récit. Il met en scène un personnage dans une situation précise et permet de comprendre la suite de l’action.",
            "### Erreurs à éviter",
            "- Recopier tout le texte support.\n- Donner une réponse vague sans événement précédent.\n- Inventer un chapitre, une page ou une citation absente du document.",
        ])
    if intent == "language_help":
        return _build_language_help_answer(message, results, facts, profile_tip)
    return "\n\n".join([
        "### Réponse",
        facts[0] if facts else f"La question porte sur {topic}.",
        "### Explication",
        " ".join(facts[:4]) if facts else "Les supports disponibles donnent des éléments proches, mais pas assez de détails pour affirmer une information précise.",
        "### À retenir",
        "\n".join(f"- {item}" for item in (facts[:3] or ["Vérifier l’information dans le support du cours.", "Justifier avec un indice du texte.", "Adapter la réponse à la consigne."])),
        "### Petit exercice",
        profile_tip or "Expliquez l’idée principale en deux phrases, puis ajoutez un exemple du texte.",
    ])


def _build_language_help_answer(
    message: str,
    results: list[dict],
    facts: list[str],
    profile_tip: str,
) -> str:
    normalized = _normalize_text(message)
    combined = " ".join(str(result.get("text_preview") or result.get("excerpt") or "") for result in results)

    if "champ" in normalized and "lexical" in normalized:
        definition = _find_supported_sentence(
            combined,
            (r"un champ lexical est[^.?!]*[.?!]", r"le champ lexical[^.?!]*(?:ensemble|mots)[^.?!]*[.?!]"),
        )
        if not definition:
            definition = "Un champ lexical est un ensemble de mots liés à une même idée, une même réalité ou un même domaine."
        example = _extract_field_example(combined)
        return "\n\n".join([
            "### Réponse",
            definition,
            "### Comment le reconnaître ?",
            "Repérez plusieurs mots qui se rapportent au même thème. Ils peuvent être des synonymes, appartenir à la même famille ou au même domaine.",
            "### Exemple",
            example or "Dans le champ lexical du sommeil, on peut relever : « sommeil », « se réveiller » et « se recoucher ».",
            "### À retenir",
            "Un seul mot ne suffit pas : il faut relever plusieurs termes liés au même thème, puis expliquer ce qu’ils révèlent dans le texte.",
            "### Petit exercice",
            profile_tip or "Relevez trois mots appartenant au champ lexical de la peur dans un court passage.",
        ])

    if "discours direct" in normalized or "discours indirect" in normalized:
        return "\n\n".join([
            "### Réponse",
            facts[0] if facts else "Le discours direct rapporte les paroles telles qu’elles sont prononcées, tandis que le discours indirect les intègre dans la phrase du narrateur.",
            "### Indices",
            "Le discours direct utilise généralement les deux-points, les guillemets ou les tirets. Le discours indirect utilise un verbe introducteur suivi de « que », « si » ou d’un mot interrogatif.",
            "### À retenir",
            "Le passage au discours indirect peut entraîner des changements de pronoms, de temps verbaux et d’indications de temps ou de lieu.",
            "### Petit exercice",
            "Transformez au discours indirect : Il déclara : « Je viendrai demain. »",
        ])

    clean_facts = facts[:3]
    return "\n\n".join([
        "### Réponse",
        clean_facts[0] if clean_facts else "La notion doit être définie à partir du cours sélectionné.",
        "### Explication",
        " ".join(clean_facts[1:]) if len(clean_facts) > 1 else "Repérez la règle, puis appliquez-la à un exemple court.",
        "### À retenir",
        "Identifiez d’abord la notion demandée, puis justifiez votre réponse avec un indice précis.",
        "### Petit exercice",
        profile_tip or "Donnez un exemple personnel qui applique cette règle de langue.",
    ])


def _find_supported_sentence(text: str, patterns: tuple[str, ...]) -> str:
    normalized_space = " ".join(str(text or "").split())
    for pattern in patterns:
        match = re.search(pattern, normalized_space, flags=re.IGNORECASE)
        if match:
            return _clean_source_sentence(match.group(0))
    return ""


def _extract_field_example(text: str) -> str:
    normalized = _normalize_text(text)
    if "sommeil" in normalized and ("reveill" in normalized or "recoucher" in normalized):
        return "Dans le texte de l’Achoura, « sommeil », « se réveiller » et « se recoucher » appartiennent au champ lexical du sommeil."
    return ""


def _select_results_for_intent(message: str, intent: str, results: list[dict]) -> list[dict]:
    if not results:
        return []
    normalized = _normalize_text(message)
    lesson_types = {
        "language_lesson",
        "grammar_lesson",
        "enunciation_lesson",
        "reported_speech_lesson",
        "language_register_lesson",
        "literary_register_lesson",
        "figure_of_style_lesson",
        "methodology",
        "writing_guide",
        "work_sheet",
        "work_summary",
        "work_structure",
        "work_characters",
    }

    def result_key(result: dict) -> tuple[float, float]:
        document_type = str(result.get("document_type") or "").lower()
        chapter = _normalize_text(str(result.get("chapter_title") or ""))
        text = _normalize_text(str(result.get("text_preview") or result.get("excerpt") or ""))
        bonus = 0.0
        if intent == "language_help" and document_type in lesson_types:
            bonus += 1.0
        if "champ" in normalized and "lexical" in normalized and "champ" in (chapter + " " + text) and "lexical" in (chapter + " " + text):
            bonus += 2.0
        if intent == "figure_of_style" and "figure" in document_type:
            bonus += 1.0
        if intent == "methodology_help" and document_type == "methodology":
            bonus += 1.0
        if intent == "writing_assistance" and document_type in {"writing_guide", "writing_topic", "scoring_rubric"}:
            bonus += 1.0
        if document_type.startswith("regional_exam") and intent == "language_help" and not any(term in normalized for term in ("examen", "question", "regional", "ancienne")):
            bonus -= 0.8
        return bonus, float(result.get("score", 0))

    ordered = sorted(results, key=result_key, reverse=True)
    if intent == "language_help":
        lessons = [item for item in ordered if str(item.get("document_type") or "").lower() in lesson_types]
        if lessons:
            examples = [item for item in ordered if item not in lessons and _result_matches_query_terms(message, item)]
            return (lessons[:2] + examples[:1])[:3]
    return ordered[:3]


def _result_matches_query_terms(message: str, result: dict) -> bool:
    query_terms = {term for term in re.findall(r"[a-z0-9]+", _normalize_text(message)) if len(term) >= 4}
    text = _normalize_text(" ".join([
        str(result.get("chapter_title") or ""),
        str(result.get("text_preview") or result.get("excerpt") or ""),
    ]))
    return bool(query_terms) and sum(1 for term in query_terms if term in text) >= min(2, len(query_terms))

def _french_topic(message: str, results: list[dict]) -> str:
    normalized = _normalize_text(message)
    if "antigone" in normalized or "creon" in normalized:
        return "Antigone"
    if "boite" in normalized or "sidi mohamed" in normalized:
        return "La Boîte à merveilles"
    if "dernier jour" in normalized or "condamne" in normalized:
        return "Le Dernier Jour d'un condamne"
    if results:
        title = results[0].get("chapter_title") or results[0].get("course_title") or results[0].get("course_name")
        if title:
            return str(title)
    return "le français de 1ère Bac"


def _profile_tip_for_message(message: str, pedagogical_profile: list[dict]) -> str:
    if not pedagogical_profile:
        return ""
    target = _weakest_competence(pedagogical_profile)
    competence = target.get("competence")
    if not competence:
        return ""
    return f"Pour renforcer votre compétence en {competence.lower()}, avancez par étapes et justifiez chaque réponse avec un indice clair."


def _extract_french_facts(message: str, results: list[dict]) -> list[str]:
    facts = _sentences_from_results(results)
    normalized_message = _normalize_text(message)
    all_text = " ".join(str(result.get("text_preview") or result.get("excerpt") or "") for result in results)
    normalized_text = _normalize_text(all_text)
    priority: list[str] = []
    if "auteur" in normalized_message and "ahmed sefrioui" in normalized_text:
        priority.append("L'auteur de La Boîte à merveilles est Ahmed Sefrioui.")
    if "personnification" in normalized_text and ("djellaba" in normalized_message or "dormait" in normalized_message):
        priority.append("Dans l'expression la djellaba dormait, l'objet reçoit une action humaine : c'est une personnification.")
    if "narrateur externe" in normalized_message and "sidi mohamed" in normalized_text:
        priority.append("Sidi Mohamed n'est pas un narrateur externe : dans La Boîte à merveilles, il raconte son expérience d'enfant à la première personne.")
    return _unique_items(priority + facts)


def _build_multi_course_rag_answer(message: str, level: str, results: list[dict]) -> str:
    normalized_level = _normalize_level(level)
    topic = _human_topic(message, results)
    key_facts = _extract_key_facts(message, results)
    sources = _format_source_lines(results)
    explanation = _pedagogical_explanation(topic, key_facts, normalized_level)
    example = _contextual_example(topic, key_facts, results, normalized_level)
    summary = _summary_from_facts(topic, key_facts)
    exercise = _exercise_for_topic(topic, normalized_level)

    return "\n\n".join(
        [
            f"# Définition simple\n\n{_simple_definition(topic, key_facts, normalized_level)}",
            f"# Explication détaillée\n\n{explanation}",
            f"# Exemple concret\n\n{example}",
            "# Résumé\n\n" + "\n".join(f"- {item}" for item in summary[:5]),
            f"# Mini exercice\n\n{exercise}",
            "# Sources utilisées\n\n" + "\n".join(sources),
        ]
    )


def _human_topic(message: str, results: list[dict]) -> str:
    normalized = _normalize_text(message)
    if "erreur" in normalized:
        return "les erreurs en programmation"
    if "regle" in normalized or "or" in normalized:
        return "les bonnes pratiques de programmation"
    if "installer" in normalized or "installation" in normalized:
        return "l'installation de Python"
    if "python" in normalized:
        return "Python"
    if "programmation" in normalized:
        return "la programmation"
    if "rag" in normalized:
        return "le RAG"
    if "deep learning" in normalized:
        return "le Deep Learning"
    if results:
        title = results[0].get("chapter_title") or results[0].get("course_title") or results[0].get("course_name")
        if title:
            return str(title)
    return "la notion demandee"


def _extract_key_facts(message: str, results: list[dict]) -> list[str]:
    text = " ".join(str(result.get("text_preview") or result.get("excerpt") or "") for result in results)
    normalized = _normalize_text(f"{message} {text}")
    facts: list[str] = []
    if "erreur" in normalized:
        facts.extend([
            "Les erreurs de syntaxe apparaissent quand le code ne respecte pas la grammaire du langage.",
            "Les erreurs semantiques produisent un resultat incorrect meme si le programme s'execute.",
            "Les erreurs d'execution surviennent pendant le lancement du programme, par exemple avec une operation impossible.",
        ])
    if "regle" in normalized or "or" in normalized:
        facts.extend([
            "Donner des noms clairs aux variables et aux fonctions.",
            "Commenter le code lorsque cela aide reellement la comprehension.",
            "Tester regulierement le programme avec des cas simples.",
            "Organiser le code en petites parties lisibles.",
            "Corriger les erreurs progressivement au lieu de tout changer en meme temps.",
        ])
    if "python" in normalized:
        facts.extend([
            "Python est un langage lisible, populaire et adapte aux debutants.",
            "Il est utilise pour l'automatisation, la data science, l'IA et le developpement web.",
        ])
    if "installer" in normalized or "installation" in normalized:
        facts.extend([
            "L'installation consiste a recuperer Python depuis une source officielle puis a verifier que la commande python fonctionne.",
            "Les captures ou versions indiquees dans un support peuvent evoluer avec le temps.",
        ])
    if "programmation" in normalized and not facts:
        facts.extend([
            "Programmer consiste a ecrire des instructions que l'ordinateur peut executer.",
            "Un programme decompose un probleme en etapes claires et testables.",
        ])
    if not facts:
        facts = _sentences_from_results(results)
    return _unique_items(facts)[:7]


def _simple_definition(topic: str, facts: list[str], level: str) -> str:
    if facts:
        return f"{topic.capitalize()} correspond ici a une idee du cours que l'on peut comprendre ainsi : {facts[0]}"
    return f"{topic.capitalize()} est une notion presente dans les supports du cours selectionne."


def _pedagogical_explanation(topic: str, facts: list[str], level: str) -> str:
    if not facts:
        return f"Le support selectionne contient des passages proches de votre question sur {topic}. La reponse reste volontairement prudente car peu d'elements explicites ont ete retrouves."
    if level == "debutant":
        return " ".join([facts[0], "L'idee principale est de partir d'un exemple simple, puis de verifier chaque etape avant d'aller plus loin."] + facts[1:3])
    if level == "avance":
        return " ".join(facts + ["Dans une lecture avancee, il faut aussi distinguer le principe, les cas limites et les conditions dans lesquelles l'explication reste valable."])
    return " ".join(facts[:5])


def _contextual_example(topic: str, facts: list[str], results: list[dict], level: str) -> str:
    normalized_topic = _normalize_text(topic)
    if "erreur" in normalized_topic:
        return "Si un programme affiche une erreur parce qu'une parenthese manque, c'est plutot une erreur de syntaxe. S'il calcule un total faux, le probleme est plutot semantique."
    if "installation" in normalized_topic:
        return "Un apprenant installe Python, ouvre un terminal, tape une commande de verification, puis lance un premier fichier simple pour confirmer que l'environnement fonctionne."
    if "programmation" in normalized_topic:
        return "Pour calculer une moyenne, on peut demander les notes, les additionner, diviser par leur nombre, puis afficher le resultat : chaque ligne correspond a une etape du raisonnement."
    if "python" in normalized_topic:
        return "Dans EduMentor AI, Python peut servir a automatiser l'extraction de texte d'un PDF ou a preparer des donnees avant leur indexation RAG."
    return "Prenez une question du cours, identifiez les mots importants, puis reliez-les aux passages sources affiches sous la reponse."


def _summary_from_facts(topic: str, facts: list[str]) -> list[str]:
    if not facts:
        return [
            "La reponse provient des supports selectionnes.",
            "Les sources indiquent le cours, le document et la page.",
            "Une verification dans le PDF reste possible.",
        ]
    return facts[:4] + ["Les sources permettent de verifier le passage utilise."]


def _exercise_for_topic(topic: str, level: str) -> str:
    if level == "avance":
        return f"Identifiez une limite ou un cas particulier lie a {topic}, puis proposez une verification concrete a effectuer dans un programme ou un document."
    if level == "debutant":
        return f"Expliquez {topic} avec vos propres mots en deux phrases, puis donnez un petit exemple."
    return f"Construisez un exemple court qui illustre {topic}, puis indiquez comment vous verifieriez que votre reponse est correcte."


def _sentences_from_results(results: list[dict]) -> list[str]:
    sentences: list[str] = []
    blocked_prefixes = (
        "examen:",
        "oeuvre:",
        "question ",
        "competence:",
        "type:",
        "bareme:",
        "barème:",
        "elements attendus:",
        "éléments attendus:",
        "correction officielle",
        "correction verifiee",
        "correction vérifiée",
        "source pedagogique complementaire:",
        "source pédagogique complémentaire:",
    )
    for result in results:
        text = str(result.get("text_preview") or result.get("excerpt") or "")
        text = re.sub(r"Source pédagogique complémentaire\s*:[^.]*\.\s*Page\s+\d+\.\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"Source pedagogique complementaire\s*:[^.]*\.\s*Page\s+\d+\.\s*", "", text, flags=re.IGNORECASE)
        for part in re.split(r"(?<=[.!?])\s+|\n+", text):
            clean = _clean_source_sentence(part)
            normalized = _normalize_text(clean)
            if not clean or len(clean) < 35 or len(clean) > 280:
                continue
            if any(normalized.startswith(_normalize_text(prefix)) for prefix in blocked_prefixes):
                continue
            if "bareme" in normalized or "elements attendus" in normalized or "question_type" in normalized:
                continue
            sentences.append(clean)
    return _unique_items(sentences)[:6]


def _clean_source_sentence(value: str) -> str:
    clean = " ".join(str(value or "").split()).strip(" -;:")
    clean = re.sub(r"\b0\s*\.\s*25\b", "0,25", clean)
    clean = re.sub(r"\b1\s*\.\s*0\b", "1", clean)
    if clean and clean[-1] not in ".!?":
        clean += "."
    return clean

def _unique_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = _normalize_text(item)
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _format_chat_source(result: dict) -> dict:
    page_start = result.get("page_start") or result.get("page_number")
    page_end = result.get("page_end") or page_start
    display_source = result.get("display_source") or result.get("source_label")
    return {
        "chunk_id": result.get("chunk_id"),
        "course_id": result.get("course_id"),
        "course_title": result.get("course_title") or result.get("course_name"),
        "course_name": result.get("course_title") or result.get("course_name"),
        "subject_id": result.get("subject_id"),
        "subject_name": result.get("subject_name"),
        "subject_slug": result.get("subject_slug"),
        "document_id": result.get("document_id"),
        "file_name": result.get("file_name") or result.get("pdf_name"),
        "pdf_name": result.get("pdf_name") or result.get("file_name"),
        "file_url": result.get("file_url"),
        "page_number": page_start,
        "page_start": page_start,
        "page_end": page_end,
        "chapter_title": result.get("chapter_title"),
        "score": result.get("score"),
        "excerpt": result.get("excerpt") or result.get("text_preview", ""),
        "source_label": display_source,
        "display_source": display_source,
        "document_type": result.get("document_type"),
        "work": result.get("work"),
        "competence": result.get("competence"),
        "year": result.get("year"),
        "region": result.get("region"),
        "session": result.get("session"),
        "verified": result.get("verified"),
    }


def _detect_language(message: str) -> str:
    normalized = _normalize_text(message)
    arabic_count = sum(1 for character in message if "\u0600" <= character <= "\u06ff")

    if arabic_count >= 2:
        darija_terms = {
            "شنو",
            "اش",
            "واش",
            "علاش",
            "كيفاش",
            "بزاف",
            "دابا",
            "هاد",
            "ديال",
            "فاش",
        }
        return "darija" if any(term in message for term in darija_terms) else "arabic"

    english_terms = {
        "what",
        "how",
        "why",
        "explain",
        "difference",
        "between",
        "example",
        "best",
        "model",
        "training",
    }
    french_terms = {
        "c'est",
        "quoi",
        "explique",
        "difference",
        "différence",
        "comment",
        "pourquoi",
        "donne",
        "exemple",
    }

    english_score = sum(1 for term in english_terms if term in normalized)
    french_score = sum(1 for term in french_terms if term in normalized)
    return "english" if english_score > french_score else "french"


def _is_ai_related_question(message: str) -> bool:
    normalized = _normalize_text(message)
    ai_keywords = {
        "ai",
        "ia",
        "backpropagation",
        "back propagation",
        "backprop",
        "bias variance",
        "cross entropy",
        "gradient descent",
        "intelligence artificielle",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "overfit",
        "overfitting",
        "underfit",
        "underfitting",
        "llm",
        "large language model",
        "modele de langage",
        "model de langage",
        "prompt",
        "rag",
        "retrieval",
        "chatbot",
        "embedding",
        "embeddings",
        "vector",
        "vecteur",
        "neural",
        "neurone",
        "neurones",
        "dataset",
        "donnees",
        "données",
        "classification",
        "regression",
        "transformer",
        "generative",
        "generative ai",
        "ia generative",
        "diffusion",
        "computer vision",
        "nlp",
        "traitement du langage",
        "reinforcement learning",
        "supervised learning",
        "unsupervised learning",
        "apprentissage par renforcement",
        "apprentissage supervise",
        "apprentissage non supervise",
        "ذكاء اصطناعي",
        "الذكاء الاصطناعي",
        "تعلم الالة",
        "تعلم الآلة",
        "تعلم عميق",
        "نماذج اللغة",
        "شات بوت",
        "شاتبوٹ",
    }

    return any(_contains_ai_keyword(normalized, message, keyword) for keyword in ai_keywords)


def _is_education_related_question(message: str) -> bool:
    if _is_ai_related_question(message):
        return True
    normalized = _normalize_text(message)
    education_keywords = {
        "ai",
        "ia",
        "intelligence artificielle",
        "machine learning",
        "deep learning",
        "llm",
        "rag",
        "prompt",
        "chatbot",
        "apprendre",
        "apprentissage",
        "cours",
        "exercice",
        "explique",
        "explain",
        "definition",
        "definir",
        "comprendre",
        "programmation",
        "programming",
        "python",
        "erreur",
        "algorithme",
        "code",
        "fonction",
        "variable",
        "informatique",
        "mathematique",
        "math",
        "physique",
        "chimie",
        "biologie",
        "education",
        "pedagogique",
    }
    return any(_contains_ai_keyword(normalized, message, keyword) for keyword in education_keywords)


def _contains_ai_keyword(normalized_message: str, original_message: str, keyword: str) -> bool:
    normalized_keyword = _normalize_text(keyword)

    if normalized_keyword in {"ai", "ia", "rag", "llm", "nlp"}:
        tokens = {
            token.strip(".,;:!?()[]{}\"'")
            for token in normalized_message.replace("/", " ").replace("-", " ").split()
        }
        return normalized_keyword in tokens

    return normalized_keyword in normalized_message or keyword in original_message


def _contextual_message(message: str, context: list[dict]) -> str:
    if not _needs_context(message):
        return message

    recent_context = [
        str(item.get("content") or item.get("text") or "").strip()
        for item in context[-6:]
        if str(item.get("content") or item.get("text") or "").strip()
    ]
    if not recent_context:
        return message

    context_text = " ".join(recent_context[-3:])
    return (
        "Réponds à la dernière question utilisateur. Le contexte précédent sert uniquement à comprendre "
        "les références ambiguës et ne doit pas remplacer la demande actuelle.\n"
        f"Question actuelle: {message}\n"
        f"Contexte secondaire: {context_text}"
    )


def _search_query_for_current_message(message: str, context: list[dict]) -> str:
    if not _needs_context(message):
        return message
    recent_user_messages = [
        str(item.get("content") or item.get("text") or "").strip()
        for item in context[-6:]
        if str(item.get("role") or "").lower() == "user"
        and str(item.get("content") or item.get("text") or "").strip()
    ]
    if not recent_user_messages:
        return message
    return f"{message}\nContexte secondaire bref: {recent_user_messages[-1]}"

def _needs_context(message: str) -> bool:
    normalized = _normalize_social_text(message)
    context_markers = {
        "it",
        "this",
        "that",
        "ça",
        "ca",
        "cela",
        "ce concept",
        "cette notion",
        "hadak",
        "hadi",
        "hada",
        "dakchi",
        "explain it",
        "explique ca",
        "explique ça",
        "give an example",
    }
    return any(marker in normalized for marker in context_markers)




def _log_chat_request(
    request_id: str,
    current_user: UserProfile | None,
    message: str,
    intent: str,
    source_count: int,
    mode: str,
) -> None:
    logger.info(
        "chat_request request_id=%s user_id=%s intent=%s mode=%s sources=%s message=%r",
        request_id,
        current_user.id if current_user else None,
        intent,
        mode,
        source_count,
        message[:160],
    )

def _general_label(language: str) -> str:
    if language == "english":
        return "General answer"
    if language == "arabic":
        return "إجابة عامة"
    return "Réponse générale"


def _social_answer(message: str) -> str | None:
    normalized = _normalize_social_text(message)
    compact = normalized.replace(" ", "")

    social_answers = {
        "bonjour": "Bonjour 👋 Comment puis-je vous aider aujourd'hui ?",
        "bonsoir": "Bonsoir 👋 Comment puis-je vous aider aujourd'hui ?",
        "salut": "Salut 👋 Comment puis-je t'aider aujourd'hui ?",
        "hello": "Hello 👋 How can I help you today?",
        "hi": "Hello 👋 How can I help you today?",
        "hey": "Hello 👋 How can I help you today?",
        "merci": "Avec plaisir 😊",
        "thanks": "You're welcome 😊",
        "thank you": "You're welcome 😊",
        "m7tajk": "😊 Je suis là pour t'aider. Pose-moi ta question.",
        "mhtajk": "😊 Je suis là pour t'aider. Pose-moi ta question.",
        "besoin d aide": "😊 Je suis là pour vous aider. Posez-moi votre question.",
        "besoin daide": "😊 Je suis là pour vous aider. Posez-moi votre question.",
        "need help": "😊 I'm here to help. Ask me your question.",
        "help": "😊 I'm here to help. Ask me your question.",
        "comment vas tu": "Je vais très bien, merci ! Comment puis-je vous aider ?",
        "comment ca va": "Je vais très bien, merci ! Comment puis-je vous aider ?",
        "ca va": "Je vais très bien, merci ! Comment puis-je vous aider ?",
        "how are you": "I'm doing very well, thank you! How can I help you?",
    }

    if normalized in social_answers:
        return social_answers[normalized]

    if compact in {"besoindaide", "commentvastu", "commentcava", "howareyou"}:
        if compact == "howareyou":
            return social_answers["how are you"]
        if compact.startswith("comment") or compact == "cava":
            return "Je vais très bien, merci ! Comment puis-je vous aider ?"
        return "😊 Je suis là pour vous aider. Posez-moi votre question."

    return None


def _normalize_social_text(message: str) -> str:
    normalized = _normalize_text(message)
    for source in ("?", "!", ".", ",", ";", ":", "'", "'", "-", "_"):
        normalized = normalized.replace(source, " ")
    return " ".join(normalized.split())


def _out_of_scope_answer(language: str) -> str:
    if language == "english":
        return (
            "I am specialized in EduMentor AI courses about Artificial Intelligence. "
            "Please ask me a question about AI, Machine Learning, Deep Learning, LLMs, Prompt Engineering, RAG, chatbots, or responsible AI."
        )
    if language == "arabic":
        return (
            "أنا مساعد متخصص في دروس EduMentor AI حول الذكاء الاصطناعي. "
            "من فضلك اطرح سؤالا مرتبطا بالذكاء الاصطناعي أو تعلم الآلة أو RAG أو الشات بوت."
        )
    if language == "darija":
        return (
            "أنا مساعد متخصص فدروس EduMentor AI ديال الذكاء الاصطناعي. "
            "سولني على IA، Machine Learning، Deep Learning، RAG، Prompt Engineering ولا Chatbots."
        )
    return (
        "Je suis spécialisé dans les cours d'IA EduMentor AI. "
        "Posez-moi une question sur l'IA, le Machine Learning, le Deep Learning, les LLM, le Prompt Engineering, le RAG, les chatbots ou l'IA responsable."
    )

# Final French 1ere Bac scope guard for the active chatbot path.
def _out_of_scope_answer(language: str) -> str:
    if language == "english":
        return (
            "I am specialized in Moroccan 1st-year baccalaureate French regional exam preparation. "
            "Please ask me about a program work, a language exercise, a figure of speech, methodology, or written production."
        )
    return (
        "Je suis spécialisé dans la préparation au régional de français de 1ère Bac. "
        "Posez-moi une question sur une œuvre au programme, un exercice de langue, une figure de style, la méthodologie ou une production écrite."
    )

