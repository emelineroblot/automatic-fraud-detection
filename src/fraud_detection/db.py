"""Accès PostgreSQL (base `fraud`) : insertion des transactions, alertes, rapports."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

import psycopg2
from psycopg2.extras import Json, RealDictCursor, execute_values

from fraud_detection.config import get_settings

log = logging.getLogger(__name__)

TRANSACTION_COLUMNS = [
    "trans_num", "trans_time", "cc_num", "merchant", "category", "amt", "first_name", "last_name",
    "gender", "street", "city", "state", "zip", "lat", "long", "city_pop", "job", "dob",
    "merch_lat", "merch_long", "is_fraud_truth", "fraud_proba", "is_fraud_pred", "model_version",
]


@contextmanager
def get_conn(uri: str | None = None) -> Iterator[psycopg2.extensions.connection]:
    conn = psycopg2.connect(uri or get_settings().fraud_db_uri)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _py(v: Any) -> Any:
    """numpy -> types Python natifs (psycopg2 ne sait pas adapter np.int64/np.float64)."""
    return v.item() if hasattr(v, "item") else v


def insert_transactions(rows: list[dict[str, Any]], uri: str | None = None) -> list[str]:
    """Insère les transactions ; renvoie les `trans_num` réellement nouveaux (dédoublonnage par PK)."""
    if not rows:
        return []
    values = [tuple(_py(r.get(c)) for c in TRANSACTION_COLUMNS) for r in rows]
    sql = (
        f"INSERT INTO transactions ({', '.join(TRANSACTION_COLUMNS)}) VALUES %s "
        "ON CONFLICT (trans_num) DO NOTHING RETURNING trans_num"
    )
    with get_conn(uri) as conn, conn.cursor() as cur:
        inserted = execute_values(cur, sql, values, fetch=True)
    new_ids = [r[0] for r in inserted]
    log.info("%d transaction(s) reçue(s), %d nouvelle(s) insérée(s)", len(rows), len(new_ids))
    return new_ids


def insert_alert(trans_num: str, channel: str, status: str, detail: str | None = None,
                 uri: str | None = None) -> None:
    with get_conn(uri) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO fraud_alerts (trans_num, channel, status, detail) VALUES (%s, %s, %s, %s)",
            (trans_num, channel, status, detail),
        )


# --------------------------------------------------------------------------- rapport quotidien
def fetch_daily_stats(report_date: date, tz: str, uri: str | None = None) -> dict[str, Any]:
    """Agrégats de la journée `report_date` (jour local `tz`) pour le rapport du matin."""
    where = "WHERE (trans_time AT TIME ZONE %(tz)s)::date = %(d)s"
    params = {"tz": tz, "d": report_date}
    with get_conn(uri) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            SELECT COUNT(*)                                            AS nb_transactions,
                   COALESCE(SUM(is_fraud_pred), 0)                    AS nb_frauds,
                   COALESCE(SUM(amt), 0)                              AS total_amount,
                   COALESCE(SUM(amt) FILTER (WHERE is_fraud_pred = 1), 0) AS fraud_amount,
                   COALESCE(AVG(amt), 0)                              AS avg_amount,
                   COUNT(*) FILTER (WHERE is_fraud_truth = 1)         AS nb_frauds_truth,
                   COUNT(*) FILTER (WHERE is_fraud_pred = 1 AND is_fraud_truth = 1) AS true_positives,
                   COUNT(*) FILTER (WHERE is_fraud_pred = 1 AND is_fraud_truth = 0) AS false_positives,
                   COUNT(*) FILTER (WHERE is_fraud_pred = 0 AND is_fraud_truth = 1) AS false_negatives
            FROM transactions {where}
        """, params)
        totals = dict(cur.fetchone())

        cur.execute(f"""
            SELECT category, COUNT(*) AS nb, SUM(is_fraud_pred) AS nb_frauds, SUM(amt) AS amount
            FROM transactions {where}
            GROUP BY category ORDER BY nb_frauds DESC, nb DESC LIMIT 5
        """, params)
        top_categories = [dict(r) for r in cur.fetchall()]

        cur.execute(f"""
            SELECT state, COUNT(*) AS nb, SUM(is_fraud_pred) AS nb_frauds
            FROM transactions {where}
            GROUP BY state ORDER BY nb_frauds DESC, nb DESC LIMIT 5
        """, params)
        top_states = [dict(r) for r in cur.fetchall()]

        cur.execute(f"""
            SELECT EXTRACT(HOUR FROM trans_time AT TIME ZONE %(tz)s)::int AS hour,
                   COUNT(*) AS nb, SUM(is_fraud_pred) AS nb_frauds
            FROM transactions {where}
            GROUP BY 1 ORDER BY 1
        """, params)
        hourly = [dict(r) for r in cur.fetchall()]

        cur.execute(f"""
            SELECT trans_num, trans_time, amt, category, merchant, city, state, fraud_proba, is_fraud_truth
            FROM transactions {where} AND is_fraud_pred = 1
            ORDER BY fraud_proba DESC LIMIT 20
        """, params)
        frauds = [dict(r) for r in cur.fetchall()]

    tp, fp, fn = totals["true_positives"], totals["false_positives"], totals["false_negatives"]
    totals["precision_live"] = tp / (tp + fp) if (tp + fp) else None
    totals["recall_live"] = tp / (tp + fn) if (tp + fn) else None
    return {
        "report_date": report_date.isoformat(), "timezone": tz, **totals,
        "top_categories": top_categories, "top_states": top_states, "hourly": hourly, "frauds": frauds,
    }


def fetch_daily_transactions(report_date: date, tz: str, uri: str | None = None) -> list[dict[str, Any]]:
    with get_conn(uri) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM transactions WHERE (trans_time AT TIME ZONE %(tz)s)::date = %(d)s ORDER BY trans_time",
            {"tz": tz, "d": report_date},
        )
        return [dict(r) for r in cur.fetchall()]


def upsert_daily_report(stats: dict[str, Any], uri: str | None = None) -> None:
    with get_conn(uri) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO daily_reports (report_date, nb_transactions, nb_frauds, total_amount, fraud_amount, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (report_date) DO UPDATE SET
                nb_transactions = EXCLUDED.nb_transactions, nb_frauds = EXCLUDED.nb_frauds,
                total_amount = EXCLUDED.total_amount, fraud_amount = EXCLUDED.fraud_amount,
                payload = EXCLUDED.payload, generated_at = now()
        """, (
            stats["report_date"], stats["nb_transactions"], stats["nb_frauds"],
            stats["total_amount"], stats["fraud_amount"], Json(stats, dumps=lambda o: json.dumps(o, default=str)),
        ))
