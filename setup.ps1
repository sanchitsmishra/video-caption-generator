$ErrorActionPreference = "Stop"

Write-Host "Creating the project Python environment..." -ForegroundColor Cyan
& py -3.13 -m venv .venv

$projectPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Write-Host "Installing the app dependencies. This can take a few minutes..." -ForegroundColor Cyan
& $projectPython -m pip install --upgrade pip
& $projectPython -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "Setup complete. Start the app with .\run.ps1" -ForegroundColor Green
