"""Dashboard Streamlit : paiements et fraudes par journée, alertes, qualité du modèle en live.

Lecture seule sur la base `fraud` (FRAUD_DB_URI). Lancé par docker compose sur le port 8501.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st

DB_URI = os.environ["FRAUD_DB_URI"]
TZ = os.getenv("REPORT_TIMEZONE", "Europe/Paris")

st.set_page_config(page_title="Fraud Detection", page_icon="🕵️", layout="wide")


@st.cache_data(ttl=30)
def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    with psycopg2.connect(DB_URI) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])


def day_transactions(d: date) -> pd.DataFrame:
    df = query(
        """
        SELECT trans_num, trans_time AT TIME ZONE %(tz)s AS local_time, amt, category, merchant, city, state,
               gender, fraud_proba, is_fraud_pred, is_fraud_truth, model_version
        FROM transactions
        WHERE (trans_time AT TIME ZONE %(tz)s)::date = %(d)s
        ORDER BY trans_time DESC
        """,
        {"tz": TZ, "d": d},
    )
    return df


# --------------------------------------------------------------------------- sidebar
st.sidebar.title("🕵️ Fraud Detection")
today = pd.Timestamp.now(tz=TZ).date()
selected = st.sidebar.date_input("Journée", value=today, max_value=today)
if st.sidebar.button("↻ Rafraîchir"):
    st.cache_data.clear()
st.sidebar.caption(f"Fuseau : {TZ} · données rafraîchies toutes les 30 s")

bounds = query("SELECT MIN(trans_time) AS first, MAX(trans_time) AS last, COUNT(*) AS n FROM transactions").iloc[0]
st.sidebar.markdown(
    f"**{int(bounds['n'])}** transactions en base"
    + (f"<br>du {bounds['first']:%d/%m %H:%M} au {bounds['last']:%d/%m %H:%M} UTC" if bounds["n"] else ""),
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- KPIs du jour
st.title(f"Paiements du {selected:%d/%m/%Y}")
df = day_transactions(selected)

if df.empty:
    st.info("Aucune transaction pour cette journée.")
else:
    nb, frauds = len(df), int(df["is_fraud_pred"].sum())
    total, fraud_amt = float(df["amt"].sum()), float(df.loc[df["is_fraud_pred"] == 1, "amt"].sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Transactions", nb)
    c2.metric("Fraudes détectées", frauds, f"{100 * frauds / nb:.1f} %", delta_color="inverse")
    c3.metric("Montant total", f"{total:,.2f} $")
    c4.metric("Montant fraudes", f"{fraud_amt:,.2f} $")

    left, right = st.columns([2, 1])
    with left:
        hourly = (
            df.assign(hour=pd.to_datetime(df["local_time"]).dt.hour)
            .groupby("hour").agg(transactions=("trans_num", "count"), fraudes=("is_fraud_pred", "sum"))
            .reindex(range(24), fill_value=0).reset_index()
        )
        fig = px.bar(hourly, x="hour", y=["transactions", "fraudes"], barmode="overlay",
                     color_discrete_map={"transactions": "#3498db", "fraudes": "#e74c3c"},
                     labels={"value": "nombre", "hour": "heure", "variable": ""}, title="Répartition horaire")
        st.plotly_chart(fig, width="stretch")
    with right:
        by_cat = df.groupby("category").agg(transactions=("trans_num", "count"), fraudes=("is_fraud_pred", "sum"),
                                            montant=("amt", "sum")).sort_values("transactions", ascending=False)
        fig = px.bar(by_cat.reset_index(), x="transactions", y="category", orientation="h",
                     color="fraudes", color_continuous_scale=["#3498db", "#e74c3c"], title="Par catégorie")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, width="stretch")

    st.subheader(f"🚨 Fraudes détectées ({frauds})")
    fr = df[df["is_fraud_pred"] == 1]
    if fr.empty:
        st.success("Aucune fraude détectée sur cette journée.")
    else:
        st.dataframe(
            fr[["local_time", "amt", "category", "merchant", "city", "state", "fraud_proba", "is_fraud_truth",
                "trans_num"]],
            width="stretch", hide_index=True,
            column_config={"fraud_proba": st.column_config.ProgressColumn("proba", min_value=0, max_value=1),
                           "amt": st.column_config.NumberColumn("montant", format="%.2f $")},
        )

    with st.expander("Toutes les transactions de la journée"):
        st.dataframe(df, width="stretch", hide_index=True)

# --------------------------------------------------------------------------- qualité du modèle (live)
st.header("Qualité du modèle en production")
st.caption("Comparaison des prédictions avec le label `is_fraud` fourni par l'API (vérité terrain), sur 7 jours glissants.")
q = query(
    """
    SELECT COUNT(*) AS n,
           COUNT(*) FILTER (WHERE is_fraud_pred = 1 AND is_fraud_truth = 1) AS tp,
           COUNT(*) FILTER (WHERE is_fraud_pred = 1 AND is_fraud_truth = 0) AS fp,
           COUNT(*) FILTER (WHERE is_fraud_pred = 0 AND is_fraud_truth = 1) AS fn,
           COUNT(*) FILTER (WHERE is_fraud_pred = 0 AND is_fraud_truth = 0) AS tn,
           MAX(model_version) AS model_version
    FROM transactions WHERE trans_time >= %(since)s
    """,
    {"since": pd.Timestamp.now(tz="UTC") - timedelta(days=7)},
).iloc[0]
tp, fp, fn, tn = (int(q[k] or 0) for k in ("tp", "fp", "fn", "tn"))
c1, c2, c3, c4 = st.columns(4)
c1.metric("Modèle", q["model_version"] or "—")
c2.metric("Précision", f"{100 * tp / (tp + fp):.0f} %" if tp + fp else "n/a")
c3.metric("Rappel", f"{100 * tp / (tp + fn):.0f} %" if tp + fn else "n/a")
c4.metric("Fraudes réelles", tp + fn)
st.dataframe(pd.DataFrame({"prédit fraude": [tp, fp], "prédit ok": [fn, tn]}, index=["fraude réelle", "ok réel"]),
             width="content")

# --------------------------------------------------------------------------- alertes & rapports
col_a, col_r = st.columns(2)
with col_a:
    st.subheader("Dernières alertes")
    alerts = query(
        """
        SELECT a.sent_at AT TIME ZONE %(tz)s AS sent_at, a.channel, a.status, t.amt, t.category, t.fraud_proba,
               a.trans_num
        FROM fraud_alerts a JOIN transactions t USING (trans_num) ORDER BY a.sent_at DESC LIMIT 20
        """,
        {"tz": TZ},
    )
    st.dataframe(alerts, width="stretch", hide_index=True)
with col_r:
    st.subheader("Rapports quotidiens")
    reports = query(
        "SELECT report_date, nb_transactions, nb_frauds, total_amount, fraud_amount, generated_at "
        "FROM daily_reports ORDER BY report_date DESC LIMIT 30"
    )
    st.dataframe(reports, width="stretch", hide_index=True)
