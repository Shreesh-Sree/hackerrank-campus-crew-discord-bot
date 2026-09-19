#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/data/production/hrcc_bot"
SERVICE_NAME="hrcc-bot"
SERVICE_FILE="$PROJECT_DIR/deploy/hrcc-bot.service"
VENV_DIR="$PROJECT_DIR/venv"

echo "=== HRCC Bot Deployment ==="
echo "Target: $PROJECT_DIR"
echo ""

cd "$PROJECT_DIR"

echo "[1/6] Pulling latest code..."
git pull origin main

echo "[2/6] Activating virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

echo "[3/6] Installing dependencies..."
pip install -r deploy/requirements.txt -q

echo "[4/6] Running test suite..."
DISCORD_BOT_TOKEN=test python -m pytest tests/ -q
echo ""

echo "[5/6] Installing systemd service..."
sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload

echo "[6/6] Restarting service..."
sudo systemctl restart "$SERVICE_NAME"
sleep 2

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "=== Deployment successful ==="
    sudo systemctl status "$SERVICE_NAME" --no-pager -l
else
    echo ""
    echo "=== DEPLOYMENT FAILED ==="
    sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    exit 1
fi
