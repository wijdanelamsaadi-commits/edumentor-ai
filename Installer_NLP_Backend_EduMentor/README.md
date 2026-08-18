# Intégration du modèle NLP dans EduMentor AI

Cette intégration ajoute un service local basé sur les cinq modèles entraînés :

- niveau ;
- record_type ;
- type_information ;
- figure ;
- competence.

## Installation

1. Extraire ce dossier dans :

`C:\Users\HP\Desktop\yancode`

2. Vérifier que les cinq modèles existent déjà dans :

`C:\Users\HP\Desktop\yancode\EduMentor_NLP_Starter_150\models`

3. Depuis PowerShell, avec le venv activé :

```powershell
cd C:\Users\HP\Desktop\yancode\Installer_NLP_Backend_EduMentor
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

L'installateur :

- sauvegarde `backend/app/main.py` ;
- copie les modèles dans `backend/data/nlp_models` ;
- ajoute `app/services/nlp_model_service.py` ;
- ajoute `app/api/nlp_routes.py` ;
- ajoute le router `/api/nlp` dans `main.py` ;
- complète les dépendances du backend.

## Test sans authentification Firebase

```powershell
cd C:\Users\HP\Desktop\yancode\backend
python scripts\test_nlp_service.py
```

## Démarrage de l'API

```powershell
cd C:\Users\HP\Desktop\yancode\backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8001
```

Route publique de contrôle :

`GET /api/nlp/health`

Routes professeur/admin :

- `POST /api/nlp/analyze-text`
- `POST /api/nlp/analyze-file`

`analyze-file` accepte JSON, LaTeX et PDF. L'extraction PDF réutilise le service existant `content_import_service.extract_pdf_pages`.

## Limite actuelle

Cette première intégration analyse le fichier via un endpoint séparé. Elle ne modifie pas encore automatiquement le job `courses/automatic-import`. Cette liaison sera faite après validation des résultats de l'endpoint NLP, afin de ne pas casser le workflow existant.
