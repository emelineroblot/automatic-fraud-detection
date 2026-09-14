#!/bin/bash
# Exécuté une seule fois par l'image postgres au premier démarrage (volume vide).
# Crée les 3 bases + rôles : airflow (métadonnées), mlflow (tracking), fraud (warehouse).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE airflow LOGIN PASSWORD '${AIRFLOW_DB_PASSWORD}';
    CREATE DATABASE airflow OWNER airflow;

    CREATE ROLE mlflow LOGIN PASSWORD '${MLFLOW_DB_PASSWORD}';
    CREATE DATABASE mlflow OWNER mlflow;

    CREATE ROLE fraud LOGIN PASSWORD '${FRAUD_DB_PASSWORD}';
    CREATE DATABASE fraud OWNER fraud;
EOSQL

psql -v ON_ERROR_STOP=1 --username fraud --dbname fraud -f /sql/init.sql
