# Course Adaptation NLP Report

## Objectif

Ce module ajoute un workflow professeur pour analyser un package pedagogique JSON/LaTeX, classifier ses sections, estimer son niveau et preparer des versions adaptees avant publication. Le cours original reste conserve comme source de verite et la publication exige une validation explicite du professeur.

## Architecture

Le workflow est expose par les routes protegees professeur :

- `POST /api/professor/course-imports/analyze`
- `GET /api/professor/course-imports/{id}`
- `POST /api/professor/course-imports/{id}/adapt`
- `GET /api/professor/course-imports/{id}/preview`
- `PATCH /api/professor/course-imports/{id}/sections/{section_id}`
- `POST /api/professor/course-imports/{id}/validate`
- `POST /api/professor/course-imports/{id}/publish`

Le service principal est `app.services.course_adaptation_nlp_service`. Il reutilise les validateurs et parseurs existants de `automatic_course_generation_service` pour conserver la compatibilite avec les imports V1/V2.

## Donnees et annotations

Le repository contient des modeles NLP locaux dans `backend/app/nlp_runtime/models` et des donnees d'index dans `backend/app/nlp_runtime/data`. Le code ne fournit pas de rapport complet de dataset d'entrainement ni de split train/validation/test pour ce nouveau workflow d'adaptation professeur. Les metriques scientifiques detaillees sont donc non implementees dans ce rapport.

## Classes utilisees

Classification pedagogique ciblee :

- titre
- introduction
- definition
- explication
- exemple
- exercice
- question
- correction
- resume
- figure_de_style
- langue
- comprehension
- methodologie
- production_ecrite
- contenu_oeuvre
- autre

Niveaux :

- `debutant`
- `intermediaire`
- `avance`

## Modeles disponibles

Modeles detectes dans le code :

- `level_classifier_v13.joblib` : estimation du niveau pedagogique.
- `content_family_classifier_v15.joblib` et sous-modeles `content_subtype_*_v15.joblib` : classification hierarchique de contenu.
- `content_metadata_router_v16.joblib` : routage par metadonnees instructionnelles.
- `adaptation_style_memory_v17.joblib` : memoire de style pour adaptation controlee.
- `qa_retrieval_memory_v18.joblib` : memoire question/reponse.
- `figure_binary_v20.joblib`, `figure_type_v20.joblib`, `exam_competence_v20.joblib` : analyse des figures et competences d'examen.

Le fichier `student_weakness_predictor_v1.joblib` existe, mais il n'est pas presente comme classifieur textuel de section dans ce workflow.

## Features

Les features exactes des modeles joblib ne sont pas exposees explicitement par un rapport de formation dans le repository. D'apres le code runtime, les predictions sont effectuees via les objets joblib charges par `ModelRegistry`.

Le fallback heuristique du workflow utilise uniquement :

- longueur approximative du texte ;
- longueur moyenne des mots ;
- mots-cles simples dans le titre, type source et contenu ;
- type de bloc JSON/LaTeX.

## Pipeline d'adaptation

1. Le professeur envoie un JSON et optionnellement un LaTeX.
2. Le backend valide les fichiers avec les schemas Pydantic existants.
3. Le LaTeX est parse pour extraire les sections referencees.
4. Chaque bloc source est transforme en section analysable.
5. Le runtime NLP local tente de predire le type de contenu et le niveau.
6. Le niveau de classe est calcule depuis les derniers `DiagnosticResult` des membres actifs.
7. Des brouillons adaptes sont crees pour le niveau dominant ou pour les trois niveaux.
8. Les sections adaptees sont stockees dans `course_adapted_sections`.
9. Le professeur peut modifier les sections.
10. Le professeur valide les adaptations.
11. La publication cree le cours, les chapitres originaux, les variantes `CourseLevelVariant`, les quiz/assessments existants et les assignations.

## Role du modele propre

Le modele propre EduMentor AI sert a :

- classifier le type de section ;
- estimer le niveau initial ;
- produire une adaptation locale controlee via `adaptation_style_memory_v17`.

Il ne remplace pas la validation humaine.

## Role du modele pre-entraine

Le workflow implemente ici n'appelle pas Groq ou Qwen pour publier automatiquement du contenu. Si une generation externe est ajoutee plus tard, elle devra rester controlee par les predictions NLP et les regles pedagogiques, puis produire un JSON valide avant stockage.

## Fallback

Si le runtime NLP local est indisponible, le workflow applique des heuristiques et des regles pedagogiques simples. Le professeur voit un avertissement. Le fallback ne publie pas directement : il reste un brouillon a valider.

## Traçabilite

Les tables ajoutees conservent :

- import source ;
- classe ;
- niveau cible ;
- contenu original ;
- contenu adapte ;
- type de section ;
- niveau source ;
- methode de generation ;
- createur ;
- validateur ;
- dates de validation/publication.

## Metriques reelles

Non implemente. Le repository ne contient pas de rapport d'entrainement complet pour ce nouveau workflow d'adaptation professeur.

## Limites

- Les performances exactes des modeles ne sont pas documentees dans le code.
- Le fallback par regles n'offre pas la richesse d'un modele generatif controle.
- La validation professeur reste indispensable avant publication.
- Les adaptations ne doivent pas modifier les corrections officielles ou documents d'examen.

## Validation future

Pour completer la partie scientifique, il faut ajouter un dataset annote versionne, comparer Logistic Regression, SVM et Random Forest sur les memes splits, puis publier Accuracy et Macro-F1 reels dans ce rapport.
