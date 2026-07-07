LEARNER = {
    "id": 1,
    "name": "Wijdane Lamsadi",
    "email": "wijdane@edumentor.ai",
    "level": "Intermediaire",
    "goal": "Maitriser les bases de Python et progresser vers les projets IA",
    "progress": 41,
}

COURSES = [
    {
        "id": 1,
        "title": "Python pour l IA",
        "level": "Debutant",
        "duration": "2h30",
        "progress": 72,
        "summary": "Syntaxe Python, variables, fonctions et manipulation de donnees simples.",
        "examples": ["Fonction de moyenne", "Nettoyage d une liste de notes"],
        "exercises": ["Calculateur de score", "Statistiques sur reponses"],
    },
    {
        "id": 2,
        "title": "Fondamentaux Machine Learning",
        "level": "Intermediaire",
        "duration": "3h10",
        "progress": 38,
        "summary": "Jeux de donnees, entrainement, evaluation et prediction.",
        "examples": ["Prediction de niveau apprenant", "Classification par score"],
        "exercises": ["Matrice de confusion", "Comparaison de modeles simules"],
    },
    {
        "id": 3,
        "title": "RAG pedagogique",
        "level": "Avance",
        "duration": "2h45",
        "progress": 12,
        "summary": "Architecture de recherche documentaire pour assistant pedagogique.",
        "examples": ["Recherche dans un cours PDF", "Resume depuis un extrait"],
        "exercises": ["Pipeline RAG", "Reponse avec sources PDF"],
    },
]

QUIZZES = {
    1: {
        "course_id": 1,
        "questions": [
            {
                "question": "Une fonction Python permet de...",
                "choices": ["Reutiliser une action", "Changer le navigateur", "Creer une image uniquement"],
                "answer": "Reutiliser une action",
            },
            {
                "question": "Une liste sert a stocker...",
                "choices": ["Plusieurs valeurs", "Uniquement un mot de passe", "Une seule couleur"],
                "answer": "Plusieurs valeurs",
            },
        ],
    },
    2: {
        "course_id": 2,
        "questions": [
            {
                "question": "Un modele de classification sert a...",
                "choices": ["Predire une categorie", "Dessiner une page", "Supprimer les donnees"],
                "answer": "Predire une categorie",
            }
        ],
    },
    3: {
        "course_id": 3,
        "questions": [
            {
                "question": "Le RAG combine generation et...",
                "choices": ["Recherche de contexte", "Suppression de cours", "Design CSS"],
                "answer": "Recherche de contexte",
            }
        ],
    },
}

RECOMMENDATIONS = [
    "Revoir le module Python avant d avancer vers le RAG.",
    "Faire un quiz court apres chaque cours.",
    "Passer au niveau avance lorsque le score moyen depasse 80%.",
]
