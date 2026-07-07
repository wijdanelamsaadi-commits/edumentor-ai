# EduMentor AI

Assistant pedagogique intelligent avec frontend React/Vite, backend FastAPI et SQLite.

## Fonctionnalites incluses

- Connexion apprenant simulee
- Dashboard de progression
- Test diagnostique debutant / intermediaire / avance
- Cours, resumes, exemples, exercices et quiz adaptes
- Chatbot pedagogique IA simule
- Suivi des scores et recommandations
- Structure RAG preparee sans branchement OpenAI

## Lancer le backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

API: http://127.0.0.1:8001

## Lancer le frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://127.0.0.1:5173
