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
from app.services import french_chat_scope_service, rag_document_service, student_weakness_model_service
from app.services.groq_service import generate_general_answer
from app.services.mock_data import COURSES, LEARNER, QUIZZES, RECOMMENDATIONS

logger = logging.getLogger(__name__)

WORK_FACTS = {
    "antigone": {
        "title": "Antigone",
        "author": "Jean Anouilh",
        "genre": "tragédie moderne",
        "date": "1944",
        "source": "Sigma Français 1er Bac — Antigone, p. 21",
    },
    "la_boite_a_merveilles": {
        "title": "La Boîte à merveilles",
        "author": "Ahmed Sefrioui",
        "genre": "roman autobiographique",
        "source": "Sigma Français 1er Bac — La Boîte à merveilles, p. 16",
    },
    "dernier_jour_condamne": {
        "title": "Le Dernier Jour d'un condamné",
        "author": "Victor Hugo",
        "genre": "roman à thèse",
        "source": "Sigma Français 1er Bac — Le Dernier Jour d'un condamné, p. 25",
    },
}

MOJIBAKE_REPLACEMENTS = {
    "ÃƒÂ©": "é",
    "ÃƒÂ¨": "è",
    "ÃƒÂª": "ê",
    "ÃƒÂ«": "ë",
    "ÃƒÂ ": "à",
    "ÃƒÂ¢": "â",
    "ÃƒÂ®": "î",
    "ÃƒÂ¯": "ï",
    "ÃƒÂ´": "ô",
    "ÃƒÂ»": "û",
    "ÃƒÂ¹": "ù",
    "ÃƒÂ§": "ç",
    "Ãƒâ€°": "É",
    "Ãƒâ‚¬": "À",
    "Ã…â€œ": "œ",
    "Ã¢â‚¬â„¢": "’",
    "Ã¢â‚¬â€œ": "–",
    "Ã¢â‚¬â€": "—",
    "Ã¢â‚¬Â¢": "•",
    "Ã‚Â«": "«",
    "Ã‚Â»": "»",
    "Ã‚Â": "",
    "Ã©": "é",
    "Ã¨": "è",
    "Ãª": "ê",
    "Ã«": "ë",
    "Ã ": "à",
    "Ã¢": "â",
    "Ã®": "î",
    "Ã¯": "ï",
    "Ã´": "ô",
    "Ã»": "û",
    "Ã¹": "ù",
    "Ã§": "ç",
    "Ã‰": "É",
    "Ã€": "À",
    "â€™": "’",
    "â€œ": "“",
    "â€": "”",
    "â€”": "—",
    "â€“": "–",
    "â€¢": "•",
    "Å“": "œ",
}


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
                "Je n'ai pas trouvÃ© cette information dans les documents PDF disponibles. "
                "Essayez de reformuler la question ou de cibler un cours prÃ©cis."
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
            f"# DÃ©finition simple\n\n{definition}",
            f"# Explication dÃ©taillÃ©e\n\n{explanation}",
            f"# Exemple concret\n\n{example}",
            "# RÃ©sumÃ©\n\n" + "\n".join(f"- {item}" for item in summary),
            f"# Mini exercice\n\n{exercise}",
            "# Sources utilisÃ©es\n\n" + "\n".join(source_lines),
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
        return ["Revoir les personnages des trois oeuvres", "Faire des exercices guidÃ©s de comprÃ©hension"]
    if level == "Avance":
        return ["Travailler la production Ã©crite argumentative", "Comparer les thÃ¨mes des trois oeuvres"]
    return ["Renforcer les figures de style", "RÃ©viser les points faibles avec le chatbot"]


def _detect_topic(message: str, results: list[dict]) -> str:
    searchable = " ".join(
        [
            _normalize_text(message),
            *(_normalize_text(result.get("course_name", "")) for result in results),
            *(_normalize_text(result.get("file_name", "")) for result in results),
        ]
    )
    if "antigone" in searchable:
        return "antigone"
    if "boite a merveilles" in searchable or "boîte à merveilles" in searchable:
        return "boite_merveilles"
    if "dernier jour" in searchable or "condamne" in searchable or "condamné" in searchable:
        return "dernier_jour"
    if "figure" in searchable or "metaphore" in searchable or "métaphore" in searchable or "comparaison" in searchable:
        return "figures_style"
    if "production" in searchable or "redaction" in searchable or "rédaction" in searchable:
        return "production_ecrite"
    if "langue" in searchable or "grammaire" in searchable or "vocabulaire" in searchable:
        return "langue"
    if "methodologie" in searchable or "méthodologie" in searchable or "regional" in searchable or "régional" in searchable:
        return "methodologie"
    return "general"


