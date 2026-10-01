#!/usr/bin/env bash
# Creates repo-root .env for docker compose / local runs (idempotent — never overwrites).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists — leaving it untouched. Edit it to add your NVIDIA_API_KEY."
  exit 0
fi

cat > .env <<'EOF'
# ── Required for real pipeline runs ──────────────────────────────────────
# Get a key at https://build.nvidia.com — used by the FastAPI runs endpoint
# and the Gap Challenger reranker. In the Streamlit UI you can also paste it
# in the sidebar; the API reads it from this file via the container env.
NVIDIA_API_KEY=paste-your-nvidia-key-here

# Optional: raises Semantic Scholar rate limits (works unauthenticated at low rate)
SEMANTIC_SCHOLAR_API_KEY=

# ── Local service passwords (safe dev defaults; change if exposing ports) ──
POSTGRES_PASSWORD=clinova_dev_pw
ARCADEDB_PASSWORD=clinova_arcade_dev

# ── Host-side defaults ────────────────────────────────────────────────────
# (containers override hosts with service names via docker-compose.yml;
#  these values are what you use when running pytest/scripts on the host)
POSTGRES_URL=postgresql://localhost:5433
POSTGRES_USER=clinova_app
POSTGRES_DATABASE=clinova

ARCADEDB_URL=http://localhost:2480
ARCADEDB_USER=root
ARCADEDB_DATABASE=clinova_graphs
EOF

echo "Created .env — now edit it and replace paste-your-nvidia-key-here with your real key."
