from fraud_detection.notify import daily_report_embed, fraud_alert_embed, send_discord

TX = {
    "trans_num": "abc123", "amt": 512.4, "category": "shopping_net", "merchant": "fraud_Shop",
    "fraud_proba": 0.93, "first_name": "Ana", "last_name": "Doe", "city": "Austin", "state": "TX",
    "cc_num": 4242424242424242, "trans_time": "2026-09-14T10:00:00+00:00", "model_version": "fraud_detection@v1",
}


def test_send_discord_skipped_without_webhook(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("FRAUD_DB_URI", "postgresql://x")
    assert send_discord(content="hello") == "skipped"


def test_send_discord_posts_payload(monkeypatch):
    calls = {}

    class Resp:
        def raise_for_status(self):
            pass

    def fake_post(url, json, timeout):
        calls.update(url=url, json=json)
        return Resp()

    monkeypatch.setattr("fraud_detection.notify.requests.post", fake_post)
    assert send_discord(embeds=[fraud_alert_embed(TX)], webhook_url="https://discord/hook") == "sent"
    assert calls["url"] == "https://discord/hook"
    assert calls["json"]["embeds"][0]["title"].endswith("Fraude détectée")


def test_fraud_alert_embed_fields():
    e = fraud_alert_embed(TX)
    names = {f["name"]: f["value"] for f in e["fields"]}
    assert names["Probabilité"] == "93.0 %"
    assert names["Carte"] == "…4242"
    assert "512.40" in e["description"]


def test_daily_report_embed():
    stats = {
        "report_date": "2026-09-13", "timezone": "Europe/Paris", "nb_transactions": 1440, "nb_frauds": 6,
        "total_amount": 98765.4, "fraud_amount": 4321.0, "precision_live": 0.8, "recall_live": 0.5,
        "top_categories": [{"category": "shopping_net", "nb": 200, "nb_frauds": 4}],
    }
    e = daily_report_embed(stats, "/opt/airflow/reports/transactions_2026-09-13.csv")
    names = {f["name"]: f["value"] for f in e["fields"]}
    assert names["Fraudes détectées"] == "6 (0.4 %)"
    assert "précision 80 %" in names["Qualité modèle (vs vérité terrain)"]
    assert "shopping_net : 4 fraude(s) / 200 tx" in names["Top catégories"]
