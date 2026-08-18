# EduMentor NLP Starter — Dataset étendu 150 exemples

## Contenu
- Dataset : `dataset/Dataset_EduMentor_LBM_Chapitre1_150.jsonl`
- 150 exemples exactement : 50 Débutant, 50 Intermédiaire, 50 Avancé.
- 60 annotations de contenu.
- 30 entrées de vocabulaire.
- 30 exemples synthétiques de figures de style.
- 30 questions adaptées au format des examens régionaux.

## Entraîner tous les modèles
Depuis le dossier du projet avec le venv activé :

```powershell
pip install -r requirements.txt
python src\train_all.py
```

ou :

```powershell
.\train_all.ps1
```

Les modèles seront créés dans `models/`.

## Prédire un niveau
```powershell
python src\predict.py --model models\tfidf_logreg_niveau.joblib --text "La boîte protège l'enfant de sa solitude."
```

## Limites importantes
- Les contenus factuels sont des paraphrases croisées de ressources pédagogiques.
- Les figures de style sont synthétiques et ne sont pas des citations du roman.
- Les questions régionales sont adaptées au format des examens et ne reproduisent pas un libellé officiel.
- Une validation finale par l'encadrant ou un professeur de français reste nécessaire.
- Les métriques de `evaluation_reference/` sont des repères de développement, pas des résultats scientifiques finaux.
