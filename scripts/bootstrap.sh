#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 검증된 버전을 먼저 쓰되, 없으면 pyproject의 requires-python(>=3.10)을 만족하는
# 다른 버전으로 진행한다. $CSI_PYTHON으로 직접 지정할 수도 있다.
#   CSI_PYTHON=python3.13 ./scripts/bootstrap.sh
PYTHON_BIN=""

if [[ -n "${CSI_PYTHON:-}" ]]; then
  if ! command -v "$CSI_PYTHON" >/dev/null 2>&1; then
    echo "오류: CSI_PYTHON으로 지정한 '$CSI_PYTHON'을 찾을 수 없습니다." >&2
    exit 1
  fi
  PYTHON_BIN="$CSI_PYTHON"
else
  for candidate in python3.12 python3.13 python3.14 python3.11 python3.10 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "오류: Python 3.10 이상을 찾지 못했습니다." >&2
  echo "  macOS: brew install python@3.12" >&2
  exit 1
fi

SELECTED="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
echo "사용할 Python: $SELECTED ($PYTHON_BIN)"
case "$SELECTED" in
  3.12.*) ;;
  *) echo "참고: 이 프로젝트에서 검증된 버전은 3.12입니다. 펌웨어를 빌드하려면 ESP-IDF v5.0.2와 함께 3.12를 권장합니다." ;;
esac

# 다른 인터프리터로 만든 기존 가상환경이 있으면 섞이지 않게 정리한다.
if [[ -d .venv ]]; then
  EXISTING="$(.venv/bin/python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo "")"
  if [[ "$EXISTING" != "$SELECTED" ]]; then
    echo "기존 .venv(${EXISTING:-알 수 없음})가 선택한 버전과 달라 다시 만듭니다."
    rm -rf .venv
  fi
fi

"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gui,ml-runtime]"

echo "기본 Python 환경 구성이 완료되었습니다."
echo "활성화: . .venv/bin/activate"
echo "포트 확인: python -m csi_gateway ports"
