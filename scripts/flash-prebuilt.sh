#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || ( "$1" != "tx" && "$1" != "rx" ) ]]; then
  echo "사용법: $0 tx|rx /dev/cu.<PORT>" >&2
  exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROLE="$1"
PORT="$2"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
if [[ "$ROLE" == "tx" ]]; then
  ROLE_LABEL="TX"
else
  ROLE_LABEL="RX"
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "오류: .venv가 없습니다. 먼저 ./scripts/bootstrap.sh를 실행하세요." >&2
  exit 1
fi
if [[ ! -e "$PORT" ]]; then
  echo "오류: 직렬 포트를 찾을 수 없습니다: $PORT" >&2
  exit 1
fi

cd "$PROJECT_ROOT"
echo "대상 역할: $ROLE_LABEL"
echo "대상 포트: $PORT"
echo "펌웨어: ESP32-S3 / HT20 / 기본 채널 6 / TX 100Hz"

if [[ "$ROLE" == "tx" ]]; then
  "$PYTHON" -m esptool --chip esp32s3 -p "$PORT" -b 460800 write-flash \
    --flash-mode dio --flash-freq 80m --flash-size 2MB \
    0x0 firmware/prebuilt/tx/bootloader.bin \
    0x8000 firmware/prebuilt/tx/partition-table.bin \
    0x10000 firmware/prebuilt/tx/csi_send.bin
else
  "$PYTHON" -m esptool --chip esp32s3 -p "$PORT" -b 460800 write-flash \
    --flash-mode dio --flash-freq 80m --flash-size 4MB \
    0x0 firmware/prebuilt/rx/bootloader.bin \
    0x8000 firmware/prebuilt/rx/partition-table.bin \
    0x1d000 firmware/prebuilt/rx/ota_data_initial.bin \
    0x20000 firmware/prebuilt/rx/console_test.bin
fi

echo "$ROLE_LABEL 플래시와 쓰기 검증이 완료되었습니다."
