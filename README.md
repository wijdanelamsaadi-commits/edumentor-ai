# EduMentor AI

EduMentor AI est une plateforme web pédagogique destinée à accompagner les élèves de 1ère année Baccalauréat au Maroc dans la préparation du régional de français. Le projet combine authentification multi-rôles, diagnostic de niveau, cours adaptés, examens régionaux, suivi de progression, remédiation personnalisée, chatbot pédagogique avec RAG et outils NLP spécialisés.

## Aperçu

La plateforme centralise un parcours complet autour du français 1ère Bac :

- apprentissage guidé autour des oeuvres au programme ;
- diagnostic et positionnement de l'élève ;
- cours et chapitres adaptés au niveau ;
- exercices, quiz et évaluations ;
- examens régionaux en mode guidé et mode complet ;
- analyse des points faibles ;
- recommandations et remédiation ;
- suivi professeur, parent et administrateur ;
- assistant pédagogique basé sur le RAG et les supports indexés.

Liens de production :

- Application : https://frontend-wijdanelamsaadi-3560s-projects.vercel.app
- API : https://edumentor-backend-production.up.railway.app
- Swagger : https://edumentor-backend-production.up.railway.app/docs

## Fonctionnalités principales

- Authentification Firebase avec email/mot de passe, connexion Google et réinitialisation du mot de passe.
- Rôles applicatifs stockés dans PostgreSQL : étudiant, professeur, parent et administrateur.
- Espace étudiant : tableau de bord, test diagnostique, cours, progression, quiz, examens régionaux, remédiation, chatbot et ressources.
- Espace professeur : classes, étudiants, suivi pédagogique, évaluations, import automatique de cours, résultats et remédiation.
- Espace parent : consultation en lecture seule de la progression et des résultats des enfants associés.
- Espace administrateur : gestion des utilisateurs, rôles, cours, PDF, quiz, statistiques, RAG et audit.
- Moteur de diagnostic, analyse des lacunes et recommandations.
- Chatbot pédagogique avec recherche documentaire RAG.
- Runtime NLP spécialisé pour le niveau, l'adaptation de contenu, les figures de style, les compétences d'examen et la correction.
- Génération de certificats PDF côté frontend lorsque les conditions pédagogiques sont remplies.

## Architecture

```text
Utilisateur
   |
   v
Frontend React/Vite
   |
   | HTTPS + Firebase ID Token
   v
Backend FastAPI
   |
   +--> PostgreSQL : données métier, utilisateurs, rôles, cours, résultats
   +--> ChromaDB : index vectoriel RAG
   +--> Firebase Admin : vérification des tokens
   +--> Services IA/NLP : adaptation, correction, points faibles, chatbot
```

## Stack technique

Frontend :

- React
- Vite
- React Router
- Firebase Authentication
- CSS applicatif

Backend :

- FastAPI
- SQLAlchemy
- PostgreSQL
- Pydantic
- Firebase Admin SDK
- ChromaDB
- sentence-transformers
- PyPDF / traitement documentaire
- scikit-learn / joblib pour les modèles NLP

Déploiement :

- Frontend : Vercel
- Backend : Railway
- Base de données : Railway PostgreSQL
- Authentification : Firebase Authentication

## Structure du repository

```text
backend/
  app/
    api/              Routes FastAPI
    core/             Configuration, base de données, migrations légères
    models/           Modèles SQLAlchemy
    schemas/          Schémas Pydantic
    services/         Logique métier, IA, RAG, cours, examens, remédiation
    rag/              Vector store et recherche documentaire
    nlp_runtime/      Runtime NLP et modèles nécessaires
  data/               Jeux de données applicatifs contrôlés
  docs/               Supports pédagogiques utilisés par le backend
  tests/              Tests backend
  requirements.txt
  railway.json

frontend/
  src/
    components/       Composants React réutilisables
    context/          Contextes d'authentification et d'état
    pages/            Pages étudiant, professeur, parent, admin
    services/         Client API, Firebase, certificats
    hooks/            Hooks React
    assets/           Ressources frontend
  package.json
  vercel.json
```

## Rôles utilisateurs

### Étudiant

L'étudiant passe un diagnostic, consulte ses cours, réalise des quiz et examens régionaux, suit sa progression et accède au chatbot pédagogique.

### Professeur

Le professeur gère ses classes, suit ses élèves, crée ou importe des cours et évaluations, consulte les résultats et supervise la remédiation.

### Parent

Le parent consulte les informations de progression et de résultats des enfants qui lui sont associés par l'administration.

### Administrateur

L'administrateur gère les utilisateurs, les rôles, les cours, les supports, les statistiques, l'audit et les opérations de maintenance pédagogique.

## Parcours pédagogique

Le parcours est centré sur la préparation au régional de français 1ère Bac :

- oeuvres : La Boîte à merveilles, Antigone, Le Dernier Jour d'un condamné ;
- compétences : compréhension, langue, figures de style, production écrite, méthodologie ;
- cours adaptés au niveau de l'apprenant ;
- examens régionaux avec correction et rapport ;
- détection des points faibles ;
- remédiation et parcours personnalisé.

