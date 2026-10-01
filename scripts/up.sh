#!/usr/bin/env bash
# One-shot bring-up: create .env if missing, validate, build, start, wait for healthchecks.
# Usage: bash scripts/up.sh            (from anywhere; cd's to repo root itself)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  bash scripts/make_dotenv.sh
  echo ""
  echo "⚠  .env was just created with a PLACEHOLDER NVIDIA_API_KEY."
  echo "   Edit .env now if you want real pipeline runs, then re-run: bash scripts/up.sh"
  echo "   (The stack itself will still start without a key.)"
  echo ""
fi

docker compose config --quiet
echo "▶ Building and starting (first run downloads a lot — docling/torch + Next.js build)…"
docker compose up -d --build --wait
echo ""
echo "✔ Stack is up:"
docker compose ps
echo ""
echo "  Web UI:      http://localhost:3000"
echo "  Streamlit:   http://localhost:8501"
echo "  API docs:    http://localhost:8000/docs"
