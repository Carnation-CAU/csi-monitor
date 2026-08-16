param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("tx", "rx")]
    [string]$Role,
    [Parameter(Mandatory = $true)]
    [string]$Port
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw ".venv가 없습니다. 먼저 .\scripts\bootstrap.ps1을 실행하세요."
}

Set-Location $ProjectRoot
Write-Host "대상 역할: $($Role.ToUpper())"
Write-Host "대상 포트: $Port"
Write-Host "펌웨어: ESP32-S3 / HT20 / 기본 채널 6 / TX 100Hz"

if ($Role -eq "tx") {
    & $Python -m esptool --chip esp32s3 -p $Port -b 460800 write-flash `
        --flash-mode dio --flash-freq 80m --flash-size 2MB `
        0x0 firmware\prebuilt\tx\bootloader.bin `
        0x8000 firmware\prebuilt\tx\partition-table.bin `
        0x10000 firmware\prebuilt\tx\csi_send.bin
} else {
    & $Python -m esptool --chip esp32s3 -p $Port -b 460800 write-flash `
        --flash-mode dio --flash-freq 80m --flash-size 4MB `
        0x0 firmware\prebuilt\rx\bootloader.bin `
        0x8000 firmware\prebuilt\rx\partition-table.bin `
        0x1d000 firmware\prebuilt\rx\ota_data_initial.bin `
        0x20000 firmware\prebuilt\rx\console_test.bin
}

if ($LASTEXITCODE -ne 0) {
    throw "$($Role.ToUpper()) 플래시에 실패했습니다: $Port"
}
Write-Host "$($Role.ToUpper()) 플래시와 쓰기 검증이 완료되었습니다."
