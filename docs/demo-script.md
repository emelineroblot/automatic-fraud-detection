# Script de démo vidéo (5–8 min)

Préparation (avant d'enregistrer) :
- `DISCORD_WEBHOOK_URL` renseigné dans `.env`, Discord ouvert sur le salon cible.
- Stack lancée : `docker compose --env-file .env -f docker/dev/docker-compose.yml up -d`
- Modèle en registry (`python training/train.py --data contexte/fraudTest.csv` déjà exécuté).
- DAGs `fraud_realtime` et `fraud_daily_report` **dépausés** dans Airflow.
- Onglets ouverts : Airflow (8080), MLflow (5000), dashboard (8501), Discord, un terminal.

| # | Étape | Ce qu'on montre | Durée |
|---|---|---|---|
| 1 | **Contexte** | `docs/architecture.md` : le schéma, les 2 besoins métier, les briques | 1 min |
| 2 | **Stack** | `docker compose ps` : postgres, mlflow, airflow (api-server, scheduler, dag-processor), dashboard | 30 s |
| 3 | **Modèle** | MLflow : expérience `fraud-detection`, comparaison des 3 runs (PR-AUC), registry `fraud_detection` v1 alias `production`, artefact = pipeline sklearn complet | 1 min |
| 4 | **Temps réel** | Airflow : DAG `fraud_realtime`, grille des runs (un par minute), ouvrir un run → logs de `predict` (proba) et `load` (insertion) | 1 min |
| 5 | **Base** | `docker exec fraud-detection-postgres-1 psql -U fraud -d fraud -c "SELECT trans_time, amt, category, fraud_proba, is_fraud_pred FROM transactions ORDER BY trans_time DESC LIMIT 5;"` | 30 s |
| 6 | **Alerte** | Trigger manuel de `fraud_realtime` avec `{"threshold_override": 0}` (UI : *Trigger DAG w/ config*) → branche `alert` → **notification Discord** en direct → ligne dans `fraud_alerts` | 1 min |
| 7 | **Rapport quotidien** | Trigger manuel de `fraud_daily_report` avec `{"report_date": "<aujourd'hui>"}` → embed Discord (volumes, montants, top catégories, qualité) + `reports/transactions_<date>.csv` + table `daily_reports` | 1 min |
| 8 | **Dashboard** | Streamlit : KPIs du jour, répartition horaire, liste des fraudes, précision/rappel live, alertes, rapports | 1 min |
| 9 | **Conclusion** | Retour au schéma : ce qui répond à chaque besoin, évolutions (Kafka, ré-entraînement planifié, cloud) | 30 s |

Commandes utiles pendant la démo :

```bash
# Déclencher une alerte sans attendre une vraie fraude
docker exec fraud-detection-airflow-scheduler-1 airflow dags trigger fraud_realtime --conf '{"threshold_override": 0}'

# Rapport du jour (au lieu de la veille)
docker exec fraud-detection-airflow-scheduler-1 airflow dags trigger fraud_daily_report --conf '{"report_date": "2026-09-15"}'

# Dernières alertes
docker exec fraud-detection-postgres-1 psql -U fraud -d fraud -c "SELECT * FROM fraud_alerts ORDER BY id DESC LIMIT 5;"
```
