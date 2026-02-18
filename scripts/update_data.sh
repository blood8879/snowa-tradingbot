#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/apps/snowa_tradingbot"
VENV="$APP_DIR/.venv"

cd "$APP_DIR"
source "$VENV/bin/activate"

echo "=== [1/2] Data Load ==="
echo "Starting: $(date)"
echo ""

python -m scripts.initial_data_load --mode all "$@"

echo ""
echo "=== [2/2] CANSLIM Screening ==="
echo ""

python -m scripts.run_screening

echo ""
echo "Finished: $(date)"
