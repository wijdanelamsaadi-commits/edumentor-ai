from __future__ import annotations

# This package already contains the trained artifact.
# Re-run the package generator only after intentionally changing the synthetic
# data assumptions. Current model: student-weakness-v1-20260802

from pathlib import Path
import json
import joblib


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    metrics = json.loads((root / "data" / "student_weakness_predictor_metrics_v1.json").read_text(encoding="utf-8"))
    artifact = joblib.load(root / "app" / "nlp_runtime" / "models" / "student_weakness_predictor_v1.joblib")
    print("Version:", artifact["version"])
    print("Dataset:", artifact["dataset_version"])
    print("Rows:", metrics["dataset_rows"])
    print("Accuracy:", metrics["accuracy"])
    print("Macro-F1:", metrics["macro_f1"])
    print(metrics["scientific_note"])

if __name__ == "__main__":
    main()
