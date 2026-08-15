# Start AETHER: API on :8000, web on :3000.
#
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
#
# Runs entirely offline in replay mode. No API key, no network.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "  AETHER - starting" -ForegroundColor Cyan
Write-Host "  ------------------------------------------------------------"

# Free the ports if a previous run is still holding them.
foreach ($port in 8000, 3000) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($owner in $owners) {
        Write-Host "  freeing port $port (pid $($owner.OwningProcess))" -ForegroundColor DarkGray
        try { Stop-Process -Id $owner.OwningProcess -Force -ErrorAction Stop } catch {}
    }
}

$env:PYTHONPATH = Join-Path $root "backend"
if (-not $env:AETHER_MODE) { $env:AETHER_MODE = "replay" }

Write-Host "  mode      $env:AETHER_MODE"
Write-Host "  api       http://127.0.0.1:8000/docs"
Write-Host "  web       http://127.0.0.1:3000"
Write-Host ""

$api = Start-Process -PassThru -NoNewWindow python `
    -ArgumentList "-m", "uvicorn", "aether.api.main:app", "--host", "127.0.0.1", "--port", "8000"

Start-Sleep -Seconds 3

try {
    Push-Location (Join-Path $root "frontend")
    npm run dev -- --port 3000
}
finally {
    Pop-Location
    if ($api -and -not $api.HasExited) {
        Write-Host "  stopping API" -ForegroundColor DarkGray
        Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    }
}
