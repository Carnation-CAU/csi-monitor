param(
    [Parameter(Mandatory = $true)][string]$Port
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project virtual environment was not found. Run scripts\bootstrap.ps1 first."
}

Set-Location $ProjectRoot
& $Python -m csi_gateway monitor --port $Port --baud 2000000 --project-root $ProjectRoot
