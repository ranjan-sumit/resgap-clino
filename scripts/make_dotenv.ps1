# Creates repo-root .env for docker compose / local runs (idempotent — never overwrites).
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

if (Test-Path .env) {
  Write-Output '.env already exists — leaving it untouched. Edit it to add your NVIDIA_API_KEY.'
  exit 0
}

@'
# Required for real pipeline runs — get a key at https://build.nvidia.com
NVIDIA_API_KEY=paste-your-nvidia-key-here

# Optional: raises Semantic Scholar rate limits (works unauthenticated at low rate)
SEMANTIC_SCHOLAR_API_KEY=

# Optional: other model providers (Provider dropdown in the sidebar)
GEMINI_API_KEY=

# Optional: SQLite file for run history + graph snapshots (default data/run_history.db)
# RESGAP_DB_PATH=
'@ | Out-File -Encoding utf8 .env

Write-Output 'Created .env — now edit it and replace paste-your-nvidia-key-here with your real key.'
