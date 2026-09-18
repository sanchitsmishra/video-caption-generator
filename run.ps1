$ErrorActionPreference = "Stop"

$projectPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $projectPython)) {
    throw "Setup is not complete. Run .\setup.ps1 first."
}

& $projectPython -m uvicorn app.main:app --reload
