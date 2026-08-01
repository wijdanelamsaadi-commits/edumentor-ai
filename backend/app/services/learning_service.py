from fastapi import HTTPException
import unicodedata
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.persistence import Course
from app.rag.engine import rag_status
from app.rag.vector_store import semantic_search
from app.services import rag_document_service
from app.services.groq_service import generate_general_answer
from app.services.mock_data import COURSES, LEARNER, QUIZZES, RECOMMENDATIONS


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
    preferred_language: str | None = None,
) -> dict:
    social_answer = _social_answer(message)
    if social_answer:
        return {
            "answer": social_answer,
            "sources": [],
            "mode": "social",
            "used_rag": False,
            "used_general_llm": False,
        }

    contextual_message = _contextual_message(message, context or [])
    if db is not None:
        _validate_chat_scope(db, course_id, subject_id)
        results = rag_document_service.filtered_semantic_search(
            db,
            contextual_message,
            course_id=course_id,
            subject_id=subject_id,
            top_k=3,
            published_only=True,
        )
    else:
        results = semantic_search(contextual_message, limit=3)
    threshold = get_settings()["rag_score_threshold"]
    relevant_results = [result for result in results if float(result.get("score", 0)) >= threshold]

    if relevant_results:
        mode = "rag_course" if course_id else "rag_subject" if subject_id else "rag_semantic"
        return {
            "answer": _build_multi_course_rag_answer(contextual_message, level, relevant_results),
            "sources": [_format_chat_source(result) for result in relevant_results],
            "mode": mode,
            "course_id": course_id,
            "subject_id": subject_id or relevant_results[0].get("subject_id"),
            "confidence": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
            "relevance": round(max(float(result.get("score", 0)) for result in relevant_results), 4),
            "used_rag": True,
            "used_general_llm": False,
            "fallback_reason": None,
        }

    detected_language = preferred_language or _detect_language(message)
    if _is_education_related_question(contextual_message):
        return {
            "answer": generate_general_answer(contextual_message, detected_language, level),
            "sources": [],
            "mode": "general_education",
            "label": _general_label(detected_language),
            "course_id": course_id,
            "subject_id": subject_id,
            "confidence": 0,
            "relevance": 0,
            "used_rag": False,
            "used_general_llm": True,
            "fallback_reason": "not_found_in_selected_supports" if course_id or subject_id else "not_found_in_supports",
        }

    return {
    "answer": _out_of_scope_answer(detected_language),
        "sources": [],
        "mode": "out_of_scope",
        "course_id": course_id,
        "subject_id": subject_id,
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
    for result in results:
        text = str(result.get("text_preview") or result.get("excerpt") or "")
        for sentence in text.replace("\n", " ").split("."):
            clean = " ".join(sentence.split())
            if 40 <= len(clean) <= 220:
                sentences.append(clean + ".")
    return sentences[:5]


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
        "source_label": result.get("source_label"),
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
    return f"Contexte récent: {context_text}\nQuestion actuelle: {message}"


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
        "donne un exemple",
        "give an example",
    }
    return any(marker in normalized for marker in context_markers)


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
