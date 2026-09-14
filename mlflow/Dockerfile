FROM ghcr.io/mlflow/mlflow:v3.16.0

# Options pip supplémentaires (ex. --trusted-host derrière un antivirus/proxy qui intercepte le TLS)
ARG PIP_EXTRA_ARGS=""

# L'image officielle n'embarque pas le driver PostgreSQL
RUN pip install --no-cache-dir $PIP_EXTRA_ARGS psycopg2-binary==2.9.13

EXPOSE 5000
# --allowed-hosts : MLflow 3 rejette les requêtes dont le Host n'est pas localhost (protection DNS rebinding) ;
# les containers Airflow l'appellent via http://mlflow:5000
CMD mlflow server \
    --backend-store-uri "${MLFLOW_BACKEND_STORE_URI}" \
    --artifacts-destination /mlflow/artifacts \
    --serve-artifacts \
    --allowed-hosts "${MLFLOW_ALLOWED_HOSTS:-*}" \
    --host 0.0.0.0 --port 5000
