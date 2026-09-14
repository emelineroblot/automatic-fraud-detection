"""DAG temps réel : toutes les minutes, collecte les paiements de l'API, prédit la fraude,
stocke en base et alerte sur Discord si une nouvelle transaction est frauduleuse.

    extract -> transform -> predict -> load -> check_fraud -> (alert | no_fraud)
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pendulum
from airflow.sdk import Param, dag, task

log = logging.getLogger(__name__)


@dag(
    dag_id="fraud_realtime",
    description="Collecte API -> prédiction fraude -> PostgreSQL -> alerte Discord (chaque minute)",
    schedule="* * * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=5),
    default_args={"retries": 2, "retry_delay": timedelta(seconds=15), "execution_timeout": timedelta(minutes=2)},
    params={
        # Déclenchement manuel : forcer le seuil (ex. 0 -> la transaction courante est traitée comme fraude,
        # pratique pour tester/démontrer la chaîne d'alerte sans attendre une vraie fraude)
        "threshold_override": Param(None, type=["null", "number"], minimum=0, maximum=1,
                                    description="Seuil de décision forcé pour ce run (défaut : FRAUD_THRESHOLD)"),
    },
    tags=["fraud", "realtime"],
)
def fraud_realtime():

    @task
    def extract() -> list[dict]:
        """Appelle l'API HF Space et renvoie les transactions brutes."""
        from fraud_detection.api_client import fetch_transactions
        from fraud_detection.config import get_settings

        return fetch_transactions(get_settings().fraud_api_url)

    @task
    def transform(records: list[dict]) -> list[dict]:
        """Normalise les transactions (noms de colonnes, horodatage UTC)."""
        from fraud_detection.api_client import normalize_transaction

        rows = [normalize_transaction(r) for r in records]
        log.info("%d transaction(s) normalisée(s) : %s", len(rows), [r["trans_num"] for r in rows])
        return rows

    @task
    def predict(rows: list[dict], **context) -> list[dict]:
        """Charge le modèle `production` du registry MLflow et score les transactions."""
        if not rows:
            return []
        from fraud_detection.api_client import to_frame
        from fraud_detection.model import load_production_model, predict_frame

        model = load_production_model()
        override = context["params"].get("threshold_override")
        if override is not None:
            log.warning("Seuil forcé pour ce run : %s (au lieu de %s)", override, model.threshold)
            model.threshold = float(override)
        scored = predict_frame(model, to_frame(rows))
        scored = scored.astype(object).where(scored.notna(), None)   # NaN -> None (XCom JSON)
        out = scored.to_dict("records")
        for r in out:
            log.info("%s | %.2f $ | %s | proba=%.4f -> %s", r["trans_num"], float(r["amt"]), r["category"],
                     float(r["fraud_proba"]), "FRAUDE" if r["is_fraud_pred"] else "ok")
        return out

    @task
    def load(rows: list[dict]) -> list[dict]:
        """Insère en base (dédoublonnage sur trans_num) et renvoie uniquement les nouvelles lignes."""
        from fraud_detection.db import insert_transactions

        new_ids = set(insert_transactions(rows))
        return [r for r in rows if r["trans_num"] in new_ids]

    @task.branch
    def check_fraud(new_rows: list[dict]) -> str:
        frauds = [r for r in new_rows if int(r.get("is_fraud_pred") or 0) == 1]
        log.info("%d nouvelle(s) transaction(s), %d fraude(s)", len(new_rows), len(frauds))
        return "alert" if frauds else "no_fraud"

    @task
    def alert(new_rows: list[dict]) -> None:
        """Notifie chaque nouvelle fraude sur Discord et trace l'alerte en base."""
        from fraud_detection.db import insert_alert
        from fraud_detection.notify import fraud_alert_embed, send_discord

        for r in new_rows:
            if int(r.get("is_fraud_pred") or 0) != 1:
                continue
            try:
                status = send_discord(embeds=[fraud_alert_embed(r)])
                detail = None
            except Exception as exc:  # l'alerte ne doit pas casser le pipeline de stockage
                status, detail = "failed", str(exc)[:500]
                log.exception("Échec de l'envoi Discord pour %s", r["trans_num"])
            insert_alert(r["trans_num"], channel="discord", status=status, detail=detail)
            log.info("Alerte %s pour %s (%.1f %%)", status, r["trans_num"], 100 * float(r["fraud_proba"]))

    @task
    def no_fraud() -> None:
        log.info("Aucune nouvelle fraude détectée sur ce run.")

    new_rows = load(predict(transform(extract())))
    branch = check_fraud(new_rows)
    branch >> [alert(new_rows), no_fraud()]


fraud_realtime()
