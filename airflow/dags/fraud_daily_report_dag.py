"""DAG quotidien : chaque matin à 6h (Europe/Paris), agrège les paiements et fraudes de la veille,
exporte un CSV, historise le rapport en base et le publie sur Discord.

    aggregate -> export_csv -> archive_s3 -> notify
    aggregate -> store

Déclenchement manuel possible avec un paramètre `report_date` (YYYY-MM-DD) pour rejouer une journée.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pendulum
from airflow.sdk import Param, dag, task

log = logging.getLogger(__name__)

REPORTS_DIR = Path("/opt/airflow/reports")


@dag(
    dag_id="fraud_daily_report",
    description="Rapport quotidien des paiements et fraudes de la veille (Discord + CSV)",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/Paris"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},
    params={"report_date": Param(None, type=["null", "string"], format="date",
                                 description="Journée à rapporter (YYYY-MM-DD). Défaut : la veille.")},
    tags=["fraud", "daily"],
)
def fraud_daily_report():

    @task
    def aggregate(**context) -> dict:
        """Agrégats SQL de la journée cible (défaut : veille en heure locale)."""
        from fraud_detection.config import get_settings
        from fraud_detection.db import fetch_daily_stats

        s = get_settings()
        param = context["params"].get("report_date")
        if param:
            report_date = date.fromisoformat(str(param))
        else:
            report_date = pendulum.now(s.report_timezone).subtract(days=1).date()
        stats = fetch_daily_stats(report_date, s.report_timezone)
        log.info("Rapport %s : %s transactions, %s fraudes, %.2f $ (fraudes %.2f $)",
                 report_date, stats["nb_transactions"], stats["nb_frauds"],
                 float(stats["total_amount"]), float(stats["fraud_amount"]))
        # Decimal/date -> JSON-sérialisable pour XCom
        return _jsonable(stats)

    @task
    def export_csv(stats: dict) -> str:
        """Exporte toutes les transactions de la journée dans reports/transactions_<date>.csv."""
        import pandas as pd

        from fraud_detection.config import get_settings
        from fraud_detection.db import fetch_daily_transactions

        s = get_settings()
        report_date = date.fromisoformat(stats["report_date"])
        rows = fetch_daily_transactions(report_date, s.report_timezone)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"transactions_{report_date.isoformat()}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        log.info("%d ligne(s) exportée(s) -> %s", len(rows), path)
        return str(path)

    @task
    def archive_s3(csv_path: str) -> str | None:
        """Copie l'export dans S3 en production (REPORTS_S3_BUCKET) ; no-op en dev."""
        from fraud_detection.storage import upload_report

        return upload_report(csv_path)

    @task
    def store(stats: dict) -> None:
        from fraud_detection.db import upsert_daily_report

        upsert_daily_report(stats)

    @task
    def notify(stats: dict, csv_path: str, s3_uri: str | None) -> str:
        from fraud_detection.notify import daily_report_embed, send_discord

        status = send_discord(embeds=[daily_report_embed(stats, s3_uri or csv_path)])
        log.info("Rapport %s envoyé sur Discord : %s", stats["report_date"], status)
        return status

    stats = aggregate()
    csv_path = export_csv(stats)
    s3_uri = archive_s3(csv_path)
    store(stats)
    notify(stats, csv_path, s3_uri)


def _jsonable(obj):
    """Convertit récursivement Decimal / date / datetime en types JSON."""
    import datetime as dt
    from decimal import Decimal

    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    return obj


fraud_daily_report()