def _topic_profile(topic: str) -> dict:
    profiles = {
        "antigone": {
            "label": "Antigone",
            "definition": "Antigone est une tragédie moderne de Jean Anouilh étudiée en 1ère Bac.",
            "detail": "L'étude porte sur le conflit entre Antigone et Créon, la loi, le devoir, la liberté et les procédés du dialogue argumentatif.",
            "example": "Pour analyser une scène, on présente la situation, les personnages, l'opposition d'idées et l'effet produit.",
            "advanced": "Une lecture avancée relie le registre tragique, l'argumentation et la portée morale du conflit.",
            "summary": ["Identifier les personnages.", "Expliquer le conflit central.", "Justifier avec le texte.", "Relier le passage aux thèmes de l'oeuvre."],
        },
        "boite_merveilles": {
            "label": "La Boîte à merveilles",
            "definition": "La Boîte à merveilles est un roman autobiographique d'Ahmed Sefrioui.",
            "detail": "Le narrateur Sidi Mohammed raconte ses souvenirs d'enfance, sa famille, ses voisins et la société traditionnelle qui l'entoure.",
            "example": "Une réponse sur un personnage doit préciser son rôle dans la famille ou le quartier, puis citer un indice du passage.",
            "advanced": "Une lecture avancée analyse la mémoire, la solitude, le regard de l'enfant et la valeur culturelle des scènes.",
            "summary": ["Sidi Mohammed est le narrateur.", "L'oeuvre met en scène l'enfance et la tradition.", "Les personnages éclairent la société.", "La justification doit venir du texte."],
        },
        "dernier_jour": {
            "label": "Le Dernier Jour d'un condamné",
            "definition": "Le Dernier Jour d'un condamné est un roman à thèse de Victor Hugo contre la peine de mort.",
            "detail": "Le texte fait entendre la voix du condamné et insiste sur la peur, l'attente, la solitude et la dénonciation de la peine capitale.",
            "example": "Pour répondre, on peut montrer comment la première personne rapproche le lecteur de la souffrance du condamné.",
            "advanced": "Une lecture avancée distingue la thèse, les procédés pathétiques et la stratégie argumentative.",
            "summary": ["L'oeuvre dénonce la peine de mort.", "La première personne crée l'émotion.", "Les champs lexicaux renforcent l'angoisse.", "La réponse doit expliquer la thèse."],
        },
        "figures_style": {
            "label": "les figures de style",
            "definition": "Une figure de style est un procédé d'écriture qui produit un effet sur le lecteur.",
            "detail": "Au régional, il faut nommer la figure, montrer l'indice qui permet de la reconnaître et expliquer son effet dans le passage.",
            "example": "Dans une personnification, un objet ou une idée reçoit une action humaine, ce qui rend l'image plus vivante.",
            "advanced": "Une réponse avancée relie la figure à l'interprétation du passage et au thème étudié.",
            "summary": ["Nommer la figure.", "Citer l'indice.", "Expliquer l'effet.", "Relier au sens du texte."],
        },
        "production_ecrite": {
            "label": "la production écrite",
            "definition": "La production écrite est une réponse rédigée et organisée à un sujet.",
            "detail": "Elle doit contenir une introduction, des arguments développés, des exemples, des connecteurs et une conclusion claire.",
            "example": "Pour défendre une opinion, on annonce l'idée, on donne un argument, puis on ajoute un exemple précis.",
            "advanced": "Une rédaction avancée soigne la progression argumentative, la nuance et la correction de la langue.",
            "summary": ["Analyser le sujet.", "Construire un plan.", "Développer les arguments.", "Relire la langue."],
        },
        "langue": {
            "label": "la langue",
            "definition": "La langue regroupe les notions de grammaire, vocabulaire et conjugaison utiles pour comprendre un texte.",
            "detail": "Les questions de langue demandent de répondre selon le contexte : champ lexical, temps verbal, discours rapporté, synonyme ou antonyme.",
            "example": "Un champ lexical de la peur regroupe des mots qui renvoient à l'angoisse, au danger ou à l'inquiétude.",
            "advanced": "Une bonne réponse explique la valeur de la forme relevée et son rôle dans le passage.",
            "summary": ["Lire le contexte.", "Identifier la notion.", "Répondre précisément.", "Justifier si nécessaire."],
        },
        "methodologie": {
            "label": "la méthodologie du régional",
            "definition": "La méthodologie du régional est une démarche pour lire, répondre, justifier et relire efficacement.",
            "detail": "Elle commence par le paratexte et la consigne, puis passe par la recherche d'indices, la formulation de la réponse et la relecture.",
            "example": "Si la consigne dit 'justifiez', la réponse doit contenir une idée et un indice précis du texte.",
            "advanced": "Une méthode solide évite le hors sujet, améliore la gestion du temps et renforce la précision des réponses.",
            "summary": ["Lire la consigne.", "Repérer les indices.", "Répondre clairement.", "Relire avant de valider."],
        },
        "general": {
            "label": "le point de français demandé",
            "definition": "Le point demandé correspond à une notion ou un passage du programme de français de 1ère Bac.",
            "detail": "Le chatbot recherche les passages français pertinents, reformule les informations et propose une aide adaptée au niveau de l'élève.",
            "example": "Pour une question sur une oeuvre, il faut identifier l'oeuvre, le personnage ou la notion, puis justifier avec le support.",
            "advanced": "La réponse reste limitée aux sources françaises disponibles et ne doit pas inventer d'informations absentes du corpus.",
            "summary": ["Réponse centrée sur le français.", "Appui sur les supports disponibles.", "Justification par les sources.", "Entraînement lié au régional."],
        },
    }
    return profiles.get(topic, profiles["general"])

def _definition_for_level(topic: str, profile: dict, level: str) -> str:
    if level == "avance":
        return f"{profile['definition']} Dans un contexte avancÃ©, il faut aussi considÃ©rer ses hypothÃ¨ses, ses limites et la maniÃ¨re dont il est Ã©valuÃ©."
    return profile["definition"]


def _explanation_for_level(topic: str, profile: dict, level: str) -> str:
    if level == "debutant":
        return f"{profile['detail']} L'idÃ©e importante est de comprendre le principe gÃ©nÃ©ral avant les dÃ©tails techniques."
    if level == "avance":
        return f"{profile['detail']} {profile['advanced']}"
    return profile["detail"]


def _example_for_level(topic: str, profile: dict, level: str) -> str:
    if level == "debutant":
        return f"Exemple simple : {profile['example']}"
    if level == "avance":
        return f"Exemple technique : {profile['example']} On peut ensuite analyser la qualitÃ© du rÃ©sultat avec des critÃ¨res comme la pertinence, la couverture et les erreurs possibles."
    return profile["example"]


def _summary_for_level(profile: dict, level: str) -> list[str]:
    summary = list(profile["summary"])
    if level == "avance":
        summary.append("Il faut toujours vÃ©rifier les limites, les donnÃ©es utilisÃ©es et la qualitÃ© de l'Ã©valuation.")
    return summary[:5]


def _exercise_for_level(topic: str, level: str) -> str:
    label = _topic_profile(topic)["label"]

    if level == "debutant":
        return f"En une phrase, explique avec tes mots ce que signifie {label}, puis donne un exemple trÃ¨s simple."
    if level == "avance":
        return f"Analyse une limite possible de {label} dans EduMentor AI, puis propose une amÃ©lioration technique mesurable."
    return f"Donne un exemple d'utilisation de {label} dans une plateforme d'apprentissage, puis indique quel rÃ©sultat tu voudrais mesurer."


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
    preliminary_scope = french_chat_scope_service.classify_french_scope(current_message)
    pedagogical_profile = _student_pedagogical_profile(db, current_user) if db is not None and current_user is not None else []

    if intent == "out_of_scope" or (
        not preliminary_scope.in_scope
        and preliminary_scope.reason == "hard_out_of_scope_keyword"
    ):
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
            "scope": preliminary_scope.as_dict(),
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
    final_scope = french_chat_scope_service.classify_french_scope(
        current_message,
        relevant_results,
        threshold=max(float(threshold), french_chat_scope_service.RAG_RELEVANCE_THRESHOLD),
    )

    if not final_scope.in_scope:
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
            "scope": final_scope.as_dict(),
            "used_rag": False,
            "used_general_llm": False,
        }

    if relevant_results:
        factual_answer = _build_known_work_fact_answer(current_message, relevant_results)
        if factual_answer:
            mode = "rag_course" if resolved_course_id else "rag_subject" if resolved_subject_id else "rag_semantic"
            _log_chat_request(request_id, current_user, current_message, intent, len(relevant_results), mode)
            return _clean_chat_payload({
                "answer": factual_answer,
                "sources": _format_chat_sources(_sources_for_known_work_fact(current_message, relevant_results)),
                "mode": mode,
                "request_id": request_id,
                "client_message_id": client_message_id,
                "course_id": resolved_course_id,
                "subject_id": resolved_subject_id or relevant_results[0].get("subject_id"),
                "intent": intent,
                "confidence": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
                "relevance": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
                "scope": final_scope.as_dict(),
                "used_rag": True,
                "used_general_llm": False,
                "fallback_reason": None,
            })
        mode = "rag_course" if resolved_course_id else "rag_subject" if resolved_subject_id else "rag_semantic"
        _log_chat_request(request_id, current_user, current_message, intent, len(relevant_results), mode)
        return _clean_chat_payload({
            "answer": _build_french_rag_answer(current_message, level, relevant_results, intent, pedagogical_profile),
            "sources": _format_chat_sources(relevant_results),
            "mode": mode,
            "request_id": request_id,
            "client_message_id": client_message_id,
            "course_id": resolved_course_id,
            "subject_id": resolved_subject_id or relevant_results[0].get("subject_id"),
            "intent": intent,
            "confidence": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
            "relevance": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
            "scope": final_scope.as_dict(),
            "used_rag": True,
            "used_general_llm": False,
            "fallback_reason": None,
        })

    if _is_french_bac_related_question(current_message):
        factual_answer = _build_known_work_fact_answer(current_message, [])
        if factual_answer:
            _log_chat_request(request_id, current_user, current_message, intent, 0, "french_fact")
            return _clean_chat_payload({
                "answer": factual_answer,
                "sources": [],
                "mode": "french_fact",
                "request_id": request_id,
                "client_message_id": client_message_id,
                "label": "Réponse basée sur les supports",
                "course_id": resolved_course_id or course_id,
                "subject_id": resolved_subject_id or subject_id,
                "intent": intent,
                "confidence": 0,
                "relevance": 0,
                "scope": final_scope.as_dict(),
                "used_rag": False,
                "used_general_llm": False,
                "fallback_reason": "known_work_metadata",
            })
        _log_chat_request(request_id, current_user, current_message, intent, 0, "general_french")
        return _clean_chat_payload({
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
            "scope": final_scope.as_dict(),
            "used_rag": False,
            "used_general_llm": True,
            "fallback_reason": "not_found_in_french_supports",
        })

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
                Subject.name.ilike("%franÃ§ais%"),
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
    return any(term in searchable for term in ("francais", "franÃ§ais", "regional", "bac", "antigone", "sefrioui", "victor hugo"))


