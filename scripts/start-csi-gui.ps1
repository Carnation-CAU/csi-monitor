param(
    [Parameter(Mandatory = $true)][string]$Port
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ToolDirectory = Join-Path $ProjectRoot "third_party\esp-csi\examples\esp-radar\console_test\tools"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "프로젝트 가상환경이 없습니다. scripts\bootstrap.ps1을 먼저 실행하세요."
}

Set-Location $ToolDirectory
& $Python esp_csi_tool.py -p $Port
