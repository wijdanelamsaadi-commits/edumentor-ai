LEARNER = {
    "id": 1,
    "name": "Wijdane Lamsadi",
    "email": "wijdane@edumentor.ai",
    "level": "Intermediaire",
    "goal": "Comprendre les fondamentaux de l IA et progresser vers un usage fiable du RAG.",
    "progress": 41,
}


PDF_FILES = {
    1: "01_Introduction_IA.pdf",
    2: "02_Machine_Learning.pdf",
    3: "03_Deep_Learning.pdf",
    4: "04_LLM.pdf",
    5: "05_Prompt_Engineering.pdf",
    6: "06_RAG.pdf",
    7: "07_Chatbots_IA.pdf",
    8: "08_IA_Responsable.pdf",
}


COURSE_TOPICS = {
    1: {
        "title": "Introduction IA",
        "level": "Debutant",
        "duration": "2h10",
        "progress": 68,
        "summary": "Comprendre ce qu est l intelligence artificielle, ses usages, ses limites et son role dans EduMentor AI.",
        "description": "Ce cours introduit les bases de l intelligence artificielle avec un vocabulaire accessible. L apprenant decouvre les notions de donnees, modele, prediction, automatisation et aide a la decision, puis relie ces notions au fonctionnement general d EduMentor AI.",
        "objectives": [
            "Definir simplement l intelligence artificielle.",
            "Distinguer automatisation, algorithme et modele IA.",
            "Identifier des exemples d IA dans l education.",
            "Comprendre le role des donnees dans un systeme intelligent.",
            "Reconnaitre les limites et risques principaux de l IA.",
            "Situer EduMentor AI comme assistant pedagogique intelligent.",
        ],
        "chapters": [
            "Qu est ce que l intelligence artificielle",
            "Donnees, algorithmes et modeles",
            "IA faible et systemes specialises",
            "Applications de l IA dans l apprentissage",
            "Limites, erreurs et biais possibles",
            "EduMentor AI comme exemple de plateforme intelligente",
        ],
        "examples": [
            ("Recommandation de cours", "Proposer une ressource adaptee au niveau d un apprenant."),
            ("Correction automatique", "Analyser un quiz et fournir une explication apres chaque reponse."),
            ("Assistant de revision", "Repondre a une question en reformulant un passage de cours."),
            ("Detection de difficulte", "Repérer un score faible et suggerer un parcours plus progressif."),
            ("Plan de progression", "Organiser les prochains cours selon les resultats obtenus."),
        ],
        "exercises": [
            "Citer trois usages de l IA dans une plateforme d apprentissage.",
            "Expliquer la difference entre algorithme et modele.",
            "Identifier un risque possible dans une decision automatisee.",
        ],
        "skills": [
            "Utiliser le vocabulaire de base de l IA.",
            "Identifier un cas d usage pedagogique de l IA.",
            "Expliquer les limites d un systeme intelligent.",
        ],
    },
    2: {
        "title": "Machine Learning",
        "level": "Intermediaire",
        "duration": "3h00",
        "progress": 42,
        "summary": "Comprendre comment un modele apprend a partir de donnees pour classer, predire ou recommander.",
        "description": "Ce cours presente le Machine Learning comme une approche d apprentissage automatique basee sur des donnees. Il introduit les features, labels, jeux d entrainement, evaluation, surapprentissage et usages pedagogiques.",
        "objectives": [
            "Expliquer le principe d apprentissage a partir des donnees.",
            "Identifier features, labels et jeux d entrainement.",
            "Distinguer classification, regression et recommandation.",
            "Comprendre la validation d un modele.",
            "Reconnaitre le surapprentissage.",
            "Relier le Machine Learning au diagnostic de niveau.",
        ],
        "chapters": [
            "Introduction au Machine Learning",
            "Donnees, features et labels",
            "Apprentissage supervise",
            "Classification et regression",
            "Evaluation et metriques",
            "Surapprentissage et generalisation",
        ],
        "examples": [
            ("Classification de niveau", "Predire Debutant, Intermediaire ou Avance a partir d un score."),
            ("Prediction de progression", "Estimer si un apprenant risque de bloquer sur un chapitre."),
            ("Recommandation de cours", "Associer un parcours a l historique d apprentissage."),
            ("Matrice de confusion", "Comparer predictions et niveaux reels obtenus."),
            ("Validation d un modele", "Tester un modele sur des donnees non vues."),
        ],
        "exercises": [
            "Identifier les features utiles pour predire un niveau.",
            "Lire une matrice de confusion simple.",
            "Expliquer pourquoi il faut separer entrainement et test.",
        ],
        "skills": [
            "Decrire un pipeline ML simple.",
            "Choisir une metrique d evaluation.",
            "Detecter un risque de surapprentissage.",
        ],
    },
    3: {
        "title": "Deep Learning",
        "level": "Avance",
        "duration": "3h20",
        "progress": 18,
        "summary": "Explorer les reseaux de neurones, leurs couches, leur entrainement et leurs usages dans les systemes IA modernes.",
        "description": "Ce cours explique le Deep Learning a travers les neurones artificiels, les couches, les fonctions d activation, l optimisation et les architectures utilisees pour traiter texte, image ou donnees complexes.",
        "objectives": [
            "Comprendre le fonctionnement d un neurone artificiel.",
            "Expliquer le role des couches d un reseau.",
            "Identifier activation, poids, perte et optimisation.",
            "Distinguer apprentissage profond et Machine Learning classique.",
            "Comprendre les besoins en donnees et en calcul.",
            "Reconnaitre les limites des modeles profonds.",
        ],
        "chapters": [
            "Du Machine Learning au Deep Learning",
            "Neurones, poids et activations",
            "Couches et architectures profondes",
            "Fonction de perte et optimisation",
            "Applications texte, image et audio",
            "Limites, couts et interpretation",
        ],
        "examples": [
            ("Classification d images", "Utiliser des couches pour reconnaitre une categorie visuelle."),
            ("Analyse de texte", "Transformer une phrase en representation exploitable."),
            ("Detection d intention", "Comprendre la demande d un apprenant dans un chatbot."),
            ("Entrainement iteratif", "Ajuster les poids pour reduire l erreur."),
            ("Limite d interpretation", "Expliquer pourquoi un modele profond peut etre difficile a justifier."),
        ],
        "exercises": [
            "Decrire le role d une fonction d activation.",
            "Comparer ML classique et Deep Learning.",
            "Identifier deux contraintes d un modele profond.",
        ],
        "skills": [
            "Lire le schema general d un reseau de neurones.",
            "Expliquer l optimisation d un modele.",
            "Analyser les limites d un systeme profond.",
        ],
    },
    4: {
        "title": "LLM",
        "level": "Avance",
        "duration": "3h10",
        "progress": 15,
        "summary": "Comprendre les grands modeles de langage, leur fonctionnement, leurs capacites et leurs limites.",
        "description": "Ce cours introduit les Large Language Models : tokenisation, contexte, generation de texte, probabilites, hallucinations, alignement et usages dans un assistant pedagogique.",
        "objectives": [
            "Definir un Large Language Model.",
            "Comprendre le role des tokens et du contexte.",
            "Expliquer la generation probabiliste de texte.",
            "Identifier hallucinations et limites.",
            "Comprendre l interet du RAG pour fiabiliser une reponse.",
            "Relier les LLM au chatbot EduMentor AI.",
        ],
        "chapters": [
            "Qu est ce qu un LLM",
            "Tokens, contexte et representation",
            "Generation probabiliste",
            "Prompt, instruction et reponse",
            "Hallucinations et limites",
            "LLM dans un assistant pedagogique",
        ],
        "examples": [
            ("Resume automatique", "Produire une synthese d un chapitre de cours."),
            ("Explication adaptee", "Reformuler une notion selon le niveau de l apprenant."),
            ("Question reponse", "Construire une reponse a partir d une question et d un contexte."),
            ("Hallucination", "Detecter une information non appuyee par une source."),
            ("RAG et LLM", "Ajouter des documents pour ancrer la reponse."),
        ],
        "exercises": [
            "Expliquer pourquoi un LLM peut halluciner.",
            "Identifier le role du contexte dans une reponse.",
            "Relier LLM et RAG dans EduMentor AI.",
        ],
        "skills": [
            "Expliquer la generation de texte par un LLM.",
            "Identifier les limites d une reponse generee.",
            "Justifier l usage du RAG avec un LLM.",
        ],
    },
    5: {
        "title": "Prompt Engineering",
        "level": "Intermediaire",
        "duration": "2h40",
        "progress": 28,
        "summary": "Apprendre a formuler des consignes claires pour obtenir des reponses utiles, structurees et adaptees.",
        "description": "Ce cours enseigne la conception de prompts efficaces : role, objectif, contexte, format attendu, contraintes, exemples et iteration. Il montre comment guider un chatbot pedagogique sans complexifier inutilement les demandes.",
        "objectives": [
            "Comprendre la structure d un bon prompt.",
            "Formuler un objectif clair.",
            "Ajouter contexte, contraintes et format attendu.",
            "Adapter un prompt au niveau de l apprenant.",
            "Evaluer et ameliorer une reponse.",
            "Utiliser le prompt engineering dans un chatbot IA.",
        ],
        "chapters": [
            "Role du prompt engineering",
            "Objectif, contexte et contraintes",
            "Formats de reponse attendus",
            "Exemples et contre exemples",
            "Adaptation au niveau de l apprenant",
            "Evaluation et iteration du prompt",
        ],
        "examples": [
            ("Prompt de resume", "Demander une synthese courte avec points cles."),
            ("Prompt pedagogique", "Demander une explication simple puis un exemple."),
            ("Prompt de quiz", "Generer des questions avec correction et explication."),
            ("Prompt contraint", "Limiter le vocabulaire ou imposer une structure."),
            ("Prompt ameliore", "Comparer une consigne vague et une consigne precise."),
        ],
        "exercises": [
            "Transformer une question vague en prompt structure.",
            "Ajouter un format de sortie a une demande.",
            "Adapter une consigne a un niveau Debutant.",
        ],
        "skills": [
            "Rediger une consigne precise.",
            "Controler le format d une reponse IA.",
            "Iterer pour ameliorer un resultat.",
        ],
    },
    6: {
        "title": "RAG",
        "level": "Avance",
        "duration": "3h00",
        "progress": 22,
        "summary": "Construire un chatbot capable de rechercher dans des PDF, selectionner les passages utiles et citer ses sources.",
        "description": "Ce cours detaille le Retrieval-Augmented Generation dans EduMentor AI : extraction PDF, chunking, embeddings, base vectorielle, recherche semantique, construction de reponse et affichage des sources.",
        "objectives": [
            "Definir le principe du Retrieval-Augmented Generation.",
            "Comprendre le role des chunks et de l overlap.",
            "Expliquer la recherche semantique avec embeddings.",
            "Identifier les sources utilisees dans une reponse.",
            "Evaluer la pertinence des passages recuperes.",
            "Comprendre les limites et bonnes pratiques du RAG.",
        ],
        "chapters": [
            "Pourquoi utiliser le RAG",
            "Extraction du texte depuis les PDF",
            "Chunking et overlap",
            "Embeddings et base vectorielle",
            "Recherche semantique",
            "Generation de reponse avec sources",
        ],
        "examples": [
            ("Recherche dans les PDF", "Trouver un passage pertinent avant de repondre."),
            ("Chunking", "Decouper un chapitre long en morceaux exploitables."),
            ("Source par page", "Afficher PDF et numero de page sous la reponse."),
            ("Question reformulee", "Retrouver un passage meme si les mots changent."),
            ("Reponse fiable", "Reformuler sans copier integralement le document."),
        ],
        "exercises": [
            "Dessiner le pipeline RAG d EduMentor AI.",
            "Expliquer le role de l embedding.",
            "Identifier une limite d une recherche documentaire.",
        ],
        "skills": [
            "Decrire un pipeline RAG complet.",
            "Verifier une reponse avec ses sources.",
            "Comparer recherche lexicale et semantique.",
        ],
    },
    7: {
        "title": "Chatbots IA",
        "level": "Intermediaire",
        "duration": "2h50",
        "progress": 35,
        "summary": "Comprendre la conception d un chatbot IA pedagogique, de la question utilisateur a la reponse adaptee.",
        "description": "Ce cours presente les composants d un chatbot IA : interface de conversation, intention, contexte, personnalisation, sources, historique et evaluation de la qualite des reponses.",
        "objectives": [
            "Definir le role d un chatbot IA pedagogique.",
            "Comprendre le cycle question, recherche, reponse.",
            "Adapter les reponses au niveau de l apprenant.",
            "Gerer historique, contexte et sources.",
            "Identifier les limites d un chatbot.",
            "Evaluer la qualite d une reponse conversationnelle.",
        ],
        "chapters": [
            "Role d un chatbot pedagogique",
            "Interface conversationnelle",
            "Contexte et personnalisation",
            "Connexion au RAG",
            "Sources et fiabilite",
            "Evaluation des reponses",
        ],
        "examples": [
            ("Reponse niveau Debutant", "Simplifier le vocabulaire et ajouter un exemple facile."),
            ("Reponse niveau Avance", "Ajouter limites, precision technique et bonnes pratiques."),
            ("Historique de chat", "Conserver les messages pour continuer l echange."),
            ("Sources utilisees", "Citer les documents qui ont appuye la reponse."),
            ("Clarification", "Demander plus de precision quand la question est trop vague."),
        ],
        "exercises": [
            "Rediger une reponse adaptee a un niveau Debutant.",
            "Identifier les sources necessaires pour une question.",
            "Evaluer si une reponse de chatbot est suffisamment fiable.",
        ],
        "skills": [
            "Concevoir un flux conversationnel.",
            "Adapter une reponse au niveau utilisateur.",
            "Analyser la fiabilite d une reponse chatbot.",
        ],
    },
    8: {
        "title": "IA Responsable",
        "level": "Debutant",
        "duration": "2h30",
        "progress": 10,
        "summary": "Identifier les principes essentiels pour utiliser l IA de maniere fiable, transparente et responsable.",
        "description": "Ce cours aborde les notions de biais, confidentialite, transparence, explicabilite, securite et responsabilite dans les systemes IA. Il aide l apprenant a evaluer les reponses d un assistant avec esprit critique.",
        "objectives": [
            "Definir les principes d une IA responsable.",
            "Identifier les biais possibles dans les donnees.",
            "Comprendre la confidentialite des informations.",
            "Verifier les sources d une reponse.",
            "Expliquer la transparence et l explicabilite.",
            "Adopter de bonnes pratiques d usage de l IA.",
        ],
        "chapters": [
            "Pourquoi parler d IA responsable",
            "Biais et qualite des donnees",
            "Confidentialite et donnees personnelles",
            "Transparence et explicabilite",
            "Fiabilite des sources",
            "Bonnes pratiques dans EduMentor AI",
        ],
        "examples": [
            ("Biais de donnees", "Un modele mal entraine peut favoriser certains profils."),
            ("Donnees personnelles", "Eviter de partager des informations sensibles dans un chat."),
            ("Source citee", "Verifier un PDF et une page avant de faire confiance a une reponse."),
            ("Explication claire", "Demander au systeme de justifier sa recommandation."),
            ("Usage responsable", "Comparer plusieurs sources avant une decision importante."),
        ],
        "exercises": [
            "Identifier un risque de biais dans un exemple pedagogique.",
            "Lister trois donnees a ne pas partager dans un chatbot.",
            "Expliquer pourquoi les sources augmentent la confiance.",
        ],
        "skills": [
            "Evaluer une reponse IA avec esprit critique.",
            "Proteger les donnees personnelles.",
            "Identifier biais, limites et sources.",
        ],
    },
}


