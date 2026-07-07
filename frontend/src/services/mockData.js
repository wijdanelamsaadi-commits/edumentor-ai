export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8135'
export const learner = {
  name: 'Wijdane',
  fullName: 'Wijdane Lamsadi',
  email: 'wijdane@exemple.com',
  level: 'Intermediaire',
  goal: 'Gerez votre profil et suivez vos performances.',
  avatar: 'WL',
}

export const courses = [
  {
    id: 1,
    title: "Introduction à l'IA",
    level: 'Debutant',
    duration: '1h 20m',
    progress: 75,
    tag: '01',
    summary: "Decouvrez les fondamentaux de l'intelligence artificielle et ses applications.",
    objectives: [
      "Comprendre ce qu'est l'intelligence artificielle.",
      "Decouvrir l'historique et les grandes etapes de l'IA.",
      "Identifier les principaux domaines d'application de l'IA.",
      "Analyser l'impact de l'IA sur la societe et les metiers.",
      "Se preparer a approfondir les concepts cles de l'IA.",
    ],
    examples: ['Assistants virtuels', 'Recommandations', 'Voitures autonomes'],
    exercises: ['Qu est-ce que l IA ?', "Bref historique de l'IA", "Domaines d'application de l'IA", "Impact et avenir de l'IA"],
  },
  {
    id: 2,
    title: 'Machine Learning',
    level: 'Intermediaire',
    duration: '2h 15m',
    progress: 45,
    tag: '02',
    summary: 'Apprenez les concepts cles du machine learning et les algorithmes essentiels.',
    objectives: ['Identifier features et labels', 'Evaluer un modele', 'Eviter le surapprentissage'],
    examples: ['Prediction de niveau apprenant', 'Classification simple par score'],
    exercises: ['Construire une matrice de confusion', 'Comparer deux modeles simules'],
  },
  {
    id: 3,
    title: 'Prompt Engineering',
    level: 'Intermediaire',
    duration: '1h 10m',
    progress: 20,
    tag: '03',
    summary: "Maitrisez l'art de creer des prompts efficaces pour obtenir les meilleurs resultats.",
    objectives: ['Structurer un prompt', 'Ajouter du contexte', 'Evaluer une reponse IA'],
    examples: ['Prompt de synthese', 'Prompt de correction', 'Prompt de quiz'],
    exercises: ['Reecrire un prompt', 'Comparer deux reponses', 'Ajouter des contraintes'],
  },
  {
    id: 4,
    title: 'RAG (Retrieval-Augmented Generation)',
    level: 'Avance',
    duration: '1h 40m',
    progress: 0,
    tag: '04',
    summary: "Combinez recherche d'information et generation de texte pour des reponses pertinentes.",
    objectives: ['Indexer des contenus', 'Retrouver un passage utile', 'Construire une reponse contextualisee'],
    examples: ['Recherche dans un cours PDF', 'Generation de resume depuis un extrait'],
    exercises: ['Dessiner un pipeline RAG', 'Simuler une reponse avec sources'],
  },
  {
    id: 5,
    title: 'Responsible AI',
    level: 'Avance',
    duration: '1h 30m',
    progress: 0,
    tag: '05',
    summary: "Explorez les enjeux ethiques et les bonnes pratiques d'une IA responsable.",
    objectives: ['Comprendre les biais', 'Evaluer les risques', 'Documenter les limites'],
    examples: ['Charte IA', 'Audit de biais', 'Explication de decision'],
    exercises: ['Identifier un risque', 'Rediger une recommandation', 'Comparer deux usages'],
  },
]

export const diagnosticQuestions = [
  {
    question: 'Quand tu decouvres une nouvelle notion technique, tu preferes commencer par...',
    options: ['Une definition simple', 'Un exemple guide', 'Un cas reel complexe'],
  },
  {
    question: 'En Python, une fonction sert principalement a...',
    options: ['Organiser une action reutilisable', 'Decorer une page web', 'Stocker une image uniquement'],
  },
  {
    question: 'Pour progresser efficacement, tu veux surtout...',
    options: ['Des bases pas a pas', 'Des exercices corriges', 'Des projets autonomes'],
  },
]

export const quizQuestions = [
  {
    question: 'Quel element permet a EduMentor AI d adapter le contenu ?',
    choices: ['Le niveau diagnostique', 'La couleur du bouton', 'Le nom du navigateur'],
    answer: 'Le niveau diagnostique',
  },
  {
    question: 'Dans une architecture RAG, la recherche documentaire sert a...',
    choices: ['Contextualiser la reponse IA', 'Remplacer la base de donnees', 'Supprimer les quiz'],
    answer: 'Contextualiser la reponse IA',
  },
  {
    question: 'Un bon suivi de progression doit afficher...',
    choices: ['Scores et recommandations', 'Uniquement le mot de passe', 'Des donnees aleatoires sans contexte'],
    answer: 'Scores et recommandations',
  },
]

export const recommendations = [
  "Revoir le chapitre Introduction à l'IA avant de continuer le module RAG.",
  'Faire un quiz court apres chaque cours pour stabiliser les acquis.',
  'Passer au niveau avance lorsque le score moyen depasse 80%.',
]
