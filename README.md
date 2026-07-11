# EduMentor AI

EduMentor AI est une plateforme web d'apprentissage de l'intelligence artificielle avec diagnostic de niveau, cours personnalisés, quiz, suivi de progression, chatbot pédagogique RAG, administration et authentification Firebase.

## Stack

- Frontend : React, Vite, React Router, Firebase Authentication.
- Backend : FastAPI, SQLAlchemy, PostgreSQL.
- IA : RAG sémantique avec PDF, chunking, ChromaDB, sentence-transformers et fallback Groq pour les questions IA absentes des supports.
- Stockage métier : PostgreSQL. Le localStorage reste utilisé comme cache/fallback frontend pour conserver une expérience tolérante aux coupures.

## Fonctionnalités principales

- Authentification email/mot de passe, Google Sign-In, reset password.
- Rôles `user` et `admin` stockés dans PostgreSQL.
- Espace apprenant : dashboard, diagnostic, cours, détail de cours, quiz, chatbot, ressources, profil/progression, paramètres.
- Espace admin multi-pages : tableau de bord, utilisateurs, cours/PDF/quiz, statistiques, RAG, journal d'audit.
- Bibliothèque de 8 supports PDF officiels : IA, Machine Learning, Deep Learning, LLM, Prompt Engineering, RAG, Chatbots IA, IA Responsable.
- Certificat PDF généré côté frontend quand tous les cours sont terminés et le quiz final est réussi.

## Lancement local

Backend :

```powershell
cd C:\Users\HP\Desktop\yancode\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8135 --reload
```

Frontend :

```powershell
cd C:\Users\HP\Desktop\yancode\frontend
npm install
Copy-Item .env.example .env
npm run dev
```

## Documentation

- Architecture : `docs/architecture.md`
- Installation : `docs/installation.md`
- Tests : `docs/tests.md`
- Sécurité : `docs/security.md`
- Limites : `docs/limitations.md`
- Scénario de démonstration : `docs/demo-scenario.md`
- Données et transformations : `docs/data-and-transformations.md`
- Évaluation pédagogique : `docs/evaluation_pedagogique.md`
- Audit final CDC : `docs/final-audit.md`
