param(
    [string]$ProjectRoot = "C:\Users\HP\Desktop\yancode",
    [switch]$InstallAllDependencies
)

$ErrorActionPreference = "Stop"

$BackendRoot = Join-Path $ProjectRoot "backend"
$TestScript = Join-Path $BackendRoot "scripts\test_nlp_runtime.py"
$MainFile = Join-Path $BackendRoot "app\main.py"
$RequirementsFile = Join-Path $BackendRoot "requirements.txt"

if (-not (Test-Path $MainFile)) {
    throw "Backend introuvable: $MainFile"
}

if (-not (Test-Path $TestScript)) {
    throw "Test NLP introuvable: $TestScript"
}

Write-Host "Backend détecté: $BackendRoot" -ForegroundColor Cyan

# Corrige définitivement l'import de app lorsque le script est lancé directement.
$TestContent = Get-Content $TestScript -Raw
$Marker = "EDUMENTOR_V22_PATH_FIX"
if ($TestContent -notmatch $Marker) {
    $PathFix = @'
# EDUMENTOR_V22_PATH_FIX
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

'@
    Set-Content `
        -Path $TestScript `
        -Value ($PathFix + $TestContent) `
        -Encoding UTF8
    Write-Host "Import path corrigé dans test_nlp_runtime.py"
}
else {
    Write-Host "Import path déjà corrigé."
}

Push-Location $BackendRoot
try {
    $env:PYTHONPATH = $BackendRoot
    $env:PIP_DEFAULT_TIMEOUT = "1000"

    Write-Host ""
    Write-Host "Installation des dépendances NLP minimales..." -ForegroundColor Cyan

    python -m pip install `
        --disable-pip-version-check `
        --prefer-binary `
        --retries 10 `
        --default-timeout 1000 `
        "scikit-learn>=1.8,<2.0" `
        "joblib>=1.4" `
        "numpy>=2.0" `
        "scipy>=1.13"

    if ($LASTEXITCODE -ne 0) {
        throw "Installation des dépendances NLP échouée."
    }

    if ($InstallAllDependencies) {
        Write-Host ""
        Write-Host "Installation de toutes les dépendances du backend..." -ForegroundColor Cyan

        python -m pip install `
            --disable-pip-version-check `
            --prefer-binary `
            --retries 10 `
            --default-timeout 1000 `
            -r requirements.txt

        if ($LASTEXITCODE -ne 0) {
            throw "Installation complète des dépendances échouée."
        }
    }

    Write-Host ""
    Write-Host "Compilation..." -ForegroundColor Cyan
    python -m compileall app scripts
    if ($LASTEXITCODE -ne 0) {
        throw "compileall a échoué."
    }

    Write-Host ""
    Write-Host "Test du runtime NLP..." -ForegroundColor Cyan
    python .\scripts\test_nlp_runtime.py
    if ($LASTEXITCODE -ne 0) {
        throw "Le test NLP a échoué."
    }

    Write-Host ""
    Write-Host "Vérification de l'application FastAPI..." -ForegroundColor Cyan
    python -c "from app.main import app; print('FASTAPI APP IMPORT OK:', app.title)"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning @"
Le runtime NLP fonctionne, mais l'import du backend complet a échoué.
Relance ensuite ce script avec:
.\repair_integration_v22_1.ps1 -InstallAllDependencies
"@
    }
    else {
        Write-Host ""
        Write-Host "REPARATION NLP V22.1 TERMINEE" -ForegroundColor Green
        Write-Host "Tu peux démarrer le backend avec:"
        Write-Host "cd `"$BackendRoot`""
        Write-Host "python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8135"
        Write-Host ""
        Write-Host "Swagger: http://127.0.0.1:8135/docs"
    }
}
finally {
    Pop-Location
}
