from __future__ import annotations

import argparse
import json

import joblib


def main() -> None:
    parser = argparse.ArgumentParser(description="Prédiction avec le modèle NLP EduMentor.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()

    model = joblib.load(args.model)
    prediction = model.predict([args.text])[0]
    result = {"texte": args.text, "prediction": str(prediction)}

    classifier = model.named_steps.get("classifier")
    if hasattr(classifier, "predict_proba"):
        probabilities = model.predict_proba([args.text])[0]
        result["probabilities"] = {
            str(label): float(probability)
            for label, probability in zip(classifier.classes_, probabilities)
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
