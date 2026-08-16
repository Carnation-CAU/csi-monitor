$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# 검증된 버전을 먼저 쓰되, 없으면 pyproject의 requires-python(>=3.10)을 만족하는
# 다른 버전으로 진행한다. 새 PC에 3.13/3.14만 설치된 경우에도 멈추지 않는다.
$PreferredVersions = @("3.12", "3.13", "3.14", "3.11", "3.10")
$PythonCommand = $null

if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($Version in $PreferredVersions) {
        try {
            & py "-$Version" -c "import sys" 2>$null
        } catch {
            continue
        }
        if ($LASTEXITCODE -eq 0) {
            $PythonCommand = @("py", "-$Version")
            break
        }
    }
}

if (-not $PythonCommand -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $PythonExecutable = & python -c "import sys; print(sys.executable)"
    if ($PythonExecutable -match "[\\/]msys64[\\/]") {
        throw "현재 MSYS Python은 한글 프로젝트 경로의 가상환경을 실행하지 못합니다. python.org의 Windows용 Python 3.10 이상을 설치하고 'Add python.exe to PATH'를 선택하세요."
    }
    $VersionOk = & python -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)"
    if ($VersionOk.Trim() -ne "1") {
        $Found = & python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        throw "Python 3.10 이상이 필요합니다. 현재: $Found"
    }
    $PythonCommand = @("python")
}

if (-not $PythonCommand) {
    throw "Python 3.10 이상을 찾지 못했습니다. python.org에서 Windows용 Python을 설치하고 'Add python.exe to PATH'를 선택하세요. 검증된 버전은 3.12입니다."
}

$SelectedVersion = & $PythonCommand[0] $PythonCommand[1..($PythonCommand.Count - 1)] -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Host "사용할 Python: $($SelectedVersion.Trim())"
if (-not $SelectedVersion.Trim().StartsWith("3.12")) {
    Write-Host "참고: 이 프로젝트에서 검증된 버전은 3.12입니다. 펌웨어를 빌드하려면 ESP-IDF v5.0.2와 함께 3.12를 권장합니다."
}

& $PythonCommand[0] $PythonCommand[1..($PythonCommand.Count - 1)] -m venv .venv
if ($LASTEXITCODE -ne 0) {
    throw "가상환경 생성에 실패했습니다."
}

$VenvPython = if (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} elseif (Test-Path ".\.venv\bin\python.exe") {
    ".\.venv\bin\python.exe"
} else {
    throw "가상환경 Python 실행 파일을 찾지 못했습니다."
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip 업그레이드에 실패했습니다."
}
& $VenvPython -m pip install -e ".[gui,ml-runtime]"
if ($LASTEXITCODE -ne 0) {
    throw "프로젝트 의존성 설치에 실패했습니다."
}
& $VenvPython -m pip install esptool
if ($LASTEXITCODE -ne 0) {
    throw "펌웨어 업로드 도구(esptool) 설치에 실패했습니다."
}

Write-Host "기본 Python 환경 구성이 완료되었습니다."
Write-Host "활성화 파일은 .venv\Scripts 또는 .venv\bin 아래에 있습니다."
Write-Host "포트 확인: python -m csi_gateway ports"
Write-Host "Windows 사용법: docs\usage-windows.md"
