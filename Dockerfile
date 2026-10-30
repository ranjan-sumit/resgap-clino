# The app as a self-contained image. It contains the code and the pinned dependencies; the data lives in a volume at /data.
#
#   docker build -t clinova:local .
#   docker run --rm -p 127.0.0.1:8501:8501 --env-file .env -v clinova-data:/data clinova:local
#
# (docker-compose.yml wraps this with the hardening options. docker-compose.dev.yml mounts the code for development.)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    RESGAP_DB_PATH=/data/run_history.db \
    RESGAP_PROJECTS_DIR=/data/projects \
    RESGAP_BACKUP_DIR=/data/backups \
    RESGAP_HIDE_PATHS=1

# The app runs as an ordinary user, never as root.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app \
 && mkdir -p /data \
 && chown app:app /data

WORKDIR /app

# Dependencies first (cached unless the lock changes): exact versions, every file checked against its recorded hash.
COPY requirements-runtime.lock ./
RUN pip install --require-hashes -r requirements-runtime.lock

# The code. Owned by root and read-only to the app user; what .dockerignore leaves out (.env, data, tests, docs) is not in the image.
COPY . .

USER app
VOLUME ["/data"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"]

# Cross-site request protection and CORS stay at Streamlit's defaults (on). Put TLS and sign-in in front of this port.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
