# Installation

## Prérequis

- Python 3.11+
- Node.js 20+
- PostgreSQL
- Un projet Firebase Authentication
- Une clé Groq optionnelle pour les réponses générales

## Backend

```powershell
cd C:\Users\HP\Desktop\yancode\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
```

Variables importantes :

- `DATABASE_URL`
- `GROQ_API_KEY`
- `GROQ_MODEL`
- `RAG_SCORE_THRESHOLD`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_CREDENTIALS_PATH` ou `FIREBASE_SERVICE_ACCOUNT_JSON`

Créer la base PostgreSQL :

```powershell
createdb edumentor_ai
```

Lancer :

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8135 --reload
```

## Frontend

```powershell
cd C:\Users\HP\Desktop\yancode\frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Renseigner les variables `VITE_FIREBASE_*` dans `frontend/.env`.
