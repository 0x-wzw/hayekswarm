#!/usr/bin/env bash
# HayekSwarm — Tailscale deployment script
# Deploys the full stack on a Tailscale node
set -euo pipefail

echo "🏛️  HayekSwarm — Tailscale Deployment"
echo "========================================"
echo ""

# ── Config ──────────────────────────────────────────────────────────────────
TS_HOSTNAME="${TS_HOSTNAME:-hayekswarm}"
TS_PORT="${TS_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
HAYEKSWARM_DIR="${HAYEKSWARM_DIR:-$HOME/hayekswarm}"
OLLAMA_API_KEY="${OLLAMA_API_KEY:-}"

# ── Check prerequisites ────────────────────────────────────────────────────

if ! command -v tailscale &> /dev/null; then
    echo "❌ Tailscale is not installed."
    echo "   Install: curl -fsSL https://tailscale.com/install.sh | sh"
    exit 1
fi

if ! command -v docker &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "❌ Neither Docker nor Python 3.11+ found."
    echo "   Install one of them."
    exit 1
fi

# ── Tailscale status ────────────────────────────────────────────────────────

echo "🔍 Checking Tailscale status..."
TS_STATUS=$(tailscale status --json 2>/dev/null || echo '{}')
TS_ONLINE=$(echo "$TS_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print('yes' if d.get('Self',{}).get('Online', False) else 'no')" 2>/dev/null || echo "unknown")

if [ "$TS_ONLINE" != "yes" ]; then
    echo "⚠️  Tailscale is not connected. Starting..."
    sudo tailscale up --hostname="$TS_HOSTNAME" --accept-routes 2>&1 || true
fi

TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
echo "✅ Tailscale IP: $TS_IP"
echo ""

# ── Clone / update repo ─────────────────────────────────────────────────────

if [ -d "$HAYEKSWARM_DIR" ]; then
    echo "📦 Updating HayekSwarm..."
    cd "$HAYEKSWARM_DIR" && git pull
else
    echo "📦 Cloning HayekSwarm..."
    git clone https://github.com/0x-wzw/hayekswarm.git "$HAYEKSWARM_DIR"
    cd "$HAYEKSWARM_DIR"
fi

# ── Deploy ──────────────────────────────────────────────────────────────────

if command -v docker &> /dev/null; then
    echo "🐳 Deploying with Docker Compose..."
    export TS_HOSTNAME
    export OLLAMA_API_KEY
    cd "$HAYEKSWARM_DIR"
    docker compose up -d --build
    echo ""
    echo "✅ HayekSwarm deployed!"
    echo "   Dashboard:  http://$TS_IP:$TS_PORT"
    echo "   API Docs:   http://$TS_IP:$TS_PORT/docs"
    echo "   Web UI:     http://$TS_IP:$WEB_PORT"
    echo "   Tailscale:  http://$TS_HOSTNAME:$TS_PORT"
else
    echo "🐍 Deploying with Python..."
    cd "$HAYEKSWARM_DIR"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[server]" --quiet
    mkdir -p data

    echo ""
    echo "Starting server..."
    uvicorn server.app:app --host 0.0.0.0 --port "$TS_PORT" &
    SERVER_PID=$!
    echo "Server PID: $SERVER_PID"

    echo ""
    echo "✅ HayekSwarm deployed!"
    echo "   Dashboard:  http://$TS_IP:$TS_PORT"
    echo "   API Docs:   http://$TS_IP:$TS_PORT/docs"
    echo "   Tailscale:  http://$TS_HOSTNAME:$TS_PORT"
    echo ""
    echo "To stop: kill $SERVER_PID"
fi

# ── Create API key ──────────────────────────────────────────────────────────

echo ""
echo "🔑 Creating initial API key..."
sleep 2
API_KEY=$(curl -s -X POST "http://localhost:$TS_PORT/api/keys" \
    -H "Content-Type: application/json" \
    -d '{"label":"admin"}' 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('key','failed'))" 2>/dev/null || echo "failed")

if [ "$API_KEY" != "failed" ]; then
    echo "   API Key: $API_KEY"
    echo "   Save this — it won't be shown again."
    echo ""
    echo "   Test it:"
    echo "   curl -X POST http://$TS_IP:$TS_PORT/api/tasks \\"
    echo "     -H \"X-API-Key: $API_KEY\" \\"
    echo "     -H \"Content-Type: application/json\" \\"
    echo '     -d '"'"'{"content":"What is Hayekian economics?","stakes":"low"}'"'"''
fi

echo ""
echo "🏛️  HayekSwarm is live on your tailnet!"