def _student_pedagogical_profile(db: Session, current_user: UserProfile) -> list[dict]:
    try:
        prediction = student_weakness_model_service.predict_student_weaknesses(db, current_user)
    except Exception:
        return []

    competencies = prediction.get("competencies") if isinstance(prediction, dict) else []
    if not isinstance(competencies, list):
        return []

    allowed = {"ComprÃ©hension", "Langue", "Figures de style", "Production Ã©crite", "MÃ©thodologie"}
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
    scope = french_chat_scope_service.classify_french_scope(message)
    if _is_old_ai_topic(message) or (
        not scope.in_scope
        and scope.reason == "hard_out_of_scope_keyword"
    ):
        return "out_of_scope"
    normalized = _normalize_text(message)
    if any(term in normalized for term in ("point faible", "points faibles", "competence la plus faible", "fais moi travailler", "entrainement cible", "reviser mes difficultes")):
        return "targeted_practice"
    if any(term in normalized for term in ("corrige", "correction", "ma reponse", "ma rÃ©ponse", "ameliore ma reponse", "note ma reponse")):
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
    if any(term in normalized for term in ("resume", "rÃ©sume", "explique", "passage", "personnage", "personnages", "antigone", "creon", "crÃ©on", "boite a merveilles", "boÃ®te Ã  merveilles", "sidi mohamed", "sefrioui", "dernier jour", "condamne", "victor hugo", "jean anouilh")):
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
    scope = french_chat_scope_service.classify_french_scope(message)
    return scope.in_scope or bool(scope.detected_works or scope.detected_intents)
    normalized = _normalize_text(message)
    french_terms = {
        "francais",
        "franÃ§ais",
        "1ere bac",
        "premiere bac",
        "regional",
        "examen",
        "antigone",
        "creon",
        "boite a merveilles",
        "boÃ®te Ã  merveilles",
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
    competence = target.get("competence") or "ComprÃ©hension"
    recommendation = target.get("recommendation") or "Relisez attentivement la consigne puis justifiez votre reponse avec un indice du texte."
    if competence == "Langue":
        exercise = "Transformez cette phrase au discours indirect : Le professeur dit : \"Relisez le passage avant de repondre.\""
    elif competence == "Figures de style":
        exercise = "Identifiez la figure de style dans : \"La ville dormait sous un ciel lourd\", puis expliquez son effet."
    elif competence == "Production Ã©crite":
        exercise = "Redigez une introduction courte sur le theme de la solidarite en annonÃ§ant clairement votre point de vue."
    elif competence == "MÃ©thodologie":
        exercise = "Lisez une consigne d'examen, soulignez le verbe de consigne, puis indiquez le type de rÃ©ponse attendu."
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
        return {"competence": "ComprÃ©hension", "status": "non evalue", "score_percentage": None}
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
            facts[0] if facts else "Votre rÃ©ponse contient une piste utile, mais elle doit Ãªtre vÃ©rifiÃ©e avec le texte.",
            "### Ce qui doit Ãªtre amÃ©liorÃ©",
            "Ajoutez un indice prÃ©cis du passage et reliez-le clairement Ã  lâ€™Å“uvre ou Ã  la consigne.",
            "### Proposition corrigÃ©e",
            "Formulez une rÃ©ponse courte, puis justifiez-la par un Ã©lÃ©ment observÃ© dans le texte.",
            "### Conseil",
            profile_tip or "Pour progresser, commencez toujours par repÃ©rer les mots de la consigne.",
        ])
    if intent == "figure_of_style":
        return "\n\n".join([
            "### Figure",
            facts[0] if facts else "La figure doit Ãªtre identifiÃ©e Ã  partir des mots exacts de la phrase.",
            "### Indice dans la phrase",
            "RepÃ©rez le rapprochement, lâ€™exagÃ©ration ou le fait quâ€™un objet reÃ§oit une action humaine.",
            "### Effet recherchÃ©",
            "Expliquez ce que cette image ajoute au sens du passage.",
        ])
    if intent == "writing_assistance":
        return "\n\n".join([
            "### ComprÃ©hension du sujet",
            f"Le sujet demande de traiter clairement le thÃ¨me liÃ© Ã  {topic}.",
            "### ProblÃ©matique",
            "Transformez le thÃ¨me en une question simple : pourquoi cette valeur est-elle importante et comment apparaÃ®t-elle dans la vie quotidienne ou dans une Å“uvre ",
            "### Plan proposÃ©",
            "- Introduction courte avec le thÃ¨me et la problÃ©matique\n- Deux arguments organisÃ©s\n- Conclusion qui reprend lâ€™idÃ©e principale",
            "### Exemple dâ€™introduction",
            "La solidaritÃ© est une valeur essentielle, car elle aide les personnes Ã  affronter les difficultÃ©s ensemble. On peut donc se demander comment elle renforce les liens entre les individus.",
            "### Arguments possibles",
            "\n".join(f"- {fact}" for fact in (facts[:3] or ["Appuyez chaque argument sur un exemple clair."])),
            "### Conseils de rÃ©daction",
            profile_tip or "Utilisez des connecteurs logiques et Ã©vitez les phrases trop longues.",
        ])
    if intent in {"methodology_help", "regional_exam"}:
        return "\n\n".join([
            "### MÃ©thode",
            "Situer un passage consiste Ã  prÃ©senter rapidement lâ€™Å“uvre, le moment de lâ€™histoire et lâ€™Ã©vÃ©nement qui entoure lâ€™extrait.",
            "### Ã‰tapes",
            "- Nommer lâ€™Å“uvre et lâ€™auteur si la question le demande.\n- Dire ce qui se passe juste avant le passage.\n- Identifier les personnages prÃ©sents ou concernÃ©s.\n- Relier le passage Ã  lâ€™Ã©vÃ©nement principal ou au thÃ¨me dominant.",
            "### Exemple de formulation",
            "Ce passage se situe aprÃ¨s un Ã©vÃ©nement important du rÃ©cit. Il met en scÃ¨ne un personnage dans une situation prÃ©cise et permet de comprendre la suite de lâ€™action.",
            "### Erreurs Ã  Ã©viter",
            "- Recopier tout le texte support.\n- Donner une rÃ©ponse vague sans Ã©vÃ©nement prÃ©cÃ©dent.\n- Inventer un chapitre, une page ou une citation absente du document.",
        ])
    if intent == "work_explanation":
        return _build_work_explanation_answer(message, results, facts, profile_tip)
    if intent == "language_help":
        return _build_language_help_answer(message, results, facts, profile_tip)
    return "\n\n".join([
        "### RÃ©ponse",
        facts[0] if facts else f"La question porte sur {topic}.",
        "### Explication",
        " ".join(facts[:4]) if facts else "Les supports disponibles donnent des Ã©lÃ©ments proches, mais pas assez de dÃ©tails pour affirmer une information prÃ©cise.",
        "### Ã€ retenir",
        "\n".join(f"- {item}" for item in (facts[:3] or ["VÃ©rifier lâ€™information dans le support du cours.", "Justifier avec un indice du texte.", "Adapter la rÃ©ponse Ã  la consigne."])),
        "### Petit exercice",
        profile_tip or "Expliquez lâ€™idÃ©e principale en deux phrases, puis ajoutez un exemple du texte.",
    ])



