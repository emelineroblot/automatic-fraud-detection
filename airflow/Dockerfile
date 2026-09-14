# Contexte de build = racine du projet (voir docker/dev/docker-compose.yml)
FROM apache/airflow:3.3.1-python3.13

# libgomp1 : dépendance système de LightGBM (OpenMP)
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER airflow

# Options pip supplémentaires (ex. --trusted-host derrière un antivirus/proxy qui intercepte le TLS)
ARG PIP_EXTRA_ARGS=""

COPY airflow/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir $PIP_EXTRA_ARGS -r /tmp/requirements.txt

# Package partagé training <-> inférence ; monté en volume en dev pour le hot reload
COPY src/ /opt/airflow/src/
ENV PYTHONPATH=/opt/airflow/src
