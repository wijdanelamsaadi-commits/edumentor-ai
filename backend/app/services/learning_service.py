from fastapi import HTTPException
import unicodedata

from app.rag.engine import rag_status
from app.rag.vector_store import semantic_search
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
    return {
        **course,
        "generated_lesson": (
            f"Ce cours est adapte au niveau {course['level'].lower()} avec resume, exemples "
            "et exercices, avec recherche documentaire disponible via le module RAG."
        ),
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
    return {
        "course_id": quiz["course_id"],
        "questions": [
            {"question": item["question"], "choices": item["choices"]} for item in quiz["questions"]
        ],
    }


def grade_quiz(course_id: int, answers: list[str]) -> dict:
    if course_id not in QUIZZES:
        raise HTTPException(status_code=404, detail="Quiz introuvable")

    questions = QUIZZES[course_id]["questions"]
    correct = sum(
        1 for index, question in enumerate(questions) if index < len(answers) and answers[index] == question["answer"]
    )
    score = round((correct / len(questions)) * 100)
    return {
        "score": score,
        "correct_answers": correct,
        "total_questions": len(questions),
        "recommendation": "Continuer le module suivant" if score >= 70 else "Revoir le resume et refaire les exercices",
    }


def rag_chat(message: str, level: str) -> dict:
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
        return ["Commencer par Python pour l IA", "Faire les exercices guides avant le quiz"]
    if level == "Avance":
        return ["Explorer le module RAG pedagogique", "Construire un mini-projet avec sources"]
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
        key = (result.get("file_name", ""), result.get("page_number"))
        if key in seen:
            continue
        seen.add(key)
        unique_sources.append(result)

    return [
        f"- {source.get('file_name')} — {source.get('course_name')} — page {source.get('page_number')}"
        for source in unique_sources
    ]


def _normalize_level(level: str) -> str:
    normalized = (
        level.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("à", "a")
        .replace("?", "e")
    )

    if "debut" in normalized or (normalized.startswith("d") and "butant" in normalized):
        return "debutant"
    if "avanc" in normalized:
        return "avance"
    return "intermediaire"


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(character for character in normalized if unicodedata.category(character) != "Mn")
