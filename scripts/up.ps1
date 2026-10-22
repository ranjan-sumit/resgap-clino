# One-shot bring-up (PowerShell): create .env if missing, validate, build, start, wait for healthchecks.
# Usage: powershell -File scripts/up.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .env)) {
  powershell -File scripts/make_dotenv.ps1
  Write-Output ''
  Write-Output "WARNING: .env was just created with a PLACEHOLDER NVIDIA_API_KEY."
  Write-Output "Edit .env now if you want real pipeline runs, then re-run: powershell -File scripts/up.ps1"
  Write-Output "(The stack itself will still start without a key.)"
  Write-Output ''
}

docker compose config --quiet
Write-Output "Building and starting (first run installs the Python deps)..."
docker compose up -d --build --wait
Write-Output ''
Write-Output "Stack is up:"
docker compose ps
Write-Output ''
Write-Output "  Streamlit:   http://localhost:8501"
