FROM ghcr.io/mlflow/mlflow:v3.16.0

# Options pip supplémentaires (ex. --trusted-host derrière un antivirus/proxy qui intercepte le TLS)
ARG PIP_EXTRA_ARGS=""

# psycopg2 : backend PostgreSQL ; boto3 : artefacts sur S3 en production (rôle d'instance EC2)
RUN pip install --no-cache-dir $PIP_EXTRA_ARGS psycopg2-binary==2.9.13 boto3

EXPOSE 5000
# --allowed-hosts : MLflow 3 rejette les requêtes dont le Host n'est pas localhost (protection DNS rebinding) ;
# les containers Airflow l'appellent via http://mlflow:5000
# --cors-allowed-origins : MLflow 3 bloque aussi les POST du navigateur (CSRF) si l'Origin n'est pas localhost
# -> l'UI ouverte via l'IP publique affiche "You do not have permission to access this resource"
# --artifacts-destination : volume local en dev, s3://bucket/prefix en prod
CMD mlflow server \
    --backend-store-uri "${MLFLOW_BACKEND_STORE_URI}" \
    --artifacts-destination "${MLFLOW_ARTIFACTS_DESTINATION:-/mlflow/artifacts}" \
    --serve-artifacts \
    --allowed-hosts "${MLFLOW_ALLOWED_HOSTS:-*}" \
    --cors-allowed-origins "${MLFLOW_CORS_ALLOWED_ORIGINS:-*}" \
    --host 0.0.0.0 --port 5000
