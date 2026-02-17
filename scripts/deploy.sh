#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/ubuntu/apps/snowa_tradingbot"
VENV="$APP_DIR/.venv"
LOG_DIR="$APP_DIR/logs"

cd "$APP_DIR"
mkdir -p "$LOG_DIR"

echo "=== [1/4] Pulling latest code ==="
git pull origin main

echo "=== [2/4] Stopping running processes ==="
pkill -f "scripts.run_bot" 2>/dev/null && echo "Bot stopped" || echo "Bot was not running"
pkill -f "uvicorn web.api.main:app" 2>/dev/null && echo "Dashboard stopped" || echo "Dashboard was not running"
sleep 2

echo "=== [3/4] Starting bot ==="
nohup "$VENV/bin/python" -m scripts.run_bot >> "$LOG_DIR/bot.out" 2>&1 &
BOT_PID=$!
echo "Bot started (PID: $BOT_PID)"

echo "=== [4/4] Starting dashboard ==="
nohup "$VENV/bin/python" -m uvicorn web.api.main:app --host 0.0.0.0 --port 8000 >> "$LOG_DIR/dashboard.out" 2>&1 &
DASH_PID=$!
echo "Dashboard started (PID: $DASH_PID)"

sleep 3
echo ""
echo "=== Status ==="
ps -p "$BOT_PID" > /dev/null 2>&1 && echo "Bot: running (PID $BOT_PID)" || echo "Bot: FAILED to start"
ps -p "$DASH_PID" > /dev/null 2>&1 && echo "Dashboard: running (PID $DASH_PID)" || echo "Dashboard: FAILED to start"
echo "Done."
