# Architecture EduMentor AI

## Vue d'ensemble

EduMentor AI suit une architecture web classique :

1. React/Vite pour l'interface apprenant et admin.
2. Firebase Authentication pour l'identité.
3. FastAPI pour les API métier.
4. PostgreSQL pour les données persistantes.
5. RAG sémantique pour répondre à partir des PDF pédagogiques.
6. Groq pour les questions IA générales non couvertes par les supports.

## Flux apprenant

L'utilisateur s'authentifie avec Firebase. Le frontend envoie le Firebase ID Token dans l'en-tête `Authorization: Bearer ...`. Le backend vérifie le token avec Firebase Admin, crée ou charge le profil PostgreSQL associé au `firebase_uid`, puis toutes les données métier sont filtrées par utilisateur.

## RAG

Les PDF dans `docs/courses` sont extraits, découpés en chunks, vectorisés avec `all-MiniLM-L6-v2` et indexés dans ChromaDB. Le chatbot interroge d'abord l'index sémantique. Si le score dépasse `RAG_SCORE_THRESHOLD`, il construit une réponse pédagogique structurée et cite les sources PDF.

## Administration

Les routes `/api/admin/...` sont protégées par `get_current_admin`. Les actions sensibles produisent un audit log : cours, PDF, utilisateurs, rôles et réindexation RAG.
