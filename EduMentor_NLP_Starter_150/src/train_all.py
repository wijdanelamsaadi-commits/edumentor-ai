from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset" / "Dataset_EduMentor_LBM_Chapitre1_150.jsonl"
MODELS = ROOT / "models"
TARGETS = ["niveau", "record_type", "type_information", "figure", "competence"]

MODELS.mkdir(exist_ok=True)

for target in TARGETS:
    print(f"\n=== Entraînement : {target} ===")
    cmd = [
        sys.executable,
        str(ROOT / "src" / "train_baseline.py"),
        "--dataset", str(DATASET),
        "--target", target,
        "--output-dir", str(MODELS),
    ]
    subprocess.run(cmd, check=True)

print("\nTous les modèles ont été entraînés.")
