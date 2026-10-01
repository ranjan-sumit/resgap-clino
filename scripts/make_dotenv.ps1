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

# Local service passwords (safe dev defaults; change if exposing ports)
POSTGRES_PASSWORD=clinova_dev_pw
ARCADEDB_PASSWORD=clinova_arcade_dev

# Host-side defaults (containers override hosts via docker-compose.yml)
POSTGRES_URL=postgresql://localhost:5433
POSTGRES_USER=clinova_app
POSTGRES_DATABASE=clinova

ARCADEDB_URL=http://localhost:2480
ARCADEDB_USER=root
ARCADEDB_DATABASE=clinova_graphs
'@ | Out-File -Encoding utf8 .env

Write-Output 'Created .env — now edit it and replace paste-your-nvidia-key-here with your real key.'
