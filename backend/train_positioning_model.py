from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


RANDOM_STATE = 20260801

BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "positioning_dataset.csv"

OUTPUT_DIR = BASE_DIR / "positioning_model_artifacts"
MODEL_DIR = OUTPUT_DIR / "model"
EVALUATION_DIR = OUTPUT_DIR / "evaluation"

MODEL_PATH = MODEL_DIR / "positioning_level_model_v1.joblib"
METADATA_PATH = MODEL_DIR / "positioning_level_model_v1_metadata.json"
COMPARISON_PATH = EVALUATION_DIR / "model_comparison.csv"
TEST_PREDICTIONS_PATH = EVALUATION_DIR / "test_predictions.csv"
TEST_CONFUSION_MATRIX_PATH = EVALUATION_DIR / "test_confusion_matrix.json"
TEST_CLASSIFICATION_REPORT_PATH = (
    EVALUATION_DIR / "test_classification_report.json"
)

TARGET_COLUMN = "label_niveau"
GROUP_COLUMN = "profile_id"

FEATURE_COLUMNS = [
    "score_global",
    "score_comprehension",
    "score_langue_grammaire",
    "score_connaissance_oeuvres",
    "score_figures_procedes",
    "score_interpretation_justification",
    "score_debutant",
    "score_intermediaire",
    "score_avance",
]

LABEL_ORDER = [
    "debutant",
    "intermediaire",
    "avance",
]