## Intelligence artificielle et RAG

Le backend contient un pipeline RAG composé de :

- documents pédagogiques et corpus français ;
- extraction ou structuration du contenu ;
- chunking ;
- embeddings avec sentence-transformers ;
- stockage vectoriel ChromaDB ;
- recherche sémantique ;
- génération de réponses pédagogiques avec sources.

Le chatbot est spécialisé sur le français 1ère Bac et reste centré sur les cours, oeuvres, exercices, méthodologie et examens régionaux du projet.

## NLP

Le dossier `backend/app/nlp_runtime` contient les modèles et services NLP utilisés en arrière-plan. Ces modèles servent notamment à :

- déterminer ou confirmer un niveau pédagogique ;
- organiser et adapter des contenus ;
- classifier des types de contenus ;
- analyser des figures de style ;
- identifier des compétences d'examen ;
- assister certaines corrections pédagogiques.

Les détails techniques des modèles ne sont pas exposés à l'étudiant dans l'interface.

## Examens régionaux

La plateforme inclut un espace régional français avec :

- liste d'examens ;
- mode guidé ;
- mode complet ;
- correction ;
- score ;
- analyse par compétence ;
- rapport de tentative ;
- déclenchement de remédiation selon les lacunes détectées.

## Installation locale

Prérequis :

- Python 3.11 ou version compatible ;
- Node.js ;
- PostgreSQL local ou URL PostgreSQL distante ;
- compte Firebase configuré ;
- variables d'environnement backend et frontend.

## Configuration

Créer les fichiers d'environnement à partir des exemples :

```powershell
cd C:\Users\HP\Desktop\yancode\backend
Copy-Item .env.example .env

cd C:\Users\HP\Desktop\yancode\frontend
Copy-Item .env.example .env
```

## Variables d'environnement

Backend :

```env
DATABASE_URL=...
CORS_ALLOW_ORIGINS=...
EDUMENTOR_DOCS_DIR=...
EDUMENTOR_CHROMA_DIR=...
GROQ_API_KEY=...
GROQ_MODEL=...
AI_MODEL=...
AI_VARIANT_MODEL=...
RAG_SCORE_THRESHOLD=...
FIREBASE_PROJECT_ID=...
FIREBASE_CREDENTIALS_PATH=...
FIREBASE_SERVICE_ACCOUNT_JSON=...
```

Frontend :

```env
VITE_API_URL=...
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=...
VITE_FIREBASE_PROJECT_ID=...
VITE_FIREBASE_STORAGE_BUCKET=...
VITE_FIREBASE_MESSAGING_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
VITE_FIREBASE_MEASUREMENT_ID=...
```

Les vraies valeurs de secrets ne doivent jamais être commitées.

## Lancement du backend

```powershell
cd C:\Users\HP\Desktop\yancode\backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8135 --reload
```

API locale :

```text
http://127.0.0.1:8135
```

Swagger local :

```text
http://127.0.0.1:8135/docs
```

## Lancement du frontend

```powershell
cd C:\Users\HP\Desktop\yancode\frontend
npm install
npm run dev
```

Frontend local :

```text
http://localhost:5173
```

## Tests

Backend :

```powershell
cd C:\Users\HP\Desktop\yancode\backend
python -m compileall app tests
python -m pytest -q
```

Tests NLP ciblés :

```powershell
cd C:\Users\HP\Desktop\yancode\backend
python -m pytest -q tests/test_nlp_integration.py
python scripts/test_nlp_runtime.py
```

Frontend :

```powershell
cd C:\Users\HP\Desktop\yancode\frontend
npm run lint
npm run build
```

## Déploiement

Frontend Vercel :

```text
https://frontend-wijdanelamsaadi-3560s-projects.vercel.app
```

Backend Railway :

```text
https://edumentor-backend-production.up.railway.app
```

Le backend doit recevoir ses secrets via les variables Railway. Le frontend doit recevoir `VITE_API_URL` via la configuration Vercel ou un build explicitement configuré.

## Sécurité

- Firebase est utilisé pour l'authentification.
- Les rôles applicatifs sont stockés côté PostgreSQL.
- Les routes sensibles utilisent des dépendances d'autorisation côté FastAPI.
- Les secrets restent dans `.env`, Railway, Vercel ou Firebase, jamais dans le repository.
- Les fichiers `.env.example` contiennent uniquement des placeholders.
- Les fichiers temporaires, backups, logs, `.venv`, `node_modules`, artefacts lourds et credentials sont exclus par `.gitignore`.

## Liens utiles

- Application : https://frontend-wijdanelamsaadi-3560s-projects.vercel.app
- API : https://edumentor-backend-production.up.railway.app
- Swagger : https://edumentor-backend-production.up.railway.app/docs
- Repository : https://github.com/wijdanelamsaadi-commits/edumentor-ai

## Auteur / contexte du projet

EduMentor AI est un projet de stage réalisé par Wijdane Lamsaadi dans un contexte de développement d'une plateforme intelligente d'apprentissage, avec un accent sur la personnalisation pédagogique, la préparation au régional de français et l'intégration de services IA/NLP dans une application web complète.
