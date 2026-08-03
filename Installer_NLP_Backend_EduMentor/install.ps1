param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

$InstallerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $InstallerRoot
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$BackendRoot = Join-Path $ProjectRoot "backend"
$StarterRoot = Join-Path $ProjectRoot "EduMentor_NLP_Starter_150"
$StarterModels = Join-Path $StarterRoot "models"
$BackendModels = Join-Path $BackendRoot "data\nlp_models"

if (-not (Test-Path $BackendRoot)) {
    throw "Dossier backend introuvable : $BackendRoot"
}

if (-not (Test-Path $StarterModels)) {
    throw "Dossier des modèles introuvable : $StarterModels. Lancez d'abord python src\train_all.py."
}

$JoblibFiles = Get-ChildItem $StarterModels -Filter "tfidf_logreg_*.joblib"
if ($JoblibFiles.Count -lt 5) {
    throw "Cinq modèles .joblib sont attendus dans $StarterModels."
}

Write-Host "Projet : $ProjectRoot" -ForegroundColor Cyan
Write-Host "Backend : $BackendRoot" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $BackendModels | Out-Null
Copy-Item (Join-Path $StarterModels "tfidf_logreg_*.joblib") $BackendModels -Force

Copy-Item `
    (Join-Path $InstallerRoot "files\app\services\nlp_model_service.py") `
    (Join-Path $BackendRoot "app\services\nlp_model_service.py") `
    -Force

Copy-Item `
    (Join-Path $InstallerRoot "files\app\api\nlp_routes.py") `
    (Join-Path $BackendRoot "app\api\nlp_routes.py") `
    -Force

New-Item -ItemType Directory -Force -Path (Join-Path $BackendRoot "scripts") | Out-Null
Copy-Item `
    (Join-Path $InstallerRoot "files\scripts\test_nlp_service.py") `
    (Join-Path $BackendRoot "scripts\test_nlp_service.py") `
    -Force

$MainPath = Join-Path $BackendRoot "app\main.py"
$MainContent = Get-Content -Raw $MainPath
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $MainPath "$MainPath.backup-$Timestamp"

$ImportLine = "from app.api.nlp_routes import router as nlp_router"
if ($MainContent -notmatch [regex]::Escape($ImportLine)) {
    $Anchor = "from app.api.regional_routes import router as regional_router"
    if ($MainContent.Contains($Anchor)) {
        $MainContent = $MainContent.Replace(
            $Anchor,
            "$Anchor`r`n$ImportLine"
        )
    } else {
        $MainContent = "$ImportLine`r`n$MainContent"
    }
}

$IncludeLine = 'app.include_router(nlp_router, prefix="/api")'
if ($MainContent -notmatch [regex]::Escape($IncludeLine)) {
    $Anchor = 'app.include_router(regional_router, prefix="/api")'
    if ($MainContent.Contains($Anchor)) {
        $MainContent = $MainContent.Replace(
            $Anchor,
            "$Anchor`r`n$IncludeLine"
        )
    } else {
        $MainContent = "$MainContent`r`n$IncludeLine`r`n"
    }
}

Set-Content -Path $MainPath -Value $MainContent -Encoding UTF8

$RequirementsPath = Join-Path $BackendRoot "requirements.txt"
$Requirements = Get-Content -Raw $RequirementsPath
$Needed = @(
    "scikit-learn>=1.8,<2.0",
    "joblib>=1.3",
    "pypdf>=4.0"
)

foreach ($Requirement in $Needed) {
    $PackageName = ($Requirement -split '[<>=]')[0]
    if ($Requirements -notmatch "(?im)^\s*$([regex]::Escape($PackageName))\b") {
        Add-Content -Path $RequirementsPath -Value $Requirement
    }
}

Write-Host ""
Write-Host "Installation terminée." -ForegroundColor Green
Write-Host "Modèles copiés vers : $BackendModels"
Write-Host "Router ajouté : /api/nlp"
Write-Host ""
Write-Host "Test direct :" -ForegroundColor Yellow
Write-Host "  cd `"$BackendRoot`""
Write-Host "  python scripts\test_nlp_service.py"
Write-Host ""
Write-Host "Démarrage du backend :" -ForegroundColor Yellow
Write-Host "  python -m uvicorn app.main:app --reload --port 8001"
Write-Host ""
Write-Host "Santé API : http://127.0.0.1:8001/api/nlp/health"
