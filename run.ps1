$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$projectPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $projectPython)) {
    Write-Host "Project environment missing. Run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting Video Caption Generator..." -ForegroundColor Cyan

& $projectPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000