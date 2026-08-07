param(
    [Parameter(Mandatory = $true)][string]$Port
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "activate-idf.ps1")

Set-Location (Join-Path $ProjectRoot "third_party\esp-csi\examples\esp-radar\console_test")
idf.py -p $Port -b 460800 flash
if ($LASTEXITCODE -ne 0) {
    throw "수신기 플래시에 실패했습니다: $Port"
}
