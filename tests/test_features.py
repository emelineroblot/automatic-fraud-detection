import json

import numpy as np
import pandas as pd
import pytest

from fraud_detection.api_client import normalize_transaction, parse_payload, to_frame
from fraud_detection.features import FEATURES, FeatureBuilder, build_features, haversine_km

_API_INNER = {
    "columns": ["cc_num", "merchant", "category", "amt", "first", "last", "gender", "street", "city", "state",
                "zip", "lat", "long", "city_pop", "job", "dob", "trans_num", "merch_lat", "merch_long",
                "is_fraud", "current_time"],
    "index": [13599],
    "data": [[2242542703101233, "fraud_Brown-Greenholt", "entertainment", 115.85, "Samuel", "Jenkins", "M",
              "43235 Mckenzie Views Apt. 837", "Westport", "KY", 40077, 38.4921, -85.4524, 564,
              "Pensions consultant", "1996-04-10", "6d3559f7d6a5686b4bc98af81894dcf6", 38.002512, -84.836117,
              0, 1789401818926]],
}
# L'API renvoie une string JSON encapsulée dans du JSON
API_PAYLOAD = json.dumps(json.dumps(_API_INNER))

CSV_ROW = {
    "trans_date_trans_time": "2020-06-21 12:14:25", "cc_num": 2291163933867244, "merchant": "fraud_Kirlin",
    "category": "personal_care", "amt": 2.86, "first": "Jeff", "last": "Elliott", "gender": "M",
    "street": "351 Darlene Green", "city": "Columbia", "state": "SC", "zip": 29209, "lat": 33.9659,
    "long": -80.9355, "city_pop": 333497, "job": "Mechanical engineer", "dob": "1968-03-19",
    "trans_num": "2da90c7d74bd46a0caf3777415b3ebd3", "unix_time": 1371816865,
    "merch_lat": 33.986391, "merch_long": -81.200714,
}


def test_parse_payload_double_encoded():
    records = parse_payload(API_PAYLOAD)
    assert len(records) == 1
    assert records[0]["trans_num"] == "6d3559f7d6a5686b4bc98af81894dcf6"
    assert records[0]["current_time"] == 1789401818926


def test_parse_payload_accepts_single_encoding_and_dict():
    assert parse_payload(json.dumps(_API_INNER))[0]["amt"] == 115.85
    assert parse_payload(_API_INNER)[0]["amt"] == 115.85


def test_parse_payload_rejects_garbage():
    with pytest.raises(ValueError):
        parse_payload(json.dumps({"foo": 1}))


def test_normalize_transaction_api_row():
    row = normalize_transaction(parse_payload(API_PAYLOAD)[0])
    assert row["first_name"] == "Samuel" and "first" not in row
    assert row["is_fraud_truth"] == 0
    assert row["trans_time"].startswith("2026-09-14T")
    assert "current_time" not in row


def test_haversine_known_distance():
    # Paris -> Londres ~ 344 km
    assert haversine_km(48.8566, 2.3522, 51.5074, -0.1278) == pytest.approx(343.5, abs=2)


def test_build_features_csv_and_api_rows_are_consistent():
    csv_feats = build_features(pd.DataFrame([CSV_ROW]))
    api_feats = build_features(to_frame([normalize_transaction(parse_payload(API_PAYLOAD)[0])]))
    assert list(csv_feats.columns) == FEATURES
    assert list(api_feats.columns) == FEATURES
    assert csv_feats.loc[0, "hour"] == 12 and csv_feats.loc[0, "day_of_week"] == 6  # dimanche
    assert csv_feats.loc[0, "age"] == pytest.approx(52.26, abs=0.05)
    assert api_feats.loc[0, "age"] == pytest.approx(30.4, abs=0.1)
    assert not api_feats.isna().any().any()


def test_build_features_missing_column():
    with pytest.raises(KeyError):
        build_features(pd.DataFrame([{k: v for k, v in CSV_ROW.items() if k != "merch_lat"}]))


def test_feature_builder_in_sklearn_pipeline():
    from sklearn.compose import ColumnTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder

    from fraud_detection.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES

    rows = pd.DataFrame([CSV_ROW] * 20)
    rows["amt"] = np.linspace(1, 500, 20)
    y = (rows["amt"] > 250).astype(int)
    pipe = Pipeline([
        ("features", FeatureBuilder()),
        ("pre", ColumnTransformer([
            ("num", "passthrough", NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ])),
        ("clf", LogisticRegression()),
    ]).fit(rows, y)
    # une ligne API brute traverse le pipeline entraîné sur des lignes CSV
    api_df = to_frame([normalize_transaction(parse_payload(API_PAYLOAD)[0])])
    assert pipe.predict_proba(api_df).shape == (1, 2)
