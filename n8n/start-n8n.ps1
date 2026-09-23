$ErrorActionPreference = "Stop"

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm was not found. Install Node.js first, then rerun this script."
}

$env:N8N_HOST = "127.0.0.1"
$env:N8N_PORT = "5678"
$env:N8N_PROTOCOL = "http"

Write-Host "Starting local n8n on http://127.0.0.1:5678"
Write-Host "JARVIS will use this endpoint when JARVIS_N8N_ENABLED=1."

npx --yes n8n