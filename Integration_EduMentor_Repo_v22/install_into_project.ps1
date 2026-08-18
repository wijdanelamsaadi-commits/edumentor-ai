param(
    [string]$ProjectRoot = "C:\Users\HP\Desktop\yancode",
    [switch]$InstallDependencies
)

$ErrorActionPreference = "Stop"

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PayloadRoot = Join-Path $PackageRoot "payload"

$BackendRoot = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$MainFile = Join-Path $BackendRoot "app\main.py"
$RequirementsFile = Join-Path $BackendRoot "requirements.txt"

if (-not (Test-Path $MainFile)) {
    throw "Projet EduMentor introuvable: $MainFile"
}

if (-not (Test-Path $RequirementsFile)) {
    throw "requirements.txt introuvable: $RequirementsFile"
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupRoot = Join-Path $ProjectRoot "_backup_nlp_v22_$Timestamp"
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

Copy-Item $MainFile (Join-Path $BackupRoot "main.py") -Force
Copy-Item $RequirementsFile (Join-Path $BackupRoot "requirements.txt") -Force

$ExistingNlpApi = Join-Path $FrontendRoot "src\services\nlpApi.js"
if (Test-Path $ExistingNlpApi) {
    Copy-Item $ExistingNlpApi (Join-Path $BackupRoot "nlpApi.js") -Force
}

Write-Host "Backup créé: $BackupRoot"

Copy-Item `
    (Join-Path $PayloadRoot "backend\app\nlp_runtime") `
    (Join-Path $BackendRoot "app") `
    -Recurse -Force

Copy-Item `
    (Join-Path $PayloadRoot "backend\app\api\nlp_routes.py") `
    (Join-Path $BackendRoot "app\api\nlp_routes.py") `
    -Force

New-Item `
    -ItemType Directory `
    -Force `
    -Path (Join-Path $BackendRoot "scripts") | Out-Null

Copy-Item `
    (Join-Path $PayloadRoot "backend\scripts\test_nlp_runtime.py") `
    (Join-Path $BackendRoot "scripts\test_nlp_runtime.py") `
    -Force

New-Item `
    -ItemType Directory `
    -Force `
    -Path (Join-Path $FrontendRoot "src\services") | Out-Null

Copy-Item `
    (Join-Path $PayloadRoot "frontend\src\services\nlpApi.js") `
    (Join-Path $FrontendRoot "src\services\nlpApi.js") `
    -Force

$MainContent = Get-Content $MainFile -Raw

$ImportLine = "from app.api.nlp_routes import router as nlp_router"
if ($MainContent -notmatch [regex]::Escape($ImportLine)) {
    $Anchor = "from app.api.admin_routes import router as admin_router"
    if ($MainContent -match [regex]::Escape($Anchor)) {
        $MainContent = $MainContent.Replace(
            $Anchor,
            "$Anchor`r`n$ImportLine"
        )
    }
    else {
        $MainContent = "$ImportLine`r`n$MainContent"
    }
}

$IncludeLine = 'app.include_router(nlp_router, prefix="/api")'
if ($MainContent -notmatch [regex]::Escape($IncludeLine)) {
    $MainContent = $MainContent.TrimEnd() + "`r`n$IncludeLine`r`n"
}

Set-Content -Path $MainFile -Value $MainContent -Encoding UTF8

$Requirements = Get-Content $RequirementsFile
$Needed = @(
    "scikit-learn==1.8.0",
    "numpy>=2.0",
    "scipy>=1.13",
    "joblib>=1.4"
)

foreach ($Dependency in $Needed) {
    $PackageName = ($Dependency -split '[<>=]')[0]
    $AlreadyExists = $Requirements | Where-Object {
        $_ -match ("^" + [regex]::Escape($PackageName) + "([<>=].*)?$")
    }
    if (-not $AlreadyExists) {
        Add-Content -Path $RequirementsFile -Value $Dependency
        $Requirements += $Dependency
    }
}

Push-Location $BackendRoot
try {
    if ($InstallDependencies) {
        python -m pip install -r requirements.txt
    }

    python -m compileall app scripts
    if ($LASTEXITCODE -ne 0) {
        throw "compileall a échoué."
    }

    python scripts\test_nlp_runtime.py
    if ($LASTEXITCODE -ne 0) {
        throw "Le test NLP a échoué."
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "INTEGRATION NLP V22 TERMINEE" -ForegroundColor Green
Write-Host "Backend: $BackendRoot"
Write-Host "Frontend service: $ExistingNlpApi"
Write-Host "Backup: $BackupRoot"
Write-Host ""
Write-Host "Démarrage backend:"
Write-Host "cd `"$BackendRoot`""
Write-Host "python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8135"
Write-Host ""
Write-Host "Swagger: http://127.0.0.1:8135/docs"