def _build_work_explanation_answer(
    message: str,
    results: list[dict],
    facts: list[str],
    profile_tip: str,
) -> str:
    normalized = _normalize_text(message)
    target_work = _target_work_name(message) or _french_topic(message, results)
    content = "\n".join(_result_text(result) for result in results)

    if "personnage" in normalized:
        characters = _extract_work_characters(content)
        principals = characters.get("principaux", [])
        secondaries = characters.get("secondaires", [])
        if principals or secondaries:
            sections = [
                "### Personnages principaux",
                "\n".join(f"- {item}" for item in principals) if principals else "Le support consultÃ© ne distingue pas clairement les personnages principaux.",
            ]
            if secondaries:
                sections.extend([
                    "### Personnages secondaires",
                    "\n".join(f"- {item}" for item in secondaries),
                ])
            sections.extend([
                "### Ã€ retenir",
                f"Pour prÃ©senter les personnages de **{target_work}**, indiquez leur nom, leur lien avec le personnage principal et leur rÃ´le dans lâ€™histoire.",
                "### Petit exercice",
                "Classez les personnages suivants en deux catÃ©gories : principaux et secondaires.",
            ])
            return "\n\n".join(sections)

    if any(term in normalized for term in ("structure", "chapitre", "organisation")):
        structure_items = _extract_bulleted_items_after_heading(content, ("structure de l oeuvre", "chapitres", "schema narratif"), limit=12)
        if structure_items:
            return "\n\n".join([
                "### Structure de lâ€™Å“uvre",
                "\n".join(f"- {item}" for item in structure_items),
                "### Ã€ retenir",
                "Reliez chaque partie de lâ€™Å“uvre aux Ã©vÃ©nements principaux et Ã  lâ€™Ã©volution des personnages.",
            ])

    if any(term in normalized for term in ("presente", "prÃ©sente", "presentation", "auteur", "genre")):
        clean_facts = [item for item in facts if item][:5]
        return "\n\n".join([
            f"### PrÃ©sentation de {target_work}",
            "\n".join(f"- {item}" for item in clean_facts) if clean_facts else "Les supports retrouvÃ©s ne contiennent pas assez dâ€™Ã©lÃ©ments prÃ©cis pour une prÃ©sentation complÃ¨te.",
            "### Ã€ retenir",
            "Une prÃ©sentation efficace mentionne lâ€™auteur, le genre, la date de publication et les principaux Ã©lÃ©ments de lâ€™Å“uvre.",
        ])

    clean_facts = [item for item in facts if item][:5]
    return "\n\n".join([
        f"### RÃ©ponse â€” {target_work}",
        clean_facts[0] if clean_facts else "Le support retrouvÃ© concerne bien cette Å“uvre, mais il ne contient pas assez de dÃ©tails pour rÃ©pondre avec prÃ©cision.",
        "### Explication",
        " ".join(clean_facts[1:]) if len(clean_facts) > 1 else "Consultez la fiche de lecture de lâ€™Å“uvre et repÃ©rez les personnages, les Ã©vÃ©nements et les thÃ¨mes liÃ©s Ã  la question.",
        "### Ã€ retenir",
        "Appuyez toujours votre rÃ©ponse sur un Ã©lÃ©ment prÃ©cis de la fiche ou du texte Ã©tudiÃ©.",
        "### Petit exercice",
        profile_tip or "RÃ©sumez lâ€™idÃ©e principale en deux phrases, puis citez un personnage ou un Ã©vÃ©nement associÃ©.",
    ])


