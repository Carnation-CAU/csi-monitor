$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $ProjectRoot "third_party\esp-csi"
$Versions = Get-Content (Join-Path $ProjectRoot "versions.json") -Raw | ConvertFrom-Json
$Commit = $Versions.espCsiCommit
$PatchFile = Join-Path $ProjectRoot "firmware\patches\esp-csi-project.patch"

# 패치가 추가하는 식별자. 두 파일 모두에 있어야 패치 적용 상태로 본다.
$PatchMarker = "RF_CONTROL_MAGIC"
$MarkerFiles = @(
    "examples\esp-radar\console_test\main\app_main.c",
    "examples\get-started\csi_send\main\app_main.c"
)

function Test-PatchApplied {
    param([string]$Root)

    foreach ($Relative in $MarkerFiles) {
        $Path = Join-Path $Root $Relative
        if (-not (Test-Path -LiteralPath $Path)) {
            return $false
        }
        if (-not (Select-String -LiteralPath $Path -Pattern $PatchMarker -Quiet -SimpleMatch)) {
            return $false
        }
    }
    return $true
}

function Assert-Commit {
    param([string]$Root)

    if (-not $Commit) {
        return
    }
    $Head = (& git -C $Root rev-parse HEAD).Trim()
    if ($Head -ne $Commit) {
        Write-Warning "체크아웃된 커밋이 versions.json과 다릅니다."
        Write-Warning "  기대: $Commit"
        Write-Warning "  실제: $Head"
        Write-Warning "다른 버전으로 빌드하면 이 프로젝트의 기준 환경이 아닙니다."
    }
}

$RecoveryHint = @"
복구 방법:
  1. Remove-Item -Recurse -Force '$Target'
  2. .\scripts\fetch-esp-csi.ps1
"@

# 1. 이미 받아둔 소스가 있으면 상태를 확인한다.
if (Test-Path -LiteralPath (Join-Path $Target ".git")) {
    if (Test-PatchApplied -Root $Target) {
        Assert-Commit -Root $Target
        Write-Host "esp-csi가 이미 준비되어 있습니다(패치 적용 확인): $Target"
        exit 0
    }

    Write-Host "esp-csi는 있지만 프로젝트 패치가 적용되지 않았습니다. 적용을 시도합니다."
    & git -C $Target apply --check $PatchFile
    if ($LASTEXITCODE -ne 0) {
        throw @"
프로젝트 패치를 적용할 수 없습니다: $Target
소스가 수정되었거나 다른 커밋을 사용 중일 수 있습니다.
이 상태로 빌드하면 채널 전환 기능이 빠지고 기본 채널이 6이 아닌 11이 됩니다.
$RecoveryHint
"@
    }
    & git -C $Target apply $PatchFile
    if ($LASTEXITCODE -ne 0) {
        throw "패치 적용에 실패했습니다: $Target`n$RecoveryHint"
    }
    if (-not (Test-PatchApplied -Root $Target)) {
        throw "패치를 적용했지만 확인에 실패했습니다: $Target`n$RecoveryHint"
    }
    Assert-Commit -Root $Target
    Write-Host "프로젝트 ESP-CSI 패치를 적용했습니다."
    exit 0
}

# 2. .git 없이 폴더만 남아 있으면 중단된 실행의 잔여물이다.
if (Test-Path -LiteralPath $Target) {
    throw @"
'$Target' 폴더가 있지만 git 저장소가 아닙니다.
이전 실행이 중단되었을 수 있습니다.
$RecoveryHint
"@
}

# 3. 처음부터 받는다.
& git clone --recursive https://github.com/espressif/esp-csi.git $Target
if ($LASTEXITCODE -ne 0) {
    throw "esp-csi 클론에 실패했습니다. 인터넷 연결을 확인하세요."
}

if ($Commit) {
    & git -C $Target checkout $Commit
    if ($LASTEXITCODE -ne 0) {
        throw "고정 커밋 체크아웃에 실패했습니다: $Commit`n$RecoveryHint"
    }
    & git -C $Target submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) {
        throw "서브모듈 초기화에 실패했습니다.`n$RecoveryHint"
    }
}

& git -C $Target apply --check $PatchFile
if ($LASTEXITCODE -ne 0) {
    throw "프로젝트 패치를 적용할 수 없습니다.`n$RecoveryHint"
}
& git -C $Target apply $PatchFile
if ($LASTEXITCODE -ne 0) {
    throw "패치 적용에 실패했습니다.`n$RecoveryHint"
}
if (-not (Test-PatchApplied -Root $Target)) {
    throw "패치를 적용했지만 확인에 실패했습니다.`n$RecoveryHint"
}

Assert-Commit -Root $Target
& git -C $Target rev-parse HEAD
Write-Host "프로젝트 ESP-CSI 패치를 적용했습니다."
