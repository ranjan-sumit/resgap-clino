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
# Get a key at https://build.nvidia.com — used by the Gap Challenger reranker.
# In the Streamlit UI you can also paste it in the sidebar.
NVIDIA_API_KEY=paste-your-nvidia-key-here

# Optional: raises Semantic Scholar rate limits (works unauthenticated at low rate)
SEMANTIC_SCHOLAR_API_KEY=

# Optional: other model providers (Provider dropdown in the sidebar)
GEMINI_API_KEY=

# Optional: SQLite file for run history + graph snapshots (default data/run_history.db)
# RESGAP_DB_PATH=
EOF

echo "Created .env — now edit it and replace paste-your-nvidia-key-here with your real key."