def split_by_profile(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Sépare les profils, et non les tentatives individuelles.

    Ainsi, les quatre tentatives d'un même profil ne peuvent jamais
    se retrouver à la fois dans l'entraînement et dans le test.
    """
    first_split = GroupShuffleSplit(
        n_splits=1,
        test_size=0.30,
        random_state=RANDOM_STATE,
    )

    train_indices, temporary_indices = next(
        first_split.split(
            dataframe,
            groups=dataframe[GROUP_COLUMN],
        )
    )

    train_df = dataframe.iloc[train_indices].copy()
    temporary_df = dataframe.iloc[temporary_indices].copy()

    second_split = GroupShuffleSplit(
        n_splits=1,
        test_size=0.50,
        random_state=RANDOM_STATE,
    )

    validation_indices, test_indices = next(
        second_split.split(
            temporary_df,
            groups=temporary_df[GROUP_COLUMN],
        )
    )

    validation_df = temporary_df.iloc[validation_indices].copy()
    test_df = temporary_df.iloc[test_indices].copy()

    return train_df, validation_df, test_df


def build_models() -> dict[str, object]:
    return {
        "logistic_regression": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=3000,
                        class_weight="balanced",
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
        "svm_rbf": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    SVC(
                        kernel="rbf",
                        C=2.0,
                        gamma="scale",
                        class_weight="balanced",
                        probability=True,
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=500,
            max_depth=12,
            min_samples_leaf=3,
            class_weight="balanced_subsample",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
    }


def compute_metrics(
    y_true: pd.Series,
    y_pred: list[str],
) -> dict[str, float]:
    return {
        "accuracy": round(
            accuracy_score(y_true, y_pred),
            6,
        ),
        "macro_f1": round(
            f1_score(
                y_true,
                y_pred,
                average="macro",
                zero_division=0,
            ),
            6,
        ),
        "macro_precision": round(
            precision_score(
                y_true,
                y_pred,
                average="macro",
                zero_division=0,
            ),
            6,
        ),
        "macro_recall": round(
            recall_score(
                y_true,
                y_pred,
                average="macro",
                zero_division=0,
            ),
            6,
        ),
    }


def label_distribution(
    dataframe: pd.DataFrame,
) -> dict[str, int]:
    counts = dataframe[TARGET_COLUMN].value_counts()
    return {
        label: int(counts.get(label, 0))
        for label in LABEL_ORDER
    }


def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset introuvable : {DATASET_PATH}\n"
            "Exécute d'abord generate_positioning_dataset.py."
        )

    dataframe = pd.read_csv(DATASET_PATH)

    required_columns = {
        TARGET_COLUMN,
        GROUP_COLUMN,
        *FEATURE_COLUMNS,
    }
    missing_columns = sorted(
        required_columns - set(dataframe.columns)
    )
    if missing_columns:
        raise ValueError(
            "Colonnes manquantes dans le dataset : "
            + ", ".join(missing_columns)
        )

    if dataframe[FEATURE_COLUMNS].isnull().any().any():
        raise ValueError(
            "Le dataset contient des valeurs manquantes "
            "dans les features."
        )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)

    train_df, validation_df, test_df = split_by_profile(
        dataframe
    )

    train_profiles = set(train_df[GROUP_COLUMN])
    validation_profiles = set(validation_df[GROUP_COLUMN])
    test_profiles = set(test_df[GROUP_COLUMN])

    if train_profiles & validation_profiles:
        raise RuntimeError(
            "Fuite détectée entre train et validation."
        )
    if train_profiles & test_profiles:
        raise RuntimeError(
            "Fuite détectée entre train et test."
        )
    if validation_profiles & test_profiles:
        raise RuntimeError(
            "Fuite détectée entre validation et test."
        )

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_COLUMN]

    X_validation = validation_df[FEATURE_COLUMNS]
    y_validation = validation_df[TARGET_COLUMN]

    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df[TARGET_COLUMN]

    comparison_rows: list[dict[str, object]] = []
    fitted_models: dict[str, object] = {}

    for model_name, model in build_models().items():
        model.fit(X_train, y_train)
        validation_predictions = model.predict(X_validation)

        metrics = compute_metrics(
            y_validation,
            validation_predictions,
        )

        comparison_rows.append(
            {
                "model": model_name,
                **metrics,
            }
        )
        fitted_models[model_name] = model

        print(
            f"{model_name}: "
            f"accuracy={metrics['accuracy']:.4f}, "
            f"macro_f1={metrics['macro_f1']:.4f}"
        )

    comparison_df = pd.DataFrame(comparison_rows).sort_values(
        by=["macro_f1", "accuracy"],
        ascending=False,
    )
    comparison_df.to_csv(
        COMPARISON_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    best_model_name = str(
        comparison_df.iloc[0]["model"]
    )

    # Réentraînement final sur train + validation.
    final_training_df = pd.concat(
        [train_df, validation_df],
        ignore_index=True,
    )

    final_models = build_models()
    best_model = final_models[best_model_name]
    best_model.fit(
        final_training_df[FEATURE_COLUMNS],
        final_training_df[TARGET_COLUMN],
    )

    test_predictions = best_model.predict(X_test)
    test_metrics = compute_metrics(
        y_test,
        test_predictions,
    )

    probabilities = None
    if hasattr(best_model, "predict_proba"):
        probabilities = best_model.predict_proba(X_test)

    predictions_df = test_df[
        [
            GROUP_COLUMN,
            "attempt_id",
            TARGET_COLUMN,
            *FEATURE_COLUMNS,
        ]
    ].copy()
    predictions_df["predicted_level"] = test_predictions
    predictions_df["prediction_correct"] = (
        predictions_df[TARGET_COLUMN]
        == predictions_df["predicted_level"]
    )

    if probabilities is not None:
        classes = list(best_model.classes_)
        for class_index, class_name in enumerate(classes):
            predictions_df[
                f"probability_{class_name}"
            ] = probabilities[:, class_index]

        predictions_df["confidence"] = probabilities.max(
            axis=1
        )

    predictions_df.to_csv(
        TEST_PREDICTIONS_PATH,
        index=False,
        encoding="utf-8-sig",
    )

    matrix = confusion_matrix(
        y_test,
        test_predictions,
        labels=LABEL_ORDER,
    )

    confusion_payload = {
        "labels": LABEL_ORDER,
        "matrix": matrix.tolist(),
    }
    TEST_CONFUSION_MATRIX_PATH.write_text(
        json.dumps(
            confusion_payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    report = classification_report(
        y_test,
        test_predictions,
        labels=LABEL_ORDER,
        output_dict=True,
        zero_division=0,
    )
    TEST_CLASSIFICATION_REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    model_bundle = {
        "model": best_model,
        "model_name": best_model_name,
        "model_version": "positioning_level_model_v1",
        "feature_columns": FEATURE_COLUMNS,
        "label_order": LABEL_ORDER,
    }
    joblib.dump(
        model_bundle,
        MODEL_PATH,
    )

    metadata = {
        "model_version": "positioning_level_model_v1",
        "selected_model": best_model_name,
        "selection_metric": "validation_macro_f1",
        "features": FEATURE_COLUMNS,
        "labels": LABEL_ORDER,
        "random_state": RANDOM_STATE,
        "dataset": {
            "path": DATASET_PATH.name,
            "synthetic": True,
            "total_rows": int(len(dataframe)),
            "total_profiles": int(
                dataframe[GROUP_COLUMN].nunique()
            ),
        },
        "split": {
            "method": "GroupShuffleSplit by profile_id",
            "train_rows": int(len(train_df)),
            "validation_rows": int(len(validation_df)),
            "test_rows": int(len(test_df)),
            "train_profiles": int(
                train_df[GROUP_COLUMN].nunique()
            ),
            "validation_profiles": int(
                validation_df[GROUP_COLUMN].nunique()
            ),
            "test_profiles": int(
                test_df[GROUP_COLUMN].nunique()
            ),
            "train_distribution": label_distribution(
                train_df
            ),
            "validation_distribution": label_distribution(
                validation_df
            ),
            "test_distribution": label_distribution(
                test_df
            ),
        },
        "validation_comparison": comparison_df.to_dict(
            orient="records"
        ),
        "test_metrics": test_metrics,
        "scientific_status": (
            "Prototype entraîné et évalué sur un dataset "
            "synthétique contrôlé. Les performances ne doivent "
            "pas être présentées comme une validation clinique "
            "ou pédagogique sur de vrais élèves."
        ),
        "anti_leakage": (
            "Toutes les tentatives d'un profile_id restent dans "
            "un seul sous-ensemble."
        ),
    }

    METADATA_PATH.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("Entraînement terminé avec succès.")
    print(f"Meilleur modèle      : {best_model_name}")
    print(
        "Test accuracy        : "
        f"{test_metrics['accuracy']:.4f}"
    )
    print(
        "Test macro F1        : "
        f"{test_metrics['macro_f1']:.4f}"
    )
    print(f"Modèle enregistré    : {MODEL_PATH}")
    print(f"Métadonnées          : {METADATA_PATH}")
    print(f"Comparaison modèles  : {COMPARISON_PATH}")
    print(
        "Matrice de confusion : "
        f"{TEST_CONFUSION_MATRIX_PATH}"
    )
    print(
        "Prédictions test     : "
        f"{TEST_PREDICTIONS_PATH}"
    )


if __name__ == "__main__":
    main()
