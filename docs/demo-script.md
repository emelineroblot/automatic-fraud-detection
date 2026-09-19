# Script de démo vidéo (5–8 min)

La vidéo montre **le pipeline en production sur AWS** (l'énoncé demande une capture du pipeline en production, cloud ou on-premise).

Préparation (avant d'enregistrer) :
- Stack AWS déployée : `bash infra/terraform/tf.sh output` → `airflow_url`, `mlflow_url`, `dashboard_url`, `ssh` ; login Airflow : `tf.sh output -raw airflow_login`.
- Discord ouvert sur le salon du webhook ; console AWS ouverte (EC2 `fraud-detection-airflow`, bucket S3).
- DAGs `fraud_realtime` et `fraud_daily_report` **dépausés** (fait par le bootstrap).
- Onglets : Airflow, MLflow, dashboard (URLs publiques de l'instance — **pas `localhost`**), Discord, console AWS, un terminal SSH.

| # | Étape | Ce qu'on montre | Durée |
|---|---|---|---|
| 1 | **Contexte** | `docs/architecture.md` : le schéma, les 2 besoins métier, les briques | 1 min |
| 2 | **Infra** | Console AWS : l'EC2, le bucket S3 (`data/`, `mlflow-artifacts/`, `reports/`) ; terminal : `tf.sh output` puis `ssh … 'sudo docker ps'` — 6 containers | 45 s |
| 3 | **Modèle** | MLflow : expérience `fraud-detection`, comparaison des 3 runs (PR-AUC), registry `fraud_detection` v1 alias `production`, artefact = pipeline sklearn complet | 1 min |
| 4 | **Temps réel** | Airflow : DAG `fraud_realtime`, grille des runs (un par minute), ouvrir un run → logs de `predict` (proba) et `load` (insertion) | 1 min |
| 5 | **Base** | via SSH : `sudo docker exec fraud-detection-postgres-1 psql -U fraud -d fraud -c "SELECT trans_time, amt, category, fraud_proba, is_fraud_pred FROM transactions ORDER BY trans_time DESC LIMIT 5;"` | 30 s |
| 6 | **Alerte** | Trigger manuel de `fraud_realtime` avec `{"threshold_override": 0}` (UI : *Trigger DAG w/ config*) → branche `alert` → **notification Discord** en direct → ligne dans `fraud_alerts` | 1 min |
| 7 | **Rapport quotidien** | Trigger manuel de `fraud_daily_report` avec `{"report_date": "<aujourd'hui>"}` → embed Discord (volumes, montants, top catégories, qualité, **URI S3 du CSV**) → le fichier dans le bucket S3 (console) | 1 min |
| 8 | **Dashboard** | Streamlit : KPIs du jour, répartition horaire, liste des fraudes, précision/rappel live, alertes, rapports | 1 min |
| 9 | **Conclusion** | Retour au schéma : ce qui répond à chaque besoin, évolutions (Kafka, ré-entraînement planifié, cloud) | 30 s |

Commandes utiles pendant la démo (les triggers se font aussi depuis l'UI Airflow : *Trigger DAG w/ config*) :

```bash
SSH=$(bash infra/terraform/tf.sh output -raw ssh)
C='cd /opt/fraud && sudo docker compose --env-file .env -f docker/prod/docker-compose.yml exec -T airflow-scheduler airflow'

# Déclencher une alerte sans attendre une vraie fraude
$SSH "$C dags trigger fraud_realtime --conf '{\"threshold_override\": 0}'"

# Rapport du jour (au lieu de la veille)
$SSH "$C dags trigger fraud_daily_report --conf '{\"report_date\": \"$(date +%F)\"}'"

# Dernières alertes, CSV archivés
$SSH 'sudo docker exec fraud-detection-postgres-1 psql -U fraud -d fraud -c "SELECT * FROM fraud_alerts ORDER BY id DESC LIMIT 5;"'
aws s3 ls s3://$(bash infra/terraform/tf.sh output -raw s3_bucket)/reports/
```

Même déroulé possible en local (`docker/dev/`, `localhost`) si l'instance est détruite.
