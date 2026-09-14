"""Notifications Discord (webhook) : alerte fraude temps réel et rapport quotidien."""

from __future__ import annotations

import logging
from typing import Any

import requests

from fraud_detection.config import get_settings

log = logging.getLogger(__name__)

RED = 0xE74C3C
BLUE = 0x3498DB
GREEN = 0x2ECC71


def send_discord(content: str | None = None, embeds: list[dict[str, Any]] | None = None,
                 webhook_url: str | None = None, timeout: int = 15) -> str:
    """Poste un message sur le webhook Discord. Renvoie 'sent' ou 'skipped' (webhook non configuré)."""
    url = webhook_url or get_settings().discord_webhook_url
    if not url:
        log.warning("DISCORD_WEBHOOK_URL non défini : notification ignorée (%s)", content or embeds[0].get("title"))
        return "skipped"
    payload: dict[str, Any] = {"username": "Fraud Detection"}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return "sent"


def fraud_alert_embed(tx: dict[str, Any]) -> dict[str, Any]:
    """Embed Discord pour une transaction prédite frauduleuse."""
    return {
        "title": "🚨 Fraude détectée",
        "color": RED,
        "description": f"**{float(tx['amt']):.2f} $** — {tx.get('category')} chez `{tx.get('merchant')}`",
        "fields": [
            {"name": "Probabilité", "value": f"{100 * float(tx['fraud_proba']):.1f} %", "inline": True},
            {"name": "Client", "value": f"{tx.get('first_name')} {tx.get('last_name')}", "inline": True},
            {"name": "Lieu", "value": f"{tx.get('city')}, {tx.get('state')}", "inline": True},
            {"name": "Carte", "value": f"…{str(tx.get('cc_num'))[-4:]}", "inline": True},
            {"name": "Horodatage (UTC)", "value": str(tx.get("trans_time"))[:19].replace("T", " "), "inline": True},
            {"name": "Modèle", "value": str(tx.get("model_version")), "inline": True},
            {"name": "trans_num", "value": f"`{tx.get('trans_num')}`", "inline": False},
        ],
    }


def daily_report_embed(stats: dict[str, Any], csv_path: str | None = None) -> dict[str, Any]:
    """Embed Discord du rapport quotidien (paiements et fraudes de la veille)."""
    nb, frauds = int(stats["nb_transactions"]), int(stats["nb_frauds"])
    rate = 100 * frauds / nb if nb else 0.0
    cats = "\n".join(
        f"• {c['category']} : {int(c['nb_frauds'] or 0)} fraude(s) / {int(c['nb'])} tx"
        for c in stats.get("top_categories", [])
    ) or "—"
    quality = "—"
    if stats.get("precision_live") is not None or stats.get("recall_live") is not None:
        p = stats.get("precision_live")
        r = stats.get("recall_live")
        quality = (f"précision {100 * p:.0f} %" if p is not None else "précision n/a") + " · " + \
                  (f"rappel {100 * r:.0f} %" if r is not None else "rappel n/a")
    fields = [
        {"name": "Transactions", "value": f"{nb}", "inline": True},
        {"name": "Fraudes détectées", "value": f"{frauds} ({rate:.1f} %)", "inline": True},
        {"name": "Montant total", "value": f"{float(stats['total_amount']):,.2f} $", "inline": True},
        {"name": "Montant fraudes", "value": f"{float(stats['fraud_amount']):,.2f} $", "inline": True},
        {"name": "Qualité modèle (vs vérité terrain)", "value": quality, "inline": False},
        {"name": "Top catégories", "value": cats, "inline": False},
    ]
    if csv_path:
        fields.append({"name": "Export", "value": f"`{csv_path}`", "inline": False})
    return {
        "title": f"📊 Rapport quotidien — {stats['report_date']}",
        "color": RED if frauds else GREEN,
        "description": f"Paiements et fraudes de la journée ({stats.get('timezone')})",
        "fields": fields,
    }