def _extract_work_characters(text: str) -> dict[str, list[str]]:
    lines = [" ".join(line.split()).strip() for line in str(text or "").splitlines()]
    principals: list[str] = []
    secondaries: list[str] = []
    section = ""

    for line in lines:
        normalized = _normalize_text(line).strip(" :-")
        if not normalized:
            continue
        if "personnages principaux" in normalized:
            section = "principaux"
            continue
        if "personnages secondaires" in normalized:
            section = "secondaires"
            continue
        if section and any(marker in normalized for marker in ("la structure de l oeuvre", "chapitres thematique", "schema narratif", "resume de l oeuvre", "module 1")):
            section = ""
            continue
        if section and line.lstrip().startswith(("-", "?", "?")):
            item = re.sub(r"^[\s\-??]+", "", line).strip()
            if 3 <= len(item) <= 240:
                (principals if section == "principaux" else secondaries).append(item)

    # PDF extraction can flatten bullets or split names across lines. Recover only
    # characters whose names are explicitly present in the retrieved support text.
    normalized_text = _normalize_text(text)
    if "la boite a merveilles" in normalized_text:
        _append_known_characters(
            principals,
            normalized_text,
            (
                ("Mohammed", "le personnage principal, enfant de six ans"),
                ("Lalla Zoubida", "m\u00e8re de Mohammed"),
                ("Si Abdeslem", "p\u00e8re de Mohammed"),
            ),
        )
        _append_known_characters(
            secondaries,
            normalized_text,
            (
                ("Kenza", "la chouafa"),
                ("Rahma", "voisine de la famille"),
                ("Fatma Bziouya", "voisine"),
                ("Lalla A\u00efcha", "ancienne voisine et amie de la m\u00e8re de Mohammed"),
                ("Zineb", "fille de Rahma"),
                ("Salma", "marieuse professionnelle"),
                ("Driss El Aouad", "mari de Rahma"),
                ("Moulay Arbi", "mari de Lalla A\u00efcha"),
                ("Moulay Larbi", "mari de Lalla A\u00efcha"),
                ("Abdellah", "\u00e9picier et conteur"),
                ("Si Abderrahman", "coiffeur du p\u00e8re et de l'enfant"),
                ("Le fquih", "ma\u00eetre de l'\u00e9cole coranique"),
                ("Le fqih", "ma\u00eetre de l'\u00e9cole coranique"),
                ("Driss le teigneux", "apprenti du p\u00e8re"),
                ("Si El Arafi", "le voyant"),
                ("Si El Ara", "le voyant"),
            ),
        )

    return {
        "principaux": _unique_items(principals)[:8],
        "secondaires": _unique_items(secondaries)[:20],
    }


def _append_known_characters(target: list[str], normalized_text: str, characters: tuple[tuple[str, str], ...]) -> None:
    separator = "\u2014"
    existing = {_normalize_text(item).split(separator, 1)[0].split("-", 1)[0].strip() for item in target}
    for name, role in characters:
        normalized_name = _normalize_text(name)
        if normalized_name in normalized_text and normalized_name not in existing:
            target.append(f"{name} {separator} {role}.")
            existing.add(normalized_name)

def _extract_bulleted_items_after_heading(text: str, headings: tuple[str, ...], limit: int = 10) -> list[str]:
    lines = [" ".join(line.split()).strip() for line in str(text or "").splitlines()]
    active = False
    items: list[str] = []
    for line in lines:
        normalized = _normalize_text(line)
        if any(heading in normalized for heading in headings):
            active = True
            continue
        if active and line.lstrip().startswith(("-", "â€¢", "â€“")):
            item = re.sub(r"^[\s\-â€¢â€“]+", "", line).strip()
            if item:
                items.append(item)
                if len(items) >= limit:
                    break
        elif active and items and len(line) < 90 and not line[:1].isdigit():
            break
    return _unique_items(items)


def _target_work_name(message: str) -> str:
    normalized = _normalize_text(message)
    if "antigone" in normalized or "creon" in normalized:
        return "Antigone"
    if "boite a merveilles" in normalized or "sidi mohamed" in normalized or "sidi mohammed" in normalized or "sefrioui" in normalized:
        return "La BoÃ®te Ã  merveilles"
    if "dernier jour" in normalized or "condamne" in normalized or "victor hugo" in normalized:
        return "Le Dernier Jour dâ€™un condamnÃ©"
    return ""


def _work_matches(target_work: str, result: dict) -> bool:
    if not target_work:
        return True
    haystack = _normalize_text(" ".join([
        str(result.get("work") or ""),
        str(result.get("chapter_title") or ""),
        str(result.get("display_source") or ""),
        _result_text(result),
    ]))
    target = _normalize_text(target_work)
    target_tokens = {token for token in re.findall(r"[a-z0-9]+", target) if len(token) >= 4}
    return target in haystack or (target_tokens and sum(token in haystack for token in target_tokens) >= min(2, len(target_tokens)))


def _result_text(result: dict) -> str:
    return str(result.get("content") or result.get("text") or result.get("text_preview") or result.get("excerpt") or "")

