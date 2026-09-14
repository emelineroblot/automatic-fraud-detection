from fraud_detection.config import get_settings


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("FRAUD_DB_URI", "postgresql://u:p@h:5432/fraud")
    monkeypatch.setenv("FRAUD_THRESHOLD", "0.3")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    s = get_settings()

    assert s.fraud_db_uri == "postgresql://u:p@h:5432/fraud"
    assert s.fraud_threshold == 0.3
    assert s.mlflow_model_name == "fraud_detection"
    assert s.discord_webhook_url is None
