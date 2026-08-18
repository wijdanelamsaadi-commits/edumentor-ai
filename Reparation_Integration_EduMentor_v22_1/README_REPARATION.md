# Réparation de l’intégration EduMentor v22.1

Le premier lancement a rencontré deux problèmes :

1. `pip` a expiré pendant le téléchargement de PyMuPDF.
2. `test_nlp_runtime.py` a été lancé directement sans ajouter le dossier
   `backend` à `sys.path`, ce qui a produit `No module named 'app'`.

Les fichiers NLP ont déjà été copiés dans le projet. Il ne faut pas relancer
l’ancien installateur.

## Commandes

Décompresser ce package, ouvrir PowerShell dans son dossier, puis exécuter :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\repair_integration_v22_1.ps1
```

Le script installe uniquement les dépendances NLP indispensables, corrige
définitivement le chemin Python, compile les fichiers et lance le test.

Résultat attendu :

```text
NLP RUNTIME V22 OK
FASTAPI APP IMPORT OK
REPARATION NLP V22.1 TERMINEE
```

Si le runtime NLP fonctionne mais que l’import du backend complet signale une
dépendance manquante, relancer avec :

```powershell
.\repair_integration_v22_1.ps1 -InstallAllDependencies
```

Le délai réseau de pip est porté à 1000 secondes avec 10 tentatives.
