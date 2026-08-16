#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 5 ]]; then
  echo "사용법: $0 PORT [LABEL] [DURATION_SECONDS] [ROOM_ID] [DEVICE_ID]"
  exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="$1"
LABEL="${2:-unlabeled}"
DURATION="${3:-120}"
ROOM_ID="${4:-room-01}"
DEVICE_ID="${5:-rx-s3-001}"

cd "$PROJECT_ROOT"
. .venv/bin/activate
python -m csi_gateway collect \
  --port "$PORT" \
  --baud 2000000 \
  --label "$LABEL" \
  --duration "$DURATION" \
  --room-id "$ROOM_ID" \
  --device-id "$DEVICE_ID" \
  --project-root "$PROJECT_ROOT"
