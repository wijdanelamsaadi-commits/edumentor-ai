# Sécurité

## Authentification

Firebase est utilisé uniquement pour l'authentification. Le backend vérifie les Firebase ID Tokens avec Firebase Admin. Les données métier ne sont pas stockées dans Firebase.

## Autorisation

Les rôles `admin` et `user` sont stockés dans PostgreSQL. Le frontend peut afficher le rôle, mais le backend ne lui fait jamais confiance. Les routes admin utilisent `get_current_admin` et renvoient `403` pour un utilisateur normal.

## Secrets

Les secrets sont exclus du dépôt via `.gitignore` :

- `.env`
- `.env.*`
- fichiers service account Firebase
- logs, bases locales, index Chroma et builds générés

Les clés Firebase web sont lues depuis `frontend/.env` via `VITE_FIREBASE_*`.

## PDF

Les uploads admin acceptent uniquement les PDF, limitent la taille, sécurisent le nom de fichier et stockent les supports dans `docs/courses` sans exposer le chemin système complet.
