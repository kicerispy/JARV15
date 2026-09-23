$ErrorActionPreference = "Stop"

$settings = @{
    "JARVIS_N8N_ENABLED" = "1"
    "JARVIS_N8N_BASE_URL" = "http://127.0.0.1:5678"
    "JARVIS_N8N_WEBHOOK_PATH" = "webhook/jarvis-gateway"
}

foreach ($entry in $settings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "User")
    Set-Item -Path ("Env:" + $entry.Key) -Value $entry.Value
}

Write-Host "JARVIS n8n delegation enabled."
Write-Host "n8n endpoint: $env:JARVIS_N8N_BASE_URL/$env:JARVIS_N8N_WEBHOOK_PATH"
Write-Host "Restart JARVIS after changing these settings."