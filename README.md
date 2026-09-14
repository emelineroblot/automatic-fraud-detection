# Automatic Fraud Detection

Pipeline de détection de fraude en temps réel — projet Jedha (*ETL with Airflow*).

- **Airflow 3** orchestre un DAG à la minute (collecte API → prédiction → stockage → alerte) et un DAG quotidien (rapport de la veille).
- **MLflow** stocke les expériences et sert de registry pour le modèle en production.
- **PostgreSQL** conserve les transactions, prédictions, alertes et rapports.
- **Discord** reçoit les alertes fraude et le rapport matinal.

## Prérequis

- Docker Desktop (≥ 4 Go de RAM alloués)
- Python ≥ 3.12 pour l'entraînement local
- Le dataset `fraudTest.csv` (fourni par Jedha, non versionné)

## Démarrage

```bash
# 1. Configuration
cp .env.example .env
# renseigner AIRFLOW_FERNET_KEY, AIRFLOW_JWT_SECRET et DISCORD_WEBHOOK_URL (voir commentaires du fichier)

# 2. Lancer la stack (depuis la racine du projet)
docker compose --env-file .env -f docker/dev/docker-compose.yml up -d --build

# 3. Vérifier
docker compose --env-file .env -f docker/dev/docker-compose.yml ps
```

| Service | URL | Identifiants |
|---------|-----|--------------|
| Airflow | http://localhost:8080 | `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` (défaut `airflow` / `airflow`) |
| MLflow  | http://localhost:5000 | — |
| PostgreSQL | `localhost:5432` | bases `airflow`, `mlflow`, `fraud` (mots de passe dans `.env`) |

Arrêt : `docker compose --env-file .env -f docker/dev/docker-compose.yml down` (ajouter `-v` pour supprimer les données).

## Entraînement local

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e ".[train,dev]"
python training/train.py --data contexte/fraudTest.csv   # log vers http://localhost:5000
pytest
```

## Structure

```
airflow/          DAGs, Dockerfile et dépendances de l'image Airflow
docker/dev/       docker-compose + script d'init PostgreSQL
mlflow/           Dockerfile du serveur MLflow
sql/init.sql      schéma de la base fraud
src/fraud_detection/  package partagé (features, client API, DB, modèle, notifications)
training/         script d'entraînement (log + register MLflow)
tests/            tests unitaires
docs/             livrable : schéma d'architecture et justification
```
