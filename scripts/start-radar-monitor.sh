#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "사용법: $0 /dev/cu.usbserial-RECEIVER [model.pt] [inference_hz]"
  exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTIVITY_MODEL="${2:-$PROJECT_ROOT/ml/v_main/model.pt}"
ACTIVITY_HZ="${3:-5}"
"$PROJECT_ROOT/.venv/bin/python" -m csi_gateway monitor \
  --port "$1" \
  --baud 2000000 \
  --project-root "$PROJECT_ROOT" \
  --activity-model "$ACTIVITY_MODEL" \
  --activity-hz "$ACTIVITY_HZ"