def _chapters(titles, completed_count=1):
    chapters = []
    for index, title in enumerate(titles, start=1):
        completed = index <= completed_count
        status = "completed" if completed else "active" if index == completed_count + 1 else "locked"
        openable = status in {"completed", "active"}
        chapters.append(
            {
                "title": title,
                "duration": f"{20 + index * 5} min",
                "completed": completed,
                "status": status,
                "openable": openable,
            }
        )
    return chapters


def _examples(items):
    return [{"title": title, "description": description} for title, description in items]


def _course(course_id, completed_count):
    topic = COURSE_TOPICS[course_id]
    return {
        "id": course_id,
        "title": topic["title"],
        "level": topic["level"],
        "duration": topic["duration"],
        "progress": topic["progress"],
        "tag": f"{course_id:02d}",
        "summary": topic["summary"],
        "description": topic["description"],
        "objectives": topic["objectives"],
        "chapters": _chapters(topic["chapters"], completed_count),
        "examples": _examples(topic["examples"]),
        "exercises": topic["exercises"],
        "skills": topic["skills"],
        "information": {
            "level": topic["level"],
            "duration": topic["duration"],
            "language": "Francais",
            "last_update": "08/07/2026",
            "chapter_count": len(topic["chapters"]),
        },
        "pdf_url": f"/docs/courses/{PDF_FILES[course_id]}",
    }


