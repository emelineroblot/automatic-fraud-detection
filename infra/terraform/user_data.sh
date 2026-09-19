#!/usr/bin/env bash
# cloud-init : installe Docker, clone le dépôt, initialise RDS, entraîne le modèle, démarre la stack.
# Journal : /var/log/fraud-bootstrap.log
# Fichier rendu par templatefile() : les variables Terraform sont interpolées, le reste est du bash.
set -euxo pipefail
exec > >(tee -a /var/log/fraud-bootstrap.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git gnupg postgresql-client unzip

# ─── AWS CLI v2 (téléchargement du dataset depuis S3 via le rôle d'instance) ───
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp && /tmp/aws/install

# ─── Docker Engine + compose plugin ───
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ubuntu

# ─── Dépôt ───
APP=/opt/fraud
mkdir -p $APP
git clone --branch "${repo_ref}" --depth 1 "${repo_url}" $APP

# ─── Secrets (uniquement sur l'instance, jamais dans le dépôt) ───
cat > $APP/.env <<EOF
AIRFLOW_UID=50000
PGHOST=${rds_host}
AIRFLOW_DB_PASSWORD=${db_airflow_password}
MLFLOW_DB_PASSWORD=${db_mlflow_password}
FRAUD_DB_PASSWORD=${db_fraud_password}
AIRFLOW_FERNET_KEY=${airflow_fernet_key}
AIRFLOW_JWT_SECRET=${airflow_jwt_secret}
AIRFLOW_ADMIN_USER=${airflow_admin_user}
AIRFLOW_ADMIN_PASSWORD=${airflow_admin_pass}
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_MODEL_NAME=fraud_detection
MLFLOW_MODEL_ALIAS=production
MLFLOW_ARTIFACTS_DESTINATION=s3://${s3_bucket}/mlflow-artifacts
FRAUD_API_URL=https://sdacelo-real-time-fraud-detection.hf.space/current-transactions
FRAUD_THRESHOLD=${fraud_threshold}
REPORT_TIMEZONE=${report_timezone}
DISCORD_WEBHOOK_URL=${discord_webhook_url}
REPORTS_S3_BUCKET=${s3_bucket}
AWS_DEFAULT_REGION=${aws_region}
EOF
chmod 600 $APP/.env

# ─── RDS : rôles + bases (idempotent) + schéma fraud ───
export PGPASSWORD='${rds_master_password}'
PSQL="psql -h ${rds_host} -U ${rds_master_user} -d postgres -v ON_ERROR_STOP=1"
for i in $(seq 1 30); do $PSQL -c "select 1" >/dev/null 2>&1 && break; sleep 10; done

create_db() {  # $1 = nom (rôle et base), $2 = mot de passe
  $PSQL <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$1') THEN
    CREATE ROLE "$1" LOGIN PASSWORD '$2';
  END IF;
END \$\$;
GRANT "$1" TO ${rds_master_user};
SQL
  $PSQL -tAc "SELECT 1 FROM pg_database WHERE datname = '$1'" | grep -q 1 || $PSQL -c "CREATE DATABASE \"$1\" OWNER \"$1\""
}
create_db airflow '${db_airflow_password}'
create_db mlflow  '${db_mlflow_password}'
create_db fraud   '${db_fraud_password}'
PGPASSWORD='${db_fraud_password}' psql -h ${rds_host} -U fraud -d fraud -v ON_ERROR_STOP=1 -f $APP/sql/init.sql
unset PGPASSWORD

# ─── Dataset d'entraînement depuis S3 ───
mkdir -p $APP/data
aws s3 cp "s3://${s3_bucket}/${dataset_key}" $APP/data/fraudTest.csv

# ─── Permissions pour l'UID airflow des conteneurs ───
mkdir -p $APP/airflow/logs $APP/reports
chown -R 50000:0 $APP
chmod -R g+rwX $APP

# ─── Stack ───
cd $APP
COMPOSE="docker compose --env-file .env -f docker/prod/docker-compose.yml"
$COMPOSE build
$COMPOSE up -d

# MLflow prêt -> entraînement + enregistrement du modèle (alias production)
for i in $(seq 1 60); do curl -fs http://localhost:5000/health >/dev/null 2>&1 && break; sleep 5; done
$COMPOSE --profile train run --rm training

# Airflow prêt -> dépause des DAGs
for i in $(seq 1 60); do curl -fs http://localhost:8080/api/v2/monitor/health >/dev/null 2>&1 && break; sleep 5; done
sleep 30   # laisser le dag-processor parser les DAGs
$COMPOSE exec -T airflow-scheduler airflow dags unpause fraud_realtime || true
$COMPOSE exec -T airflow-scheduler airflow dags unpause fraud_daily_report || true

echo "bootstrap terminé : $(date -u)"
