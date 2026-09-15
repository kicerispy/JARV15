# JARVIS - Run without PowerShell window
# This script starts JARVIS hidden and exits immediately

$pythonPath = if (Test-Path "jarvis_cuda\Scripts\python.exe") {
    "jarvis_cuda\Scripts\python.exe"
} else {
    "python"
}

$mainScript = Join-Path $PSScriptRoot "run_jarvis.py"

# Start Python without showing a console window
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pythonPath
$psi.Arguments = "`"$mainScript`""
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal
$psi.CreateNoWindow = $false
$psi.UseShellExecute = $false

[System.Diagnostics.Process]::Start($psi) | Out-Null