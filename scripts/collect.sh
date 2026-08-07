#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 PORT [LABEL] [DURATION_SECONDS]"
  exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="$1"
LABEL="${2:-unlabeled}"
DURATION="${3:-120}"

cd "$PROJECT_ROOT"
. .venv/bin/activate
python -m csi_gateway collect \
  --port "$PORT" \
  --label "$LABEL" \
  --duration "$DURATION" \
  --project-root "$PROJECT_ROOT"
