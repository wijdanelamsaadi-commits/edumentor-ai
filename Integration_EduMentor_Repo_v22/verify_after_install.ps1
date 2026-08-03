param(
    [string]$ProjectRoot = "C:\Users\HP\Desktop\yancode"
)

$ErrorActionPreference = "Stop"
$BackendRoot = Join-Path $ProjectRoot "backend"

Push-Location $BackendRoot
try {
    python -m compileall app scripts
    python scripts\test_nlp_runtime.py
}
finally {
    Pop-Location
}
