#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/apps/snowa_tradingbot"
VENV="$APP_DIR/.venv"

cd "$APP_DIR"
source "$VENV/bin/activate"

echo "=== SNOWA Data Update ==="
echo "Starting: $(date)"
echo ""

python -m scripts.initial_data_load --mode all "$@"

echo ""
echo "Finished: $(date)"
