#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$PROJECT_ROOT/third_party/esp-csi"
PATCH_FILE="$PROJECT_ROOT/firmware/patches/esp-csi-project.patch"

cd "$PROJECT_ROOT"
COMMIT="$(python3 -c 'import json; print(json.load(open("versions.json"))["espCsiCommit"])')"

# 패치가 추가하는 식별자. 두 파일 모두에 있어야 패치 적용 상태로 본다.
PATCH_MARKER="RF_CONTROL_MAGIC"
MARKER_FILES=(
  "examples/esp-radar/console_test/main/app_main.c"
  "examples/get-started/csi_send/main/app_main.c"
)

recovery_hint() {
  cat <<EOF
복구 방법:
  1. rm -rf "$TARGET"
  2. ./scripts/fetch-esp-csi.sh
EOF
}

is_patch_applied() {
  local relative
  for relative in "${MARKER_FILES[@]}"; do
    if [[ ! -f "$TARGET/$relative" ]]; then
      return 1
    fi
    if ! grep -qF "$PATCH_MARKER" "$TARGET/$relative"; then
      return 1
    fi
  done
  return 0
}

assert_commit() {
  local head
  [[ -n "$COMMIT" ]] || return 0
  head="$(git -C "$TARGET" rev-parse HEAD)"
  if [[ "$head" != "$COMMIT" ]]; then
    echo "경고: 체크아웃된 커밋이 versions.json과 다릅니다." >&2
    echo "  기대: $COMMIT" >&2
    echo "  실제: $head" >&2
    echo "다른 버전으로 빌드하면 이 프로젝트의 기준 환경이 아닙니다." >&2
  fi
}

apply_patch() {
  if ! git -C "$TARGET" apply --check "$PATCH_FILE"; then
    echo "오류: 프로젝트 패치를 적용할 수 없습니다: $TARGET" >&2
    echo "소스가 수정되었거나 다른 커밋을 사용 중일 수 있습니다." >&2
    echo "이 상태로 빌드하면 채널 전환 기능이 빠지고 기본 채널이 6이 아닌 11이 됩니다." >&2
    recovery_hint >&2
    exit 1
  fi
  if ! git -C "$TARGET" apply "$PATCH_FILE"; then
    echo "오류: 패치 적용에 실패했습니다: $TARGET" >&2
    recovery_hint >&2
    exit 1
  fi
  if ! is_patch_applied; then
    echo "오류: 패치를 적용했지만 확인에 실패했습니다: $TARGET" >&2
    recovery_hint >&2
    exit 1
  fi
}

# 1. 이미 받아둔 소스가 있으면 상태를 확인한다.
if [[ -d "$TARGET/.git" ]]; then
  if is_patch_applied; then
    assert_commit
    echo "esp-csi가 이미 준비되어 있습니다(패치 적용 확인): $TARGET"
    exit 0
  fi

  echo "esp-csi는 있지만 프로젝트 패치가 적용되지 않았습니다. 적용을 시도합니다."
  apply_patch
  assert_commit
  echo "프로젝트 ESP-CSI 패치를 적용했습니다."
  exit 0
fi

# 2. .git 없이 폴더만 남아 있으면 중단된 실행의 잔여물이다.
if [[ -e "$TARGET" ]]; then
  echo "오류: '$TARGET' 폴더가 있지만 git 저장소가 아닙니다." >&2
  echo "이전 실행이 중단되었을 수 있습니다." >&2
  recovery_hint >&2
  exit 1
fi

# 3. 처음부터 받는다.
if ! git clone --recursive https://github.com/espressif/esp-csi.git "$TARGET"; then
  echo "오류: esp-csi 클론에 실패했습니다. 인터넷 연결을 확인하세요." >&2
  exit 1
fi

if [[ -n "$COMMIT" ]]; then
  git -C "$TARGET" checkout "$COMMIT"
  git -C "$TARGET" submodule update --init --recursive
fi

apply_patch
assert_commit
git -C "$TARGET" rev-parse HEAD
echo "프로젝트 ESP-CSI 패치를 적용했습니다."
