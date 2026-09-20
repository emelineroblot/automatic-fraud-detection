from pathlib import Path

import mlflow

from fraud_detection.config import Settings
from fraud_detection.model import _cached_model_path


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        fraud_db_uri="postgresql://u:p@h/fraud", mlflow_tracking_uri="http://mlflow:5000",
        mlflow_model_name="fraud_detection", mlflow_model_alias="production",
        fraud_api_url="http://api", fraud_threshold=0.5, report_timezone="Europe/Paris",
        discord_webhook_url=None, model_cache_dir=str(tmp_path / "cache"),
    )


def test_model_downloaded_once_per_version(tmp_path, monkeypatch):
    calls = []

    def fake_download(artifact_uri, dst_path):
        calls.append(artifact_uri)
        Path(dst_path, "MLmodel").write_text("flavors: {}")
        Path(dst_path, "model.pkl").write_bytes(b"x" * 10)
        return dst_path

    monkeypatch.setattr(mlflow.artifacts, "download_artifacts", fake_download)
    s = _settings(tmp_path)

    first = _cached_model_path(s, "models:/fraud_detection@production", "1")
    second = _cached_model_path(s, "models:/fraud_detection@production", "1")
    other = _cached_model_path(s, "models:/fraud_detection@production", "2")

    assert first == second == tmp_path / "cache" / "fraud_detection" / "v1"
    assert (first / "MLmodel").exists() and (first / "model.pkl").exists()
    assert other.name == "v2"
    assert len(calls) == 2                      # v1 une fois, v2 une fois
    assert not list(first.parent.glob("*.partial"))
