#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/apps/snowa_tradingbot"
VENV="$APP_DIR/.venv"

cd "$APP_DIR"

echo "=== CANSLIM Screening Pipeline ==="
echo "Starting: $(date)"
echo ""

"$VENV/bin/python" -m scripts.run_screening

echo ""
echo "Finished: $(date)"
