param(
    [Parameter(Mandatory = $true)][string]$Port,
    [string]$ActivityModel = "",
    [double]$ActivityHz = 20,
    [int]$ActivityWindowFrames = 950
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project virtual environment was not found. Run scripts\bootstrap.ps1 first."
}

Set-Location $ProjectRoot
$Arguments = @(
    "-m", "csi_gateway", "monitor",
    "--port", $Port,
    "--baud", "2000000",
    "--project-root", $ProjectRoot,
    "--activity-hz", $ActivityHz,
    "--activity-window-frames", $ActivityWindowFrames
)
if ($ActivityModel) {
    $Arguments += @("--activity-model", $ActivityModel)
}
& $Python @Arguments
