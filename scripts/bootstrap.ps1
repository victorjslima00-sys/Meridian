# Meridian Developer Bootstrap for Windows
$ErrorActionPreference = "Stop"

Write-Host "=== Meridian Developer Bootstrap (Windows x64) ===" -ForegroundColor Cyan

$expectedPython = "3.12"
try {
    $actualPython = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($actualPython -ne $expectedPython) {
        Write-Warning "Expected Python $expectedPython, found $actualPython."
    }
} catch {
    Write-Warning "Python was not found in PATH."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment in .venv..." -ForegroundColor Yellow
    python -m venv .venv
}

Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

Write-Host "Upgrading pip to pinned version..." -ForegroundColor Yellow
python -m pip install pip==25.0.1

if (Test-Path "requirements.lock") {
    Write-Host "Installing dependencies from requirements.lock..." -ForegroundColor Yellow
    pip install -r requirements.lock
} else {
    Write-Host "Installing dependencies from requirements-dev.txt..." -ForegroundColor Yellow
    pip install -r requirements-dev.txt
    if (Test-Path "requirements-mt5.txt") {
        Write-Host "Installing Windows MetaTrader 5 dependencies..." -ForegroundColor Yellow
        pip install -r requirements-mt5.txt
    }
}

Write-Host "Bootstrapping frontend..." -ForegroundColor Yellow
Set-Location frontend
cmd.exe /c "npm ci"
Set-Location ..

if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Write-Host "Creating .env template..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "⚠️ Please configure API_KEY in .env before running backend." -ForegroundColor Red
}

Write-Host "Running pre-flight test collection..." -ForegroundColor Yellow
python -m pytest tests/ --collect-only -q

Write-Host "✅ Meridian Bootstrap Complete!" -ForegroundColor Green
