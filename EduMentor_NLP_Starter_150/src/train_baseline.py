from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from common import load_jsonl, select_examples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entraîne un modèle NLP EduMentor sans modèle préentraîné.")
    parser.add_argument("--dataset", required=True, help="Chemin du fichier JSONL annoté.")
    parser.add_argument(
        "--target",
        default="niveau",
        choices=["niveau", "record_type", "type_information", "figure", "competence"],
        help="Colonne cible à prédire.",
    )
    parser.add_argument("--output-dir", default="models", help="Dossier de sortie.")
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(args.dataset)
    texts, labels, ids = select_examples(records, args.target)
    counts = Counter(labels)

    if len(texts) < 12 or len(counts) < 2:
        raise SystemExit("Dataset insuffisant : au moins 12 exemples et 2 classes sont nécessaires.")

    too_small = {label: count for label, count in counts.items() if count < 2}
    if too_small:
        raise SystemExit(f"Certaines classes ont moins de 2 exemples : {too_small}")

    stratify = labels if min(counts.values()) >= 2 else None
    x_train, x_test, y_train, y_test, id_train, id_test = train_test_split(
        texts,
        labels,
        ids,
        test_size=args.test_size,
        random_state=args.random_state,
        stratify=stratify,
    )

    model = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    ngram_range=(1, 2),
                    max_features=10000,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=args.random_state,
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)

    metrics = {
        "target": args.target,
        "samples_total": len(texts),
        "samples_train": len(x_train),
        "samples_test": len(x_test),
        "class_distribution": dict(counts),
        "accuracy": accuracy_score(y_test, predictions),
        "macro_f1": f1_score(y_test, predictions, average="macro", zero_division=0),
        "classification_report": classification_report(
            y_test, predictions, output_dict=True, zero_division=0
        ),
        "labels": sorted(counts),
        "confusion_matrix": confusion_matrix(y_test, predictions, labels=sorted(counts)).tolist(),
        "warning": (
            "Résultats de smoke test uniquement : dataset trop petit pour une conclusion scientifique."
            if len(texts) < 300
            else None
        ),
    }

    model_path = output_dir / f"tfidf_logreg_{args.target}.joblib"
    metrics_path = output_dir / f"metrics_{args.target}.json"
    predictions_path = output_dir / f"predictions_{args.target}.csv"

    joblib.dump(model, model_path)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    with predictions_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "texte", "vrai_label", "label_predit"])
        for sample_id, text, truth, prediction in zip(id_test, x_test, y_test, predictions):
            writer.writerow([sample_id, text, truth, prediction])

    print(json.dumps({
        "model": str(model_path),
        "metrics": str(metrics_path),
        "predictions": str(predictions_path),
        "accuracy": metrics["accuracy"],
        "macro_f1": metrics["macro_f1"],
        "warning": metrics["warning"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
