# Automatic Fraud Detection

Pipeline de détection de fraude en temps réel — projet Jedha (*ETL with Airflow*).

- **Airflow 3** orchestre un DAG **à la minute** (API → prédiction → PostgreSQL → alerte Discord) et un DAG **quotidien** (rapport de la veille : Discord + CSV).
- **MLflow** trace les entraînements et sert de registry ; les DAGs chargent `models:/fraud_detection@production`.
- **PostgreSQL** conserve transactions, prédictions, alertes et rapports.
- **Streamlit** propose un dashboard par journée et le suivi de la qualité du modèle en live.

📄 Schéma et justification de l'architecture : [`docs/architecture.md`](docs/architecture.md) · Script de démo : [`docs/demo-script.md`](docs/demo-script.md)

```
API HF (1 tx/min) ─► Airflow fraud_realtime ─► PostgreSQL ─► Discord 🚨
                          ▲                        │
fraudTest.csv ─► train.py ─► MLflow registry       ├─► Airflow fraud_daily_report ─► Discord 📊 + CSV
                                                   └─► Dashboard Streamlit
```

## Prérequis

- Docker Desktop (≥ 4 Go de RAM alloués)
- Python ≥ 3.12 pour l'entraînement local
- Le dataset `fraudTest.csv` (fourni par Jedha, non versionné — à placer dans `contexte/`)
- Un webhook Discord (Paramètres du salon → Intégrations → Webhooks)

## Démarrage

```bash
# 1. Configuration
cp .env.example .env
# renseigner AIRFLOW_FERNET_KEY, AIRFLOW_JWT_SECRET, DISCORD_WEBHOOK_URL (voir les commentaires du fichier)

# 2. Lancer la stack (depuis la racine du projet)
docker compose --env-file .env -f docker/dev/docker-compose.yml up -d --build

# 3. Entraîner et publier le modèle (une fois)
python -m venv .venv && .venv/Scripts/activate      # Windows ; source .venv/bin/activate sinon
pip install -e ".[train,dev]"
python training/train.py --data contexte/fraudTest.csv

# 4. Dépauser les DAGs (ou via l'UI Airflow)
docker exec fraud-detection-airflow-scheduler-1 airflow dags unpause fraud_realtime
docker exec fraud-detection-airflow-scheduler-1 airflow dags unpause fraud_daily_report
```

| Service | URL | Identifiants |
|---------|-----|--------------|
| Airflow | http://localhost:8080 | `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` (défaut `airflow` / `airflow`) |
| MLflow  | http://localhost:5000 | — |
| Dashboard | http://localhost:8501 | — |
| PostgreSQL | `localhost:5432` (`POSTGRES_HOST_PORT`) | bases `airflow`, `mlflow`, `fraud` (mots de passe dans `.env`) |

Arrêt : `docker compose --env-file .env -f docker/dev/docker-compose.yml down` (ajouter `-v` pour supprimer les données).

## Utilisation

```bash
# Forcer une alerte (seuil à 0 pour ce run) — utile pour tester la chaîne de notification
docker exec fraud-detection-airflow-scheduler-1 airflow dags trigger fraud_realtime --conf '{"threshold_override": 0}'

# Rejouer le rapport d'une journée donnée
docker exec fraud-detection-airflow-scheduler-1 airflow dags trigger fraud_daily_report --conf '{"report_date": "2026-09-15"}'

# Essai rapide d'entraînement sans toucher au registry
python training/train.py --data contexte/fraudTest.csv --models lgbm --sample 100000 --no-register

# Tests unitaires
pytest
```

## Structure

```
airflow/dags/            fraud_realtime_dag.py (* * * * *) · fraud_daily_report_dag.py (0 6 * * *)
airflow/                 Dockerfile + requirements de l'image Airflow (deps ML alignées avec pyproject.toml)
src/fraud_detection/     package partagé : config · features · api_client · model · db · notify
training/train.py        split temporel, LogReg / RandomForest / LightGBM, log + register MLflow
mlflow/                  Dockerfile du serveur MLflow (backend PostgreSQL)
dashboard/               app Streamlit
sql/init.sql             schéma de la base fraud (transactions, fraud_alerts, daily_reports)
docker/dev/              docker-compose.yml + script d'init PostgreSQL
tests/                   tests unitaires (features, parsing API, notifications, config)
docs/                    architecture (livrable 1) + script de démo vidéo
reports/                 exports CSV du rapport quotidien
```

## Notes d'environnement

- **TLS intercepté** (antivirus/proxy d'entreprise) : si `pip` échoue en `CERTIFICATE_VERIFY_FAILED` au build, renseigner `PIP_EXTRA_ARGS` dans `.env` ; si les appels HTTPS des DAGs échouent, générer `docker/certs/ca-bundle.pem` (certifi + certificat racine de l'intercepteur) et définir `REQUESTS_CA_BUNDLE=/certs/ca-bundle.pem`.
- **Ports déjà utilisés** : `POSTGRES_HOST_PORT`, `MLFLOW_HOST_PORT`, `AIRFLOW_HOST_PORT`, `DASHBOARD_HOST_PORT` dans `.env`.
- Le script d'init PostgreSQL ne s'exécute qu'au premier démarrage (volume vide) : `down -v` pour repartir de zéro.
