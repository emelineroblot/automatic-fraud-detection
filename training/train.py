"""Entraînement, comparaison et mise en production du modèle de détection de fraude.

Usage :
    python training/train.py --data contexte/fraudTest.csv
    python training/train.py --data contexte/fraudTest.csv --models lgbm --sample 100000 --no-register

Chaque modèle = un run MLflow (pipeline sklearn complet : FeatureBuilder -> preprocessing -> classifieur).
Le meilleur (PR-AUC sur le jeu de test temporel) est enregistré dans le registry sous
`fraud_detection` avec l'alias `production`, que le DAG Airflow charge directement.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from mlflow import MlflowClient
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fraud_detection.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES, FeatureBuilder  # noqa: E402

log = logging.getLogger("train")
RANDOM_STATE = 42


# --------------------------------------------------------------------------- data
def load_data(path: str, sample: int | None) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    if sample:
        df = df.sample(n=min(sample, len(df)), random_state=RANDOM_STATE)
    log.info("Dataset : %d lignes, %.3f %% de fraudes", len(df), 100 * df["is_fraud"].mean())
    return df


def temporal_split(df: pd.DataFrame, test_size: float = 0.2):
    """Split temporel : on entraîne sur le passé, on teste sur le futur (comme en production)."""
    df = df.sort_values("trans_date_trans_time")
    cut = int(len(df) * (1 - test_size))
    train, test = df.iloc[:cut], df.iloc[cut:]
    log.info(
        "Train : %d lignes (jusqu'au %s) | Test : %d lignes (à partir du %s)",
        len(train), train["trans_date_trans_time"].iloc[-1], len(test), test["trans_date_trans_time"].iloc[0],
    )
    return train, test


# --------------------------------------------------------------------------- models
def make_pipeline(kind: str, pos_weight: float) -> Pipeline:
    cat = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    if kind == "lr":
        pre = ColumnTransformer([("num", StandardScaler(), NUMERIC_FEATURES), ("cat", cat, CATEGORICAL_FEATURES)])
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE)
    elif kind == "rf":
        pre = ColumnTransformer([("num", "passthrough", NUMERIC_FEATURES), ("cat", cat, CATEGORICAL_FEATURES)])
        clf = RandomForestClassifier(
            n_estimators=200, min_samples_leaf=2, class_weight="balanced_subsample",
            n_jobs=-1, random_state=RANDOM_STATE,
        )
    elif kind == "lgbm":
        pre = ColumnTransformer([("num", "passthrough", NUMERIC_FEATURES), ("cat", cat, CATEGORICAL_FEATURES)])
        clf = LGBMClassifier(
            n_estimators=600, learning_rate=0.05, num_leaves=63, subsample=0.8, subsample_freq=1,
            colsample_bytree=0.8, scale_pos_weight=pos_weight, random_state=RANDOM_STATE, n_jobs=-1, verbose=-1,
        )
    else:
        raise ValueError(kind)
    return Pipeline([("features", FeatureBuilder()), ("pre", pre), ("clf", clf)])


def evaluate(y_true, proba) -> dict[str, float]:
    precision, recall, thresholds = precision_recall_curve(y_true, proba)
    f1 = 2 * precision * recall / np.clip(precision + recall, 1e-12, None)
    best = int(np.argmax(f1[:-1]))
    pred_05 = (proba >= 0.5).astype(int)
    return {
        "pr_auc": float(average_precision_score(y_true, proba)),
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "precision_at_0.5": float(precision_score(y_true, pred_05, zero_division=0)),
        "recall_at_0.5": float(recall_score(y_true, pred_05)),
        "f1_at_0.5": float(f1_score(y_true, pred_05)),
        "best_threshold": float(thresholds[best]),
        "best_f1": float(f1[best]),
        "precision_at_best": float(precision[best]),
        "recall_at_best": float(recall[best]),
    }


# --------------------------------------------------------------------------- main
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", required=True, help="chemin du CSV fraudTest.csv")
    p.add_argument("--models", default="lr,rf,lgbm", help="liste parmi lr,rf,lgbm")
    p.add_argument("--sample", type=int, default=None, help="sous-échantillon pour un essai rapide")
    p.add_argument("--experiment", default="fraud-detection")
    p.add_argument("--model-name", default=os.getenv("MLFLOW_MODEL_NAME", "fraud_detection"))
    p.add_argument("--alias", default=os.getenv("MLFLOW_MODEL_ALIAS", "production"))
    p.add_argument("--no-register", action="store_true", help="ne pas enregistrer le meilleur modèle")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # MLflow écrit des emojis sur stdout -> plante sous Windows en cp1252
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment(args.experiment)
    log.info("MLflow : %s / expérience %s", mlflow.get_tracking_uri(), args.experiment)

    df = load_data(args.data, args.sample)
    train, test = temporal_split(df)
    X_train, y_train = train.drop(columns=["is_fraud"]), train["is_fraud"]
    X_test, y_test = test.drop(columns=["is_fraud"]), test["is_fraud"]
    pos_weight = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))

    results: list[tuple[str, float, str]] = []
    for kind in [m.strip() for m in args.models.split(",") if m.strip()]:
        with mlflow.start_run(run_name=kind) as run:
            log.info("=== %s ===", kind)
            pipe = make_pipeline(kind, pos_weight)
            pipe.fit(X_train, y_train)
            proba = pipe.predict_proba(X_test)[:, 1]
            metrics = evaluate(y_test.to_numpy(), proba)
            log.info("%s -> %s", kind, {k: round(v, 4) for k, v in metrics.items()})

            clf_params = {
                f"clf__{k}": v for k, v in pipe.named_steps["clf"].get_params().items()
                if isinstance(v, (int, float, str, bool))
            }
            mlflow.log_params({
                "model": kind, "n_train": len(X_train), "n_test": len(X_test),
                "pos_weight": round(pos_weight, 2), "split": "temporal_80_20", **clf_params,
            })
            mlflow.log_metrics(metrics)
            mlflow.set_tag("best_threshold", f"{metrics['best_threshold']:.4f}")
            example = X_test.head(5)
            # cloudpickle : le format skops (défaut MLflow 3) refuse les classes custom (FeatureBuilder, LightGBM)
            mlflow.sklearn.log_model(
                pipe, name="model", input_example=example,
                signature=infer_signature(example, pipe.predict_proba(example)[:, 1]),
                serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
            )
            results.append((kind, metrics["pr_auc"], run.info.run_id))

    results.sort(key=lambda r: r[1], reverse=True)
    best_kind, best_auc, best_run = results[0]
    log.info("Classement PR-AUC : %s", [(k, round(a, 4)) for k, a, _ in results])

    if args.no_register:
        log.info("--no-register : meilleur modèle = %s (run %s), non enregistré", best_kind, best_run)
        return

    client = MlflowClient()
    mv = mlflow.register_model(f"runs:/{best_run}/model", args.model_name)
    client.set_registered_model_alias(args.model_name, args.alias, mv.version)
    client.set_model_version_tag(args.model_name, mv.version, "algorithm", best_kind)
    client.set_model_version_tag(args.model_name, mv.version, "pr_auc", f"{best_auc:.4f}")
    best_thr = client.get_run(best_run).data.tags.get("best_threshold", "")
    client.set_model_version_tag(args.model_name, mv.version, "best_threshold", best_thr)
    log.info(
        "Modèle %s version %s (%s, PR-AUC %.4f) -> alias '%s'",
        args.model_name, mv.version, best_kind, best_auc, args.alias,
    )


if __name__ == "__main__":
    main()
