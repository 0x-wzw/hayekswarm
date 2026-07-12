#!/usr/bin/env bash
# HayekSwarm Marketplace — Quick start script
set -euo pipefail

echo "🏛️  HayekSwarm Marketplace Setup"
echo "=================================="
echo ""

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3.11+ is required"
    exit 1
fi

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# Install
echo "📦 Installing HayekSwarm..."
pip install -e ".[server]" --quiet

# Create .env if needed
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file..."
    cat > .env << 'EOF'
# HayekSwarm Configuration
HAYEKSWARM_DB=hayekswarm.db
OLLAMA_API_KEY=
OLLAMA_BASE_URL=https://ollama.com/v1
EOF
    echo "   Edit .env to set your OLLAMA_API_KEY"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the marketplace:"
echo "  source .venv/bin/activate"
echo "  uvicorn server.app:app --reload --port 8000"
echo ""
echo "Or with Docker:"
echo "  docker compose up"
echo ""
echo "Then create an API key:"
echo "  curl -X POST http://localhost:8000/api/keys -H 'Content-Type: application/json' -d '{\"label\":\"my-key\"}'"
echo ""
echo "Submit a task:"
echo '  curl -X POST http://localhost:8000/api/tasks -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" -d '"'"'{"content":"Design an API architecture","stakes":"medium"}'"'"''
echo ""
echo "Open the dashboard:"
echo "  http://localhost:8000"