COURSES = [
    _course(1, 3),
    _course(2, 2),
    _course(3, 1),
    _course(4, 1),
    _course(5, 2),
    _course(6, 1),
    _course(7, 2),
    _course(8, 0),
]


QUIZ_BLUEPRINTS = {
    1: {
        "concept": "intelligence artificielle",
        "definition": "un systeme capable d aider a analyser, predire ou recommander a partir de donnees",
        "wrong_definition": "un simple fichier PDF sans traitement",
        "data": "les donnees permettent au systeme de produire une analyse plus adaptee",
        "use_case": "recommander un cours selon le niveau d un apprenant",
        "risk": "biais ou erreur si les donnees sont incompletes",
        "edumentor": "adapter le parcours et aider l apprenant avec un chatbot",
    },
    2: {
        "concept": "Machine Learning",
        "definition": "une methode ou un modele apprend des regularites a partir de donnees",
        "wrong_definition": "une page web statique sans donnees",
        "data": "features et labels servent a entrainer puis evaluer le modele",
        "use_case": "classer automatiquement le niveau Debutant, Intermediaire ou Avance",
        "risk": "surapprentissage si le modele memorise trop les donnees d entrainement",
        "edumentor": "analyser les resultats pour proposer des cours adaptes",
    },
    3: {
        "concept": "Deep Learning",
        "definition": "une famille de methodes basees sur des reseaux de neurones a plusieurs couches",
        "wrong_definition": "une liste manuelle de regles fixes uniquement",
        "data": "les donnees ajustent les poids du reseau pendant l entrainement",
        "use_case": "detecter des intentions complexes dans des questions d apprenants",
        "risk": "cout de calcul eleve et interpretation parfois difficile",
        "edumentor": "mieux comprendre des demandes textuelles complexes",
    },
    4: {
        "concept": "LLM",
        "definition": "un grand modele de langage capable de generer du texte a partir d un contexte",
        "wrong_definition": "un tableur de notes sans generation de langage",
        "data": "le contexte et les tokens orientent la generation de la reponse",
        "use_case": "expliquer une notion dans un style adapte au niveau",
        "risk": "hallucination si la reponse n est pas ancree dans des sources",
        "edumentor": "produire des explications pedagogiques structurees",
    },
    5: {
        "concept": "Prompt Engineering",
        "definition": "l art de formuler des consignes claires pour guider une IA",
        "wrong_definition": "une methode pour ignorer le contexte utilisateur",
        "data": "objectif, contexte, contraintes et format attendu rendent la demande plus precise",
        "use_case": "demander un resume avec exemple et mini exercice",
        "risk": "reponse vague si la consigne est incomplete",
        "edumentor": "structurer les demandes envoyees au chatbot pedagogique",
    },
    6: {
        "concept": "RAG",
        "definition": "une approche qui recherche des documents avant de generer une reponse",
        "wrong_definition": "une generation sans document ni source",
        "data": "chunks, embeddings et sources relient la reponse aux PDF",
        "use_case": "retrouver un passage de cours puis citer le PDF utilise",
        "risk": "mauvaise reponse si les chunks recuperes sont peu pertinents",
        "edumentor": "repondre aux questions avec sources PDF et pages",
    },
    7: {
        "concept": "Chatbots IA",
        "definition": "des interfaces conversationnelles capables de repondre a des questions",
        "wrong_definition": "un bouton de navigation sans dialogue",
        "data": "message, niveau, historique et sources ameliorent la reponse",
        "use_case": "accompagner un apprenant pendant sa revision",
        "risk": "reponse trop generale si le contexte manque",
        "edumentor": "dialoguer avec l apprenant et adapter les explications",
    },
    8: {
        "concept": "IA Responsable",
        "definition": "un ensemble de pratiques pour utiliser l IA de facon fiable et transparente",
        "wrong_definition": "une utilisation sans verification ni protection des donnees",
        "data": "qualite des donnees, confidentialite et sources soutiennent la confiance",
        "use_case": "verifier les sources avant d accepter une reponse",
        "risk": "biais, fuite de donnees ou information non fiable",
        "edumentor": "afficher les sources et encourager l esprit critique",
    },
}


