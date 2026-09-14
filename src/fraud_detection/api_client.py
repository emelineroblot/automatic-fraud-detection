"""Client de l'API temps réel (HF Space) et normalisation des transactions reçues."""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd
import requests

log = logging.getLogger(__name__)

# Renommage API/CSV -> colonnes de la table `transactions`
_RENAME = {"first": "first_name", "last": "last_name", "is_fraud": "is_fraud_truth"}


def parse_payload(payload: str | dict) -> list[dict[str, Any]]:
    """Décode la réponse de l'API : JSON double-encodé au format pandas orient="split"."""
    data = payload
    # L'endpoint renvoie une *string* JSON encapsulée dans du JSON -> deux décodages
    for _ in range(2):
        if isinstance(data, str):
            data = json.loads(data)
    if not isinstance(data, dict) or "columns" not in data or "data" not in data:
        raise ValueError(f"Format de réponse inattendu : {str(payload)[:200]}")
    return [dict(zip(data["columns"], row)) for row in data["data"]]


def fetch_transactions(url: str, timeout: int = 30) -> list[dict[str, Any]]:
    """Appelle l'API et renvoie la liste des transactions brutes (généralement une seule)."""
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    records = parse_payload(resp.text)
    log.info("API %s -> %d transaction(s)", url, len(records))
    return records


def normalize_transaction(record: dict[str, Any]) -> dict[str, Any]:
    """Transaction API -> ligne canonique (noms de colonnes de la table, trans_time ISO UTC).

    Le résultat reste JSON-sérialisable (XCom Airflow).
    """
    row = {_RENAME.get(k, k): v for k, v in record.items()}

    if "current_time" in row:
        ts = pd.to_datetime(int(row.pop("current_time")), unit="ms", utc=True)
    elif "trans_date_trans_time" in row:
        ts = pd.to_datetime(row.pop("trans_date_trans_time"), utc=True)
        row.pop("unix_time", None)
    else:
        raise KeyError("Transaction sans horodatage (current_time / trans_date_trans_time)")
    row["trans_time"] = ts.isoformat()

    if row.get("dob") is not None:
        row["dob"] = str(pd.to_datetime(row["dob"]).date())
    if row.get("is_fraud_truth") is not None:
        row["is_fraud_truth"] = int(row["is_fraud_truth"])
    return row


def to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Lignes canoniques -> DataFrame prêt pour le pipeline de features."""
    return pd.DataFrame(rows)
