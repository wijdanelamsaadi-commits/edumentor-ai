# Tests et validation

## Backend

```powershell
cd C:\Users\HP\Desktop\yancode\backend
.\.venv\Scripts\python -m compileall app
.\.venv\Scripts\python -m pytest
```

La suite couvre :

- création et isolation des utilisateurs Firebase ;
- collision email avec UID Firebase différent ;
- profil utilisateur sans modification de rôle ;
- progression de cours idempotente ;
- seed des 8 cours et quiz ;
- routage chatbot : social, RAG, Groq général, hors sujet.

## Frontend

```powershell
cd C:\Users\HP\Desktop\yancode\frontend
npm run build
npm run lint
```

## Tests navigateur recommandés

1. Login avec un utilisateur normal.
2. Passer le diagnostic.
3. Ouvrir un cours, avancer les chapitres, rafraîchir.
4. Passer un quiz et vérifier Dashboard/Profile.
5. Poser au chatbot : `C'est quoi le RAG ?`, `What is overfitting?`, `météo`, `Bonjour`.
6. Ouvrir l'espace admin avec un compte admin et vérifier cours, statistiques, RAG et audit logs.
