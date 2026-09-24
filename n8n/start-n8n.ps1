$ErrorActionPreference = "Stop"

$runtimeDir = Join-Path $PSScriptRoot "..\.jarvis_runtime"
$logPath = Join-Path $runtimeDir "n8n-autostart.log"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

function Write-StartupLog([string]$Message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    Add-Content -Path $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

Write-StartupLog "n8n launcher started."
Write-StartupLog "PowerShell: $($PSVersionTable.PSVersion)"
Write-StartupLog "Working directory: $((Get-Location).Path)"

try {
    $npxCommand = Get-Command npx.cmd -ErrorAction SilentlyContinue
    if (-not $npxCommand) {
        $npxCommand = Get-Command npx -ErrorAction SilentlyContinue
    }

    if (-not $npxCommand) {
        throw "Node.js/npm was not found. Install Node.js first, then rerun this script."
    }

    $env:N8N_HOST = "127.0.0.1"
    $env:N8N_PORT = "5678"
    $env:N8N_PROTOCOL = "http"

    Write-StartupLog "Resolved npx: $($npxCommand.Source)"
    Write-StartupLog "Starting local n8n on http://127.0.0.1:5678"
    Write-Host "Starting local n8n on http://127.0.0.1:5678"
    Write-Host "JARVIS will use this endpoint when JARVIS_N8N_ENABLED=1."

    & $npxCommand.Source --yes n8n@2.40.5 2>&1 | ForEach-Object {
        $line = $_ | Out-String
        Add-Content -Path $logPath -Value $line.TrimEnd() -Encoding UTF8
        Write-Host $_
    }

    $exitCode = $LASTEXITCODE
    Write-StartupLog "npx/n8n process exited with code $exitCode."
    exit $exitCode
}
catch {
    $errorText = ($_ | Out-String).Trim()
    Write-StartupLog "n8n launcher failed: $errorText"
    Write-Error $errorText
    exit 1
}
