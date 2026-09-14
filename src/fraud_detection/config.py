"""Configuration centralisée, lue depuis les variables d'environnement (.env / docker compose)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Variable d'environnement manquante : {name}")
    return value


@dataclass(frozen=True)
class Settings:
    fraud_db_uri: str
    mlflow_tracking_uri: str
    mlflow_model_name: str
    mlflow_model_alias: str
    fraud_api_url: str
    fraud_threshold: float
    report_timezone: str
    discord_webhook_url: str | None


def get_settings() -> Settings:
    return Settings(
        fraud_db_uri=_env("FRAUD_DB_URI"),
        mlflow_tracking_uri=_env("MLFLOW_TRACKING_URI", "http://localhost:5000"),
        mlflow_model_name=_env("MLFLOW_MODEL_NAME", "fraud_detection"),
        mlflow_model_alias=_env("MLFLOW_MODEL_ALIAS", "production"),
        fraud_api_url=_env(
            "FRAUD_API_URL",
            "https://sdacelo-real-time-fraud-detection.hf.space/current-transactions",
        ),
        fraud_threshold=float(_env("FRAUD_THRESHOLD", "0.5")),
        report_timezone=_env("REPORT_TIMEZONE", "Europe/Paris"),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
    )