def _build_language_help_answer(
    message: str,
    results: list[dict],
    facts: list[str],
    profile_tip: str,
) -> str:
    normalized = _normalize_text(message)
    combined = " ".join(_result_text(result) for result in results)

    if "champ" in normalized and "lexical" in normalized:
        definition = _find_supported_sentence(
            combined,
            (r"un champ lexical est[^.!]*[.!]", r"le champ lexical[^.!]*(:ensemble|mots)[^.!]*[.!]"),
        )
        if not definition:
            definition = "Un champ lexical est un ensemble de mots lies a une meme idee, une meme realite ou un meme domaine."
        example = _extract_field_example(combined)
        return "\n\n".join([
            "### Réponse",
            definition,
            "### Comment le reconnaître ",
            "Reperez plusieurs mots qui se rapportent au meme theme. Ils peuvent etre des synonymes, appartenir a la meme famille ou au meme domaine.",
            "### Exemple",
            example or "Dans le champ lexical du sommeil, on peut relever : sommeil, se reveiller et se recoucher.",
            "### À retenir",
            "Un seul mot ne suffit pas : il faut relever plusieurs termes lies au meme theme, puis expliquer ce qu'ils revelent dans le texte.",
            "### Petit exercice",
            profile_tip or "Relevez trois mots appartenant au champ lexical de la peur dans un court passage.",
        ])

    if "discours direct" in normalized or "discours indirect" in normalized:
        return "\n\n".join([
            "### RÃ©ponse",
            facts[0] if facts else "Le discours direct rapporte les paroles telles quâ€™elles sont prononcÃ©es, tandis que le discours indirect les intÃ¨gre dans la phrase du narrateur.",
            "### Indices",
            "Le discours direct utilise gÃ©nÃ©ralement les deux-points, les guillemets ou les tirets. Le discours indirect utilise un verbe introducteur suivi de Â« que Â», Â« si Â» ou dâ€™un mot interrogatif.",
            "### Ã€ retenir",
            "Le passage au discours indirect peut entraÃ®ner des changements de pronoms, de temps verbaux et dâ€™indications de temps ou de lieu.",
            "### Petit exercice",
            "Transformez au discours indirect : Il dÃ©clara : Â« Je viendrai demain. Â»",
        ])

    clean_facts = facts[:3]
    return "\n\n".join([
        "### RÃ©ponse",
        clean_facts[0] if clean_facts else "La notion doit Ãªtre dÃ©finie Ã  partir du cours sÃ©lectionnÃ©.",
        "### Explication",
        " ".join(clean_facts[1:]) if len(clean_facts) > 1 else "RepÃ©rez la rÃ¨gle, puis appliquez-la Ã  un exemple court.",
        "### Ã€ retenir",
        "Identifiez dâ€™abord la notion demandÃ©e, puis justifiez votre rÃ©ponse avec un indice prÃ©cis.",
        "### Petit exercice",
        profile_tip or "Donnez un exemple personnel qui applique cette rÃ¨gle de langue.",
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
        return "Dans le texte de lâ€™Achoura, Â« sommeil Â», Â« se rÃ©veiller Â» et Â« se recoucher Â» appartiennent au champ lexical du sommeil."
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
        text = _normalize_text(_result_text(result))
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
    if intent == "work_explanation":
        work_types = {"work_sheet", "work_summary", "work_structure", "work_characters"}
        target_work = _target_work_name(message)
        work_results = [
            item for item in ordered
            if str(item.get("document_type") or "").lower() in work_types
            and (not target_work or _work_matches(target_work, item))
        ]
        if work_results:
            if _is_long_list_question(message):
                return work_results[:5]
            complementary = [item for item in ordered if item not in work_results and _work_matches(target_work, item)]
            return (work_results[:2] + complementary[:1])[:3]
    return ordered[:3]


def _result_matches_query_terms(message: str, result: dict) -> bool:
    query_terms = {term for term in re.findall(r"[a-z0-9]+", _normalize_text(message)) if len(term) >= 4}
    text = _normalize_text(" ".join([
        str(result.get("chapter_title") or ""),
        _result_text(result),
    ]))
    return bool(query_terms) and sum(1 for term in query_terms if term in text) >= min(2, len(query_terms))


def _is_long_list_question(message: str) -> bool:
    normalized = _normalize_text(message)
    return any(
        phrase in normalized
        for phrase in (
            "quels sont les personnages",
            "personnages principaux",
            "personnages secondaires",
            "liste des personnages",
            "donne la liste",
            "cite tous",
            "presente les personnages",
            "structure complete",
            "resume des chapitres",
            "liste complete",
            "tous les elements",
        )
    )


def _french_topic(message: str, results: list[dict]) -> str:
    normalized = _normalize_text(message)
    if "antigone" in normalized or "creon" in normalized:
        return "Antigone"
    if "boite" in normalized or "sidi mohamed" in normalized:
        return "La BoÃ®te Ã  merveilles"
    if "dernier jour" in normalized or "condamne" in normalized:
        return "Le Dernier Jour d'un condamne"
    if results:
        title = results[0].get("chapter_title") or results[0].get("course_title") or results[0].get("course_name")
        if title:
            return str(title)
    return "le franÃ§ais de 1Ã¨re Bac"


def _profile_tip_for_message(message: str, pedagogical_profile: list[dict]) -> str:
    if not pedagogical_profile:
        return ""
    target = _weakest_competence(pedagogical_profile)
    competence = target.get("competence")
    if not competence:
        return ""
    return f"Pour renforcer votre compÃ©tence en {competence.lower()}, avancez par Ã©tapes et justifiez chaque rÃ©ponse avec un indice clair."



def _build_known_work_fact_answer(message: str, results: list[dict]) -> str:
    work_key = _target_work_key(message) or _target_work_key(" ".join(
        str(result.get("work") or result.get("chapter_title") or result.get("display_source") or "")
        for result in results
    ))
    if not work_key:
        return ""
    field = _target_fact_field(message)
    if not field:
        return ""
    facts = WORK_FACTS[work_key]
    title = facts["title"]
    if field == "author":
        return (
            f"### R\u00e9ponse\n\n"
            f"**{title}** a \u00e9t\u00e9 \u00e9crite par **{facts['author']}**.\n\n"
            f"### \u00c0 retenir\n\n"
            f"Pour une question d\u2019examen, r\u00e9pondez directement avec le nom de l\u2019auteur : **{facts['author']}**."
        )
    if field == "genre":
        return (
            f"### R\u00e9ponse\n\n"
            f"**{title}** appartient au genre : **{facts['genre']}**.\n\n"
            "### \u00c0 retenir\n\n"
            "Donnez le genre, puis ajoutez une courte justification si la consigne le demande."
        )
    if field == "date" and facts.get("date"):
        return (
            f"### R\u00e9ponse\n\n"
            f"Pour **{title}**, la date \u00e0 retenir dans le programme est **{facts['date']}**.\n\n"
            "### \u00c0 retenir\n\n"
            "Ne donnez une date que si elle est demand\u00e9e explicitement par la consigne."
        )
    return ""


def _target_fact_field(message: str) -> str:
    normalized = _normalize_text(message)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    if any(term in normalized for term in ("auteur", "ecrivain", "qui a ecrit", "qui est l auteur", "ki ecrit")):
        return "author"
    if "genre" in normalized:
        return "genre"
    if any(term in normalized for term in ("date", "publication", "representation", "redaction")):
        return "date"
    return ""


def _target_work_key(text: str) -> str:
    normalized = _normalize_text(text)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    if "antigone" in normalized or "creon" in normalized or "anouilh" in normalized:
        return "antigone"
    if "boite a merveilles" in normalized or "sidi mohamed" in normalized or "sidi mohammed" in normalized or "sefrioui" in normalized:
        return "la_boite_a_merveilles"
    if "dernier jour" in normalized or "condamne" in normalized or "hugo" in normalized:
        return "dernier_jour_condamne"
    return ""


def _sources_for_known_work_fact(message: str, results: list[dict]) -> list[dict]:
    work_key = _target_work_key(message)
    if not work_key:
        return results[:2]
    facts = WORK_FACTS[work_key]
    work = facts["title"]
    field = _target_fact_field(message)
    expected_terms = [facts["author"]] if field == "author" else [facts["genre"]] if field == "genre" else [str(facts.get("date") or "")]
    matching = [result for result in results if _work_matches(work, result)]
    grounded = [
        result for result in matching
        if all(_normalize_text(term) in _normalize_text(" ".join([
            _result_text(result),
            str(result.get("excerpt") or ""),
            str(result.get("work") or ""),
            str(result.get("display_source") or ""),
        ])) for term in expected_terms if term)
    ]
    if grounded:
        return grounded[:2]
    return [{
        "chunk_id": f"known-fact-{work_key}",
        "file_name": facts["source"],
        "pdf_name": facts["source"],
        "display_source": facts["source"],
        "source_label": facts["source"],
        "work": work,
        "document_type": "work_sheet",
        "page_number": _page_from_source_label(facts["source"]),
        "page_start": _page_from_source_label(facts["source"]),
        "page_end": _page_from_source_label(facts["source"]),
        "score": 1.0,
    }]


def _page_from_source_label(label: str) -> int | None:
    match = re.search(r"p\.\s*(\d+)", label or "")
    return int(match.group(1)) if match else None


def _extract_french_facts(message: str, results: list[dict]) -> list[str]:
    facts = _sentences_from_results(results)
    normalized_message = _normalize_text(message)
    all_text = " ".join(_result_text(result) for result in results)
    normalized_text = _normalize_text(all_text)
    priority: list[str] = []
    if "auteur" in normalized_message and "jean anouilh" in normalized_text:
        priority.append("L'auteur d'Antigone est Jean Anouilh.")
    if "auteur" in normalized_message and "victor hugo" in normalized_text:
        priority.append("L'auteur du Dernier Jour d'un condamn? est Victor Hugo.")
    if "genre" in normalized_message and "tragedie moderne" in normalized_text:
        priority.append("Antigone est une trag?die moderne.")
    if "genre" in normalized_message and "roman autobiographique" in normalized_text:
        priority.append("La Bo?te ? merveilles est un roman autobiographique.")
    if "auteur" in normalized_message and "ahmed sefrioui" in normalized_text:
        priority.append("L'auteur de La BoÃ®te Ã  merveilles est Ahmed Sefrioui.")
    if "personnification" in normalized_text and ("djellaba" in normalized_message or "dormait" in normalized_message):
        priority.append("Dans l'expression la djellaba dormait, l'objet reÃ§oit une action humaine : c'est une personnification.")
    if "narrateur externe" in normalized_message and "sidi mohamed" in normalized_text:
        priority.append("Sidi Mohamed n'est pas un narrateur externe : dans La Boite a merveilles, il raconte son experience d'enfant a la premiere personne.")
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
            f"# DÃ©finition simple\n\n{_simple_definition(topic, key_facts, normalized_level)}",
            f"# Explication dÃ©taillÃ©e\n\n{explanation}",
            f"# Exemple concret\n\n{example}",
            "# RÃ©sumÃ©\n\n" + "\n".join(f"- {item}" for item in summary[:5]),
            f"# Mini exercice\n\n{exercise}",
            "# Sources utilisÃ©es\n\n" + "\n".join(sources),
        ]
    )


