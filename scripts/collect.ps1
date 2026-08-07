param(
    [Parameter(Mandatory = $true)][string]$Port,
    [string]$Label = "unlabeled",
    [int]$Duration = 120,
    [string]$DeviceId = "rx-s3-001",
    [string]$RoomId = "room-01"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPython = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} elseif (Test-Path ".\.venv\bin\python.exe") {
    ".\.venv\bin\python.exe"
} else {
    throw "가상환경이 없습니다. 먼저 scripts\bootstrap.ps1을 실행하세요."
}

& $VenvPython -m csi_gateway collect `
    --port $Port `
    --baud 2000000 `
    --label $Label `
    --duration $Duration `
    --device-id $DeviceId `
    --room-id $RoomId `
    --project-root $ProjectRoot