def _build_quiz(course_id):
    topic = COURSE_TOPICS[course_id]
    quiz = QUIZ_BLUEPRINTS[course_id]
    concept = quiz["concept"]
    return {
        "course_id": course_id,
        "questions": [
            {
                "question": f"Quelle definition correspond le mieux a {concept} ?",
                "choices": [quiz["definition"], quiz["wrong_definition"], "un changement de couleur dans l interface"],
                "answer": quiz["definition"],
                "explanation": f"{concept} se comprend d abord par son role fonctionnel dans un systeme d apprentissage.",
            },
            {
                "question": f"Dans le cours {topic['title']}, pourquoi les donnees sont-elles importantes ?",
                "choices": [quiz["data"], "elles servent seulement a decorer la page", "elles remplacent toujours l enseignant"],
                "answer": quiz["data"],
                "explanation": "Les donnees apportent le contexte necessaire pour analyser une situation et produire une reponse utile.",
            },
            {
                "question": f"Quel exemple est coherent avec {concept} dans EduMentor AI ?",
                "choices": [quiz["use_case"], "supprimer tous les cours disponibles", "ouvrir une page vide sans contenu"],
                "answer": quiz["use_case"],
                "explanation": "L exemple relie directement la notion du cours a une fonctionnalite pedagogique de la plateforme.",
            },
            {
                "question": f"Quel risque faut-il surveiller avec {concept} ?",
                "choices": [quiz["risk"], "une progression toujours parfaite", "un PDF qui devient automatiquement une image"],
                "answer": quiz["risk"],
                "explanation": "Tout systeme IA doit etre evalue avec prudence, surtout quand la qualite des donnees ou du contexte varie.",
            },
            {
                "question": "Quelle pratique ameliore la fiabilite d une reponse pedagogique ?",
                "choices": ["Verifier les sources et expliquer le raisonnement", "Masquer les sources", "Copier sans comprendre"],
                "answer": "Verifier les sources et expliquer le raisonnement",
                "explanation": "La verification des sources et une explication claire rendent la reponse plus fiable pour l apprenant.",
            },
            {
                "question": f"Comment EduMentor AI utilise principalement {concept} ?",
                "choices": [quiz["edumentor"], "ignorer le niveau de l apprenant", "remplacer tous les supports pedagogiques"],
                "answer": quiz["edumentor"],
                "explanation": "La notion est integree pour personnaliser l apprentissage et rendre l aide plus pertinente.",
            },
            {
                "question": "Pourquoi adapter une explication au niveau de l apprenant ?",
                "choices": ["Pour rendre le contenu comprehensible et progressif", "Pour supprimer le quiz", "Pour eviter tout exemple"],
                "answer": "Pour rendre le contenu comprehensible et progressif",
                "explanation": "Un apprenant Debutant, Intermediaire ou Avance n a pas besoin du meme niveau de detail.",
            },
            {
                "question": "Quel element doit accompagner une bonne correction de quiz ?",
                "choices": ["Une explication de la bonne reponse", "Uniquement une note sans contexte", "Un lien mort"],
                "answer": "Une explication de la bonne reponse",
                "explanation": "La correction devient pedagogique quand elle explique pourquoi une reponse est correcte.",
            },
            {
                "question": f"Quel support officiel correspond au cours {topic['title']} ?",
                "choices": [PDF_FILES[course_id], "ancien-support-inconnu.pdf", "image-sans-contenu.png"],
                "answer": PDF_FILES[course_id],
                "explanation": "Chaque cours EduMentor AI est associe a son PDF officiel dans le dossier docs/courses.",
            },
            {
                "question": "Quelle action montre qu un apprenant progresse correctement ?",
                "choices": ["Consulter le cours, faire le quiz puis analyser la correction", "Ignorer les exercices", "Ne jamais ouvrir les supports"],
                "answer": "Consulter le cours, faire le quiz puis analyser la correction",
                "explanation": "Le parcours complet combine contenu, entrainement, evaluation et retour pedagogique.",
            },
        ],
    }


QUIZZES = {course_id: _build_quiz(course_id) for course_id in COURSE_TOPICS}


RECOMMENDATIONS = [
    {
        "title": "Reviser les bases de l IA",
        "description": "Commencer par Introduction IA avant de passer aux concepts plus techniques.",
        "course_id": 1,
    },
    {
        "title": "Consolider le Machine Learning",
        "description": "Etudier les donnees, labels et metriques pour mieux comprendre le diagnostic.",
        "course_id": 2,
    },
    {
        "title": "Approfondir le RAG",
        "description": "Explorer le pipeline PDF, chunking, recherche semantique et sources.",
        "course_id": 6,
    },
]