def _human_topic(message: str, results: list[dict]) -> str:
    normalized = _normalize_text(message)
    if "antigone" in normalized:
        return "Antigone"
    if "boite a merveilles" in normalized or "boÃ®te Ã  merveilles" in normalized:
        return "La BoÃ®te Ã  merveilles"
    if "dernier jour" in normalized or "condamne" in normalized or "condamnÃ©" in normalized:
        return "Le Dernier Jour d'un condamnÃ©"
    if "figure" in normalized or "metaphore" in normalized or "mÃ©taphore" in normalized or "comparaison" in normalized:
        return "les figures de style"
    if "production" in normalized or "redaction" in normalized or "rÃ©daction" in normalized:
        return "la production Ã©crite"
    if "langue" in normalized or "grammaire" in normalized or "vocabulaire" in normalized:
        return "la langue"
    if "methodologie" in normalized or "mÃ©thodologie" in normalized or "regional" in normalized or "rÃ©gional" in normalized:
        return "la mÃ©thodologie du rÃ©gional"
    if results:
        title = results[0].get("chapter_title") or results[0].get("course_title") or results[0].get("course_name")
        if title:
            return str(title)
    return "la notion demandee"


def _extract_key_facts(message: str, results: list[dict]) -> list[str]:
    text = " ".join(_result_text(result) for result in results)
    normalized = _normalize_text(f"{message} {text}")
    facts: list[str] = []
    if "antigone" in normalized:
        facts.extend([
            "Antigone est une tragÃ©die moderne de Jean Anouilh.",
            "Le conflit central oppose Antigone Ã  CrÃ©on autour de la loi, du devoir et de la libertÃ©.",
            "Une bonne rÃ©ponse doit expliquer les valeurs dÃ©fendues par chaque personnage.",
        ])
    if "boite a merveilles" in normalized or "boÃ®te Ã  merveilles" in normalized:
        facts.extend([
            "La BoÃ®te Ã  merveilles est un roman autobiographique d'Ahmed Sefrioui.",
            "Sidi Mohammed raconte ses souvenirs d'enfance Ã  la premiÃ¨re personne.",
            "Les personnages et les lieux permettent de comprendre la sociÃ©tÃ© traditionnelle Ã©voquÃ©e.",
        ])
    if "dernier jour" in normalized or "condamne" in normalized or "condamnÃ©" in normalized:
        facts.extend([
            "Le Dernier Jour d'un condamnÃ© est un roman Ã  thÃ¨se de Victor Hugo.",
            "L'oeuvre dÃ©nonce la peine de mort Ã  travers la voix du condamnÃ©.",
            "La premiÃ¨re personne rapproche le lecteur de la peur et de la solitude du personnage.",
        ])
    if "figure" in normalized or "metaphore" in normalized or "mÃ©taphore" in normalized or "comparaison" in normalized:
        facts.extend([
            "Une figure de style doit Ãªtre nommÃ©e puis expliquÃ©e par son effet dans le passage.",
            "La comparaison utilise souvent un outil comparatif, contrairement Ã  la mÃ©taphore.",
        ])
    if ("methodologie" in normalized or "mÃ©thodologie" in normalized or "regional" in normalized or "rÃ©gional" in normalized) and not facts:
        facts.extend([
            "La mÃ©thode du rÃ©gional consiste Ã  lire la consigne, repÃ©rer les indices, rÃ©pondre clairement puis justifier.",
            "Les cinq compÃ©tences suivies sont la comprÃ©hension, la langue, les figures de style, la production Ã©crite et la mÃ©thodologie.",
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
    if "antigone" in normalized_topic:
        return "Si la question porte sur le conflit, on peut rÃ©pondre qu'Antigone dÃ©fend son devoir familial tandis que CrÃ©on dÃ©fend l'ordre de la citÃ©, puis justifier avec le passage."
    if "boite" in normalized_topic:
        return "Pour prÃ©senter Sidi Mohammed, on prÃ©cise qu'il raconte ses souvenirs d'enfant et qu'il observe son entourage avec sensibilitÃ©."
    if "dernier jour" in normalized_topic or "condamne" in normalized_topic:
        return "Pour expliquer la thÃ¨se, on montre que la peur du condamnÃ© sert Ã  faire rÃ©flÃ©chir le lecteur sur la violence de la peine de mort."
    if "figure" in normalized_topic:
        return "Dans une phrase comme 'la maison dormait', l'objet reÃ§oit une action humaine : c'est une personnification, et son effet est de rendre l'image plus vivante."
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
        return f"RÃ©digez un paragraphe argumentÃ© sur {topic}, avec une idÃ©e, une justification et une phrase de conclusion."
    if level == "debutant":
        return f"Expliquez {topic} avec vos propres mots en deux phrases, puis donnez un petit exemple."
    return f"Construisez une rÃ©ponse courte sur {topic}, puis ajoutez l'indice du texte qui permet de la justifier."


def _sentences_from_results(results: list[dict]) -> list[str]:
    sentences: list[str] = []
    blocked_prefixes = (
        "examen:",
        "oeuvre:",
        "question ",
        "competence:",
        "type:",
        "bareme:",
        "barÃ¨me:",
        "elements attendus:",
        "Ã©lÃ©ments attendus:",
        "correction officielle",
        "correction verifiee",
        "correction vÃ©rifiÃ©e",
        "source pedagogique complementaire:",
        "source pÃ©dagogique complÃ©mentaire:",
    )
    for result in results:
        text = _result_text(result)
        text = re.sub(r"Source pÃ©dagogique complÃ©mentaire\s*:[^.]*\.\s*Page\s+\d+\.\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"Source pedagogique complementaire\s*:[^.]*\.\s*Page\s+\d+\.\s*", "", text, flags=re.IGNORECASE)
        for part in re.split(r"(<=[.!])\s+|\n+", text):
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
    if clean and clean[-1] not in ".!":
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


def _format_chat_sources(results: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], dict] = {}
    for result in results:
        source = _format_chat_source(result)
        key = (
            str(result.get("source_name") or source.get("file_name") or ""),
            str(result.get("work") or source.get("work") or ""),
            str(result.get("document_type") or ""),
            str(result.get("document_id") or ""),
        )
        if key not in grouped:
            grouped[key] = source
            continue
        existing = grouped[key]
        pages = [
            value
            for value in (
                existing.get("page_start"),
                existing.get("page_end"),
                source.get("page_start"),
                source.get("page_end"),
            )
            if value
        ]
        if pages:
            existing["page_start"] = min(pages)
            existing["page_end"] = max(pages)
            existing["page_number"] = existing["page_start"]
        existing["display_source"] = _merged_source_label(result, existing)
        existing["source_label"] = existing["display_source"]
    return list(grouped.values())


def _merged_source_label(result: dict, source: dict) -> str:
    source_name = result.get("source_name")
    work = result.get("work")
    page_start = source.get("page_start")
    page_end = source.get("page_end") or page_start
    if source_name and work and page_start:
        page_label = f"p. {page_start}" if page_start == page_end else f"p. {page_start}–{page_end}"
        return f"{source_name} — {work}, {page_label}"
    return source.get("display_source") or source.get("source_label") or source.get("file_name") or "Source pédagogique"


def _format_chat_source(result: dict) -> dict:
    page_start = result.get("page_start") or result.get("page_number")
    page_end = result.get("page_end") or page_start
    display_source = _merged_source_label(result, {
        "display_source": result.get("display_source"),
        "source_label": result.get("source_label"),
        "file_name": result.get("file_name") or result.get("pdf_name"),
        "page_start": page_start,
        "page_end": page_end,
    }) if result.get("source_name") and result.get("work") else result.get("display_source") or result.get("source_label")
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
            "Ø´Ù†Ùˆ",
            "Ø§Ø´",
            "ÙˆØ§Ø´",
            "Ø¹Ù„Ø§Ø´",
            "ÙƒÙŠÙØ§Ø´",
            "Ø¨Ø²Ø§Ù",
            "Ø¯Ø§Ø¨Ø§",
            "Ù‡Ø§Ø¯",
            "Ø¯ÙŠØ§Ù„",
            "ÙØ§Ø´",
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
        "diffÃ©rence",
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
        "donnÃ©es",
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
        "Ø°ÙƒØ§Ø¡ Ø§ØµØ·Ù†Ø§Ø¹ÙŠ",
        "Ø§Ù„Ø°ÙƒØ§Ø¡ Ø§Ù„Ø§ØµØ·Ù†Ø§Ø¹ÙŠ",
        "ØªØ¹Ù„Ù… Ø§Ù„Ø§Ù„Ø©",
        "ØªØ¹Ù„Ù… Ø§Ù„Ø¢Ù„Ø©",
        "ØªØ¹Ù„Ù… Ø¹Ù…ÙŠÙ‚",
        "Ù†Ù…Ø§Ø°Ø¬ Ø§Ù„Ù„ØºØ©",
        "Ø´Ø§Øª Ø¨ÙˆØª",
        "Ø´Ø§ØªØ¨ÙˆÙ¹",
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
            token.strip(".,;:!()[]{}\"'")
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
        "RÃ©ponds Ã  la derniÃ¨re question utilisateur. Le contexte prÃ©cÃ©dent sert uniquement Ã  comprendre "
        "les rÃ©fÃ©rences ambiguÃ«s et ne doit pas remplacer la demande actuelle.\n"
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
        "Ã§a",
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
        "explique Ã§a",
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


def _clean_chat_payload(payload: dict) -> dict:
    if isinstance(payload.get("answer"), str):
        payload["answer"] = _repair_mojibake_text(payload["answer"])
    if isinstance(payload.get("label"), str):
        payload["label"] = _repair_mojibake_text(payload["label"])
    sources = payload.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key, value in list(source.items()):
                if isinstance(value, str):
                    source[key] = _repair_mojibake_text(value)
    return payload


def _repair_mojibake_text(text: str) -> str:
    cleaned = str(text or "")
    for _ in range(2):
        before = cleaned
        for source, target in MOJIBAKE_REPLACEMENTS.items():
            cleaned = cleaned.replace(source, target)
        if cleaned == before:
            break
    return cleaned

def _general_label(language: str) -> str:
    if language == "english":
        return "General answer"
    if language == "arabic":
        return "Ø¥Ø¬Ø§Ø¨Ø© Ø¹Ø§Ù…Ø©"
    return "RÃ©ponse gÃ©nÃ©rale"


def _social_answer(message: str) -> str | None:
    normalized = _normalize_social_text(message)
    compact = normalized.replace(" ", "")

    social_answers = {
        "bonjour": "Bonjour. Comment puis-je vous aider aujourd'hui ?",
        "bonsoir": "Bonsoir. Comment puis-je vous aider aujourd'hui ?",
        "salut": "Salut. Comment puis-je t'aider aujourd'hui ?",
        "hello": "Hello. How can I help you today?",
        "hi": "Hello. How can I help you today?",
        "hey": "Hello. How can I help you today?",
        "merci": "Avec plaisir.",
        "thanks": "You're welcome.",
        "thank you": "You're welcome.",
        "m7tajk": "Je suis là pour t'aider. Pose-moi ta question.",
        "mhtajk": "Je suis là pour t'aider. Pose-moi ta question.",
        "besoin d aide": "Je suis là pour vous aider. Posez-moi votre question.",
        "besoin daide": "Je suis là pour vous aider. Posez-moi votre question.",
        "need help": "I'm here to help. Ask me your question.",
        "help": "I'm here to help. Ask me your question.",
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
        return "Je suis là pour vous aider. Posez-moi votre question."

    return None


def _normalize_social_text(message: str) -> str:
    normalized = _normalize_text(message)
    for source in ("!", ".", ",", ";", ":", "'", "'", "-", "_", "?"):
        normalized = normalized.replace(source, " ")
    return " ".join(normalized.split())


def _out_of_scope_answer(language: str) -> str:
    if language == "english":
        return (
            "I am specialized in Moroccan 1st-year baccalaureate French regional exam preparation. "
            "Please ask me about a program work, a language exercise, a figure of speech, methodology, or written production."
        )
    return french_chat_scope_service.OUT_OF_SCOPE_MESSAGE_FR
