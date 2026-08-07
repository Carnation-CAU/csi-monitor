$ErrorActionPreference = "Stop"

# 설치 경로는 PC마다 다르므로 환경 변수로 덮어쓸 수 있게 둔다.
#   $env:CSI_PYTHON312_PATH  Python 3.12 설치 폴더
#   $env:IDF_PATH            ESP-IDF v5.0.2 설치 폴더
#   $env:IDF_TOOLS_PATH      ESP-IDF 도구 폴더
$Python312 = if ($env:CSI_PYTHON312_PATH) {
    $env:CSI_PYTHON312_PATH
} else {
    Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"
}

$IdfRoot = if ($env:IDF_PATH) {
    $env:IDF_PATH
} else {
    Join-Path $env:USERPROFILE "esp\esp-idf-v5.0.2"
}

if (-not $env:IDF_TOOLS_PATH) {
    $env:IDF_TOOLS_PATH = Join-Path $env:USERPROFILE ".espressif"
}

$IdfExport = Join-Path $IdfRoot "export.ps1"

if (-not (Test-Path -LiteralPath (Join-Path $Python312 "python.exe"))) {
    throw @"
Python 3.12를 찾지 못했습니다: $Python312
다른 경로에 설치했다면 다음처럼 지정하세요.
  `$env:CSI_PYTHON312_PATH = 'D:\Python312'
"@
}

if (-not (Test-Path -LiteralPath $IdfExport)) {
    throw @"
ESP-IDF v5.0.2를 찾지 못했습니다: $IdfExport
다른 경로에 설치했다면 다음처럼 지정하세요.
  `$env:IDF_PATH = 'D:\esp\esp-idf-v5.0.2'
"@
}

$env:Path = "$Python312;$Python312\Scripts;$env:Path"
. $IdfExport

Write-Host "ESP-IDF v5.0.2 / Python 3.12 환경이 활성화되었습니다."
