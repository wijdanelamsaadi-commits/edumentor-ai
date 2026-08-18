# EduMentor AI — Starter du modèle NLP

Ce package prépare la première version du **modèle NLP développé et entraîné sur le dataset du projet**, sans utiliser de modèle de langage préentraîné.

## Ce que contient le package

- `dataset/` : prototype annoté de *La Boîte à merveilles*, chapitre 1.
- `src/normalize_input.py` : conversion d'un fichier JSON, LaTeX ou PDF textuel vers une structure JSON commune.
- `src/train_baseline.py` : entraînement TF-IDF + régression logistique.
- `src/predict.py` : prédiction sur un nouveau texte.
- `models/` : modèles sauvegardés.
- `evaluation/` : résultats et comparaisons futures.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 1. Normaliser un fichier importé par l'enseignant

```bash
python src/normalize_input.py --input exemples/chapitre.tex --output exemples/chapitre_normalise.json
```

Le PDF doit contenir du texte sélectionnable. Un PDF scanné nécessitera plus tard un module OCR.

## 2. Entraîner le premier modèle

Classification du niveau :

```bash
python src/train_baseline.py --dataset dataset/dataset_la_boite_a_merveilles_chapitre1_prototype.jsonl --target niveau --output-dir models
```

Classification de la nature de l'enregistrement :

```bash
python src/train_baseline.py --dataset dataset/dataset_la_boite_a_merveilles_chapitre1_prototype.jsonl --target record_type --output-dir models
```

## 3. Tester une prédiction

```bash
python src/predict.py --model models/tfidf_logreg_niveau.joblib --text "La boîte représente un refuge contre la solitude."
```

## Limite actuelle

Le prototype comporte seulement 41 enregistrements. Les scores obtenus servent à vérifier le pipeline, pas à conclure sur les performances du modèle. Avant une évaluation scientifique, il faut viser au minimum plusieurs centaines d'exemples validés, équilibrés entre les classes et répartis entre les trois romans.

## Ordre de travail recommandé

1. Valider le guide et les classes d'annotation.
2. Étendre le chapitre 1 à au moins 100 exemples vérifiés.
3. Annoter les autres chapitres de *La Boîte à merveilles*.
4. Ajouter *Antigone* et *Le Dernier Jour d'un condamné*.
5. Séparer les données par chapitre en entraînement, validation et test afin d'éviter les fuites de données.
6. Comparer le modèle final avec un modèle préentraîné uniquement dans le benchmark.
