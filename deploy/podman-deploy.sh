#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/data/production/hrcc_bot"
COMPOSE="$HOME/.local/bin/podman-compose"

cd "$PROJECT_DIR"

echo "=== HRCC Bot — Podman Deployment ==="
echo ""

# Step 1: Pull latest code
echo "[1/5] Pulling latest code..."
git pull origin main

# Step 2: Run tests before deploying
echo "[2/5] Running test suite..."
source venv/bin/activate 2>/dev/null || true
DISCORD_BOT_TOKEN=test DATABASE_URL="" python -m pytest tests/ -q --no-header 2>&1 | tail -3
echo ""

# Step 3: Build the container image
echo "[3/5] Building container image..."
podman build -t hrcc-bot:latest -f Containerfile .

# Step 4: Stop existing containers (if running)
echo "[4/5] Stopping existing containers..."
$COMPOSE -f podman-compose.yml down 2>/dev/null || true

# Step 5: Start the stack
echo "[5/5] Starting Postgres + Bot..."
$COMPOSE -f podman-compose.yml up -d

echo ""
echo "=== Waiting for services to start ==="
sleep 5

# Verify
echo ""
echo "=== Container Status ==="
podman ps --filter "name=hrcc" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== Bot Logs (last 15 lines) ==="
podman logs --tail 15 hrcc-bot 2>&1 || true

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Useful commands:"
echo "  podman logs -f hrcc-bot           # Follow bot logs"
echo "  podman logs -f hrcc-postgres      # Follow DB logs"
echo "  podman exec -it hrcc-postgres psql -U hrcc_user -d hrcc_bot  # DB shell"
echo "  $COMPOSE -f podman-compose.yml down   # Stop everything"
echo "  $COMPOSE -f podman-compose.yml restart bot  # Restart bot only"
