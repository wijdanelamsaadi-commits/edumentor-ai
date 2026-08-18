export const learner = {
  name: 'Wijdane',
  fullName: 'Wijdane Lamsadi',
  email: 'wijdane@exemple.com',
  level: 'Intermediaire',
  goal: 'Préparer le régional de français de 1ère Bac Maroc.',
  avatar: 'WL',
}

export const courses = [
  {
    id: 1,
    title: 'La Boîte à merveilles',
    level: 'Debutant',
    duration: '3h',
    progress: 75,
    tag: '01',
    summary: "Étudier l'oeuvre d'Ahmed Sefrioui : narrateur, personnages, souvenirs et thèmes.",
    objectives: ['Présenter l’auteur et l’oeuvre', 'Identifier les personnages', 'Comprendre les événements', 'Justifier une réponse'],
    examples: ['Sidi Mohammed narrateur', 'Lalla Zoubida', 'Souvenirs d’enfance'],
    exercises: ['Présenter le narrateur', 'Classer les personnages', 'Résumer un extrait'],
  },
  {
    id: 2,
    title: 'Antigone',
    level: 'Intermediaire',
    duration: '3h 20m',
    progress: 45,
    tag: '02',
    summary: 'Analyser la tragédie moderne de Jean Anouilh : conflit, loi, liberté et devoir.',
    objectives: ['Comprendre le conflit', 'Comparer Antigone et Créon', 'Analyser un dialogue'],
    examples: ['Conflit Antigone/Créon', 'Registre tragique'],
    exercises: ['Expliquer le choix d’Antigone', 'Relever deux arguments'],
  },
  {
    id: 3,
    title: "Le Dernier Jour d'un condamné",
    level: 'Intermediaire',
    duration: '3h 10m',
    progress: 20,
    tag: '03',
    summary: 'Comprendre le roman à thèse de Victor Hugo et la dénonciation de la peine de mort.',
    objectives: ['Identifier la thèse', 'Analyser la première personne', 'Repérer les procédés argumentatifs'],
    examples: ['Voix du condamné', 'Champ lexical de la peur'],
    exercises: ['Relever une thèse', 'Rédiger deux arguments'],
  },
  {
    id: 4,
    title: 'Figures de style',
    level: 'Debutant',
    duration: '2h 20m',
    progress: 0,
    tag: '04',
    summary: 'Reconnaître comparaison, métaphore, personnification, antithèse et hyperbole.',
    objectives: ['Nommer une figure', 'Distinguer comparaison et métaphore', 'Expliquer l’effet produit'],
    examples: ['Comparaison', 'Métaphore', 'Personnification'],
    exercises: ['Identifier trois figures', 'Expliquer un effet'],
  },
  {
    id: 5,
    title: 'Production écrite',
    level: 'Avance',
    duration: '3h',
    progress: 0,
    tag: '05',
    summary: 'Construire une rédaction organisée avec introduction, arguments, exemples et conclusion.',
    objectives: ['Analyser le sujet', 'Organiser un plan', 'Utiliser des connecteurs'],
    examples: ['Sujet argumentatif', 'Plan en deux arguments'],
    exercises: ['Rédiger une introduction', 'Développer un argument'],
  },
]

export const diagnosticQuestions = [
  {
    question: 'Quand tu lis un extrait, tu commences par...',
    options: ['Identifier les personnages', 'Lire seulement la dernière phrase', 'Répondre sans lire'],
  },
  {
    question: 'Une comparaison contient généralement...',
    options: ['Un outil comme "comme"', 'Une date de naissance', 'Une opération de calcul'],
  },
  {
    question: 'Pour progresser au régional, tu veux surtout...',
    options: ['Des exercices corrigés', 'Des réponses sans explication', 'Changer de matière'],
  },
]

export const quizQuestions = [
  {
    question: 'Quelle compétence permet de comprendre le sens d’un extrait ?',
    choices: ['Compréhension', 'Décoration', 'Calcul'],
    answer: 'Compréhension',
  },
  {
    question: 'Dans une question de langue, il faut...',
    choices: ['Tenir compte du contexte', 'Ignorer le texte', 'Changer de sujet'],
    answer: 'Tenir compte du contexte',
  },
  {
    question: 'Une bonne production écrite doit afficher...',
    choices: ['Plan, arguments et connecteurs', 'Uniquement une phrase', 'Des idées sans ordre'],
    answer: 'Plan, arguments et connecteurs',
  },
]

export const recommendations = [
  'Relire les personnages des trois oeuvres au programme.',
  'Faire un exercice corrigé sur les figures de style.',
  'Préparer un plan clair avant chaque production écrite.',
]
