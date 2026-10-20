$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$projectPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"

Write-Host "`nChecking project environment..." -ForegroundColor Cyan

$repair = $false

if (-not (Test-Path $projectPython)) {
    $repair = $true
    Write-Host "Environment not found. Creating a new one..." -ForegroundColor Yellow
}
else {
    Write-Host "Checking installed packages..." -ForegroundColor Cyan

    & $projectPython -c "import fastapi, uvicorn, numpy, cv2, torch, torchvision, transformers, ultralytics, pydantic, pydantic_core; assert int(numpy.__version__.split('.')[0]) == 2 and int(numpy.__version__.split('.')[1]) < 3"

    if ($LASTEXITCODE -ne 0) {
        $repair = $true
        Write-Host "Environment is broken. Repairing it..." -ForegroundColor Yellow
    }
}

if ($repair) {
    if (Test-Path (Join-Path $PSScriptRoot ".venv")) {
        Remove-Item -Recurse -Force (Join-Path $PSScriptRoot ".venv")
    }

    & py -3.13 -m venv .venv

    if ($LASTEXITCODE -ne 0) {
        throw "Could not create Python environment. Check Python 3.13 installation."
    }

    $projectPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

    & $projectPython -m pip install --upgrade pip

    if ($LASTEXITCODE -ne 0) {
        throw "Could not upgrade pip."
    }

    & $projectPython -m pip install -r $requirements

    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed. Check the error above."
    }
}
else {
    Write-Host "Environment is healthy. Checking requirements..." -ForegroundColor Green

    & $projectPython -m pip install -r $requirements

    if ($LASTEXITCODE -ne 0) {
        throw "Dependency check failed. Review the error above."
    }
}

Write-Host "`nSetup complete! Run the project using .\run.ps1" -ForegroundColor Green