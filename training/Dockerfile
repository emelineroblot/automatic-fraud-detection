# Image d'entraînement (production) : python:3.13 = version de l'image Airflow -> pickle compatible.
# Contexte de build = racine du projet.
FROM python:3.13-slim

ARG PIP_EXTRA_ARGS=""
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
COPY training/ training/
RUN pip install --no-cache-dir $PIP_EXTRA_ARGS -e ".[train]"

ENV MLFLOW_DISABLE_AGENT_HINT=1
CMD ["python", "training/train.py", "--data", "/data/fraudTest.csv"]
