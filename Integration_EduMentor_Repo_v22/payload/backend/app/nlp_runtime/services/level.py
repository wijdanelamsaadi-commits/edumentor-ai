from __future__ import annotations

from typing import Any

import numpy as np

from .registry import ModelRegistry


def predict_level(registry: ModelRegistry, text: str) -> dict[str, Any]:
    model = registry.level_model
    label = str(model.predict([text])[0])
    scores_raw = model.decision_function([text])

    classes = [str(item) for item in model.classes_]
    if np.ndim(scores_raw) == 1:
        values = [float(item) for item in scores_raw]
    else:
        values = [float(item) for item in scores_raw[0]]

    score_by_label = dict(zip(classes, values))
    ordered = sorted(values, reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) >= 2 else ordered[0]

    return {
        "predicted_level": label,
        "decision_scores": score_by_label,
        "decision_margin": float(margin),
        "confidence_kind": "uncalibrated_svm_margin",
        "model_version": "v13",
        "requires_human_validation": True,
    }
