param(
    [Parameter(Mandatory = $true)][string]$Port,
    [string]$ActivityModel = "",
    [double]$ActivityHz = 5
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DefaultActivityModel = Join-Path $ProjectRoot "ml\v_main\model.pt"
if (-not $ActivityModel) {
    $ActivityModel = $DefaultActivityModel
}

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
    "--activity-model", $ActivityModel
)
& $Python @Arguments
