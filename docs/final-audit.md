# Audit final CDC

| Exigence CDC | État | Preuve dans le projet | Reste à faire |
|---|---|---|---|
| Diagnostic Débutant / Intermédiaire / Avancé | Réalisé | `/api/diagnostic/questions`, `/api/diagnostic/submit`, sauvegarde PostgreSQL + cache | Aucun blocage |
| Génération/adaptation de cours | Réalisé | 8 cours PostgreSQL, chapitres, objectifs, exemples, compétences, PDF | Génération LLM complète possible en amélioration |
| Quiz adaptés | Réalisé | `GET /api/quiz/{id}`, `POST /api/quiz/{id}/submit`, 10 questions par cours | Aucun blocage |
| Chatbot pédagogique | Réalisé | `/api/chat`, modes `rag_semantic`, `general`, `out_of_scope`, social | Aucun blocage |
| RAG sur documents PDF | Réalisé | extraction, chunks, ChromaDB, embeddings `all-MiniLM-L6-v2`, sources PDF | Réindexation admin disponible |
| Suivi progression/scores/recommandations | Réalisé | PostgreSQL + localStorage fallback, Dashboard/Profile dynamiques | Aucun blocage |
| Interface web claire apprenant | Réalisé | React/Vite, routes protégées, dashboard, cours, quiz, chatbot, ressources, profil | Responsive à vérifier selon terminal final |
| Administration | Réalisé | multi-pages admin, CRUD cours/PDF/quiz, stats, audit, RAG | Aucun blocage majeur |
| PostgreSQL | Réalisé | SQLAlchemy, modèles métier, `DATABASE_URL` | Alembic recommandé plus tard |
| Documentation technique | Réalisé | `docs/*.md`, README final | Aucun blocage |
| Sécurité minimale | Réalisé | Firebase Auth, rôles backend, `.gitignore`, env examples | Durcissement production possible |
