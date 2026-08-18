# Intégration EduMentor NLP v22

Ce package est adapté au repository réel `edumentor-ai`.

Il conserve l’architecture existante :

- FastAPI dans `backend/app`
- Firebase Admin déjà présent
- `get_current_user` pour protéger les routes
- React/Vite et `authenticatedRequest` côté frontend
- PostgreSQL inchangé

## Installation automatique

Décompresser le ZIP, ouvrir PowerShell dans son dossier puis exécuter :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_into_project.ps1 -InstallDependencies
```

Le chemin par défaut est :

```text
C:\Users\HP\Desktop\yancode
```

Un backup des fichiers modifiés est créé automatiquement dans le projet.

## Routes ajoutées

Toutes les routes utilisent le Firebase ID Token existant :

```text
GET  /api/nlp/models/status
POST /api/nlp/level
POST /api/nlp/content-type
POST /api/nlp/adapt
POST /api/nlp/qa/generate
POST /api/nlp/qa/correct
POST /api/nlp/figures
POST /api/nlp/exam-competence
POST /api/nlp/analyze-all
```

## Démarrage

```powershell
cd C:\Users\HP\Desktop\yancode\backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8135
```

Swagger :

```text
http://127.0.0.1:8135/docs
```

Comme les routes sont protégées par Firebase, Swagger répondra `401`
sans Bearer token. Le frontend utilise automatiquement le token grâce
à `authenticatedRequest`.

## Frontend

Le fichier ajouté est :

```text
frontend/src/services/nlpApi.js
```

Exemple :

```javascript
import { analyzeFigureOfSpeech } from './services/nlpApi.js'

const result = await analyzeFigureOfSpeech(
  'La nuit murmure à l’oreille d’Antigone.'
)
```

## Important

- Aucun Holdout n’est inclus.
- La base PostgreSQL n’est pas modifiée.
- Firebase reste uniquement le système d’authentification.
- Les sorties automatiques restent soumises à validation pédagogique.
