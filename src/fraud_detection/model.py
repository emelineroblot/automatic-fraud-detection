"""Chargement du modèle de production depuis le registry MLflow et prédiction."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import mlflow
import numpy as np
import pandas as pd
from mlflow import MlflowClient

from fraud_detection.config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class LoadedModel:
    pipeline: object            # sklearn Pipeline (FeatureBuilder -> preprocessing -> classifier)
    name: str
    version: str
    threshold: float

    @property
    def label(self) -> str:
        return f"{self.name}@v{self.version}"


def load_production_model(settings: Settings | None = None) -> LoadedModel:
    """Charge `models:/<name>@<alias>` (alias `production` par défaut) depuis MLflow."""
    s = settings or get_settings()
    mlflow.set_tracking_uri(s.mlflow_tracking_uri)
    client = MlflowClient()
    mv = client.get_model_version_by_alias(s.mlflow_model_name, s.mlflow_model_alias)
    uri = f"models:/{s.mlflow_model_name}@{s.mlflow_model_alias}"
    pipeline = mlflow.sklearn.load_model(uri)
    log.info("Modèle chargé : %s (version %s, run %s)", uri, mv.version, mv.run_id)
    return LoadedModel(pipeline=pipeline, name=s.mlflow_model_name, version=str(mv.version),
                       threshold=s.fraud_threshold)


def predict_frame(model: LoadedModel, df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute `fraud_proba`, `is_fraud_pred` et `model_version` au DataFrame de transactions."""
    proba = model.pipeline.predict_proba(df)[:, 1]
    out = df.copy()
    out["fraud_proba"] = np.round(proba, 6)
    out["is_fraud_pred"] = (proba >= model.threshold).astype(int)
    out["model_version"] = model.label
    return out
