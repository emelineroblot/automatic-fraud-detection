"""Feature engineering partagé entre l'entraînement et l'inférence.

Le même `FeatureBuilder` est embarqué dans le pipeline sklearn loggé dans MLflow :
une ligne brute (CSV d'entraînement OU transaction de l'API temps réel) traverse
exactement les mêmes transformations des deux côtés.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

NUMERIC_FEATURES = ["amt", "city_pop", "hour", "day_of_week", "age", "distance_km"]
CATEGORICAL_FEATURES = ["category", "gender"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Colonnes brutes strictement nécessaires au calcul des features
REQUIRED_RAW_COLUMNS = [
    "amt", "city_pop", "dob", "lat", "long", "merch_lat", "merch_long", "category", "gender",
]

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Distance grand-cercle (km) entre deux points, vectorisée."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def resolve_trans_time(df: pd.DataFrame) -> pd.Series:
    """Renvoie l'horodatage de la transaction en UTC naïf, quelle que soit la source.

    - CSV d'entraînement : `trans_date_trans_time` (texte) ou `unix_time` (s)
    - API temps réel     : `current_time` (epoch ms)
    - Base de données    : `trans_time` (timestamp)
    """
    if "trans_time" in df.columns:
        ts = pd.to_datetime(df["trans_time"], utc=True, errors="coerce")
    elif "trans_date_trans_time" in df.columns:
        ts = pd.to_datetime(df["trans_date_trans_time"], errors="coerce")
        ts = ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts.dt.tz_convert("UTC")
    elif "current_time" in df.columns:
        ts = pd.to_datetime(df["current_time"].astype("int64"), unit="ms", utc=True)
    elif "unix_time" in df.columns:
        ts = pd.to_datetime(df["unix_time"].astype("int64"), unit="s", utc=True)
    else:
        raise KeyError("Aucune colonne d'horodatage (trans_time / trans_date_trans_time / current_time / unix_time)")
    return ts.dt.tz_convert(None)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Transforme un DataFrame de transactions brutes en matrice de features."""
    missing = [c for c in REQUIRED_RAW_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(f"Colonnes manquantes pour le feature engineering : {missing}")

    ts = resolve_trans_time(df)
    dob = pd.to_datetime(df["dob"], errors="coerce")

    out = pd.DataFrame(index=df.index)
    out["amt"] = pd.to_numeric(df["amt"], errors="coerce").astype(float)
    out["city_pop"] = pd.to_numeric(df["city_pop"], errors="coerce").astype(float)
    out["hour"] = ts.dt.hour.astype(float)
    out["day_of_week"] = ts.dt.dayofweek.astype(float)
    out["age"] = ((ts - dob).dt.days / 365.25).astype(float)
    out["distance_km"] = haversine_km(df["lat"], df["long"], df["merch_lat"], df["merch_long"])
    out["category"] = df["category"].astype(str)
    out["gender"] = df["gender"].astype(str)
    return out[FEATURES]


class FeatureBuilder(BaseEstimator, TransformerMixin):
    """Étape sklearn sans état : brut -> features. Picklée avec le pipeline dans MLflow."""

    def fit(self, X, y=None):
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return build_features(X)

    def get_feature_names_out(self, input_features=None):
        return np.asarray(FEATURES, dtype=object)
