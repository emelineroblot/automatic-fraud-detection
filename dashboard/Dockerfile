FROM python:3.13-slim

# Options pip supplémentaires (ex. --trusted-host derrière un antivirus/proxy qui intercepte le TLS)
ARG PIP_EXTRA_ARGS=""

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir $PIP_EXTRA_ARGS -r requirements.txt
COPY app.py .

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
