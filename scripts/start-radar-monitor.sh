#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "사용법: $0 /dev/cu.usbserial-RECEIVER"
  exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$PROJECT_ROOT/.venv/bin/python" -m csi_gateway monitor \
  --port "$1" \
  --baud 2000000 \
  --project-root "$PROJECT_ROOT"
