# Données et transformations

## Supports pédagogiques

Les 8 PDF officiels sont placés dans `docs/courses` :

- `01_Introduction_IA.pdf`
- `02_Machine_Learning.pdf`
- `03_Deep_Learning.pdf`
- `04_LLM.pdf`
- `05_Prompt_Engineering.pdf`
- `06_RAG.pdf`
- `07_Chatbots_IA.pdf`
- `08_IA_Responsable.pdf`

## Transformation RAG

1. Extraction du texte PDF.
2. Association du texte au cours et au fichier.
3. Chunking d'environ 800 caractères avec overlap.
4. Embeddings `all-MiniLM-L6-v2`.
5. Index ChromaDB local.
6. Recherche sémantique avec seuil `RAG_SCORE_THRESHOLD`.
7. Réponse pédagogique structurée avec sources.

## Données utilisateur

PostgreSQL stocke les profils, diagnostics, progressions, quiz, notifications, conversations, feedbacks, cours, chapitres, objectifs, exemples, compétences, quiz admin et audit logs.
