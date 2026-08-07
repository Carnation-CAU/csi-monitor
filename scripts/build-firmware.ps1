$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "activate-idf.ps1")

$Projects = @(
    (Join-Path $ProjectRoot "third_party\esp-csi\examples\get-started\csi_send"),
    (Join-Path $ProjectRoot "third_party\esp-csi\examples\esp-radar\console_test")
)

foreach ($Project in $Projects) {
    Push-Location $Project
    try {
        idf.py set-target esp32s3
        if ($LASTEXITCODE -ne 0) {
            throw "Target 설정 실패: $Project"
        }
        idf.py build
        if ($LASTEXITCODE -ne 0) {
            throw "빌드 실패: $Project"
        }
    } finally {
        Pop-Location
    }
}

Write-Host "송신기와 수신기 펌웨어 빌드가 완료되었습니다."
