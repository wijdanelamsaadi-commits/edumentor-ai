# Limites et hypothèses

- Les migrations SQLAlchemy sont créées automatiquement au démarrage en mode développement. Pour une production complète, Alembic est recommandé.
- Le localStorage reste utilisé comme cache/fallback frontend pour certaines données afin de préserver l'expérience hors ligne partielle.
- Les quiz sont stockés en base mais l'évaluation finale de certification repose sur le quiz du dernier cours.
- Le RAG utilise une recherche sémantique locale et ne fait pas encore de génération LLM avec citations enrichies ; il reformule les passages via un constructeur pédagogique backend.
- Le déploiement Docker n'est pas inclus dans cette version.
- Les tests end-to-end navigateur ne sont pas automatisés.
