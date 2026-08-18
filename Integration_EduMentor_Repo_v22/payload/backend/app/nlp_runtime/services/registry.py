from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib

from app.nlp_runtime.config import settings


class ModelRegistry:
    def __init__(self) -> None:
        m = settings.models_dir
        d = settings.data_dir

        self.level_model = joblib.load(m / "level_classifier_v13.joblib")

        self.content_metadata_router = joblib.load(
            m / "content_metadata_router_v16.joblib"
        )
        self.content_family_model = joblib.load(
            m / "content_family_classifier_v15.joblib"
        )
        self.content_config = json.loads(
            (m / "content_hierarchy_config_v15.json").read_text(
                encoding="utf-8"
            )
        )
        self.content_subtypes: dict[str, Any] = {}
        for family, info in self.content_config["families"].items():
            if info["model"]:
                local_name = {
                    "subtype_synthese_v15.joblib":
                        "content_subtype_synthese_v15.joblib",
                    "subtype_reperes_v15.joblib":
                        "content_subtype_reperes_v15.joblib",
                    "subtype_question_v15.joblib":
                        "content_subtype_question_v15.joblib",
                    "subtype_correction_v15.joblib":
                        "content_subtype_correction_v15.joblib",
                    "subtype_langue_v15.joblib":
                        "content_subtype_langue_v15.joblib",
                }[info["model"]]
                self.content_subtypes[family] = joblib.load(m / local_name)
            else:
                self.content_subtypes[family] = info["constant_label"]

        self.adaptation_memory = joblib.load(
            m / "adaptation_style_memory_v17.joblib"
        )
        self.qa_memory = joblib.load(
            m / "qa_retrieval_memory_v18.joblib"
        )
        self.exact_qa_memory = json.loads(
            (d / "exact_train_qa_memory_v18.json").read_text(
                encoding="utf-8"
            )
        )
        self.chapter_index = json.loads(
            (d / "chapter_index_v8.json").read_text(encoding="utf-8")
        )

        self.figure_binary_model = joblib.load(
            m / "figure_binary_v20.joblib"
        )
        self.figure_type_model = joblib.load(
            m / "figure_type_v20.joblib"
        )
        self.exam_competence_model = joblib.load(
            m / "exam_competence_v20.joblib"
        )

    def status(self) -> dict[str, Any]:
        return {
            "level_classifier": "v13",
            "content_router": "v16 + fallback v15",
            "adaptation": "v17",
            "questions_corrections": "v18",
            "figures_competences": "v20",
            "chapters_loaded": len(self.chapter_index),
            "exact_qa_pairs_loaded": len(self.exact_qa_memory),
            "holdout_loaded": False,
        }


@lru_cache(maxsize=1)
def get_registry() -> ModelRegistry:
    return ModelRegistry()
