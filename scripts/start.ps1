# Starts the backend (uvicorn, port 8000) and the Flutter web frontend (Chrome).
# Usage (from the repository root):   .\scripts\start.ps1
# Stop with Ctrl+C in this window (or press q in the Flutter console); the backend stops too.
param(
    [int]$BackendPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Backend environment not found. Create it once with:" -ForegroundColor Yellow
    Write-Host "  python -m venv backend\.venv"
    Write-Host "  backend\.venv\Scripts\python -m pip install -r backend\requirements.txt"
    exit 1
}
if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    Write-Host "Flutter is not on the PATH. Install Flutter (stable channel) first." -ForegroundColor Yellow
    exit 1
}

$backendUrl = "http://localhost:$BackendPort"
Write-Host "Starting backend on $backendUrl ..." -ForegroundColor Cyan
$backend = Start-Process -FilePath $python -PassThru -NoNewWindow -ArgumentList @(
    "-m", "uvicorn", "app.main:create_app", "--factory",
    "--app-dir", (Join-Path $root "backend"),
    "--host", "127.0.0.1", "--port", "$BackendPort"
)

try {
    Push-Location (Join-Path $root "frontend")
    Write-Host "Starting the Flutter web app (Chrome, port $WebPort) ..." -ForegroundColor Cyan
    flutter run -d chrome --web-port $WebPort --dart-define=BACKEND_URL=$backendUrl
}
finally {
    Pop-Location
    if ($backend -and -not $backend.HasExited) {
        Write-Host "Stopping backend ..." -ForegroundColor Cyan
        Stop-Process -Id $backend.Id -Force
    }
}
