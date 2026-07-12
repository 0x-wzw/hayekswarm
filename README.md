# 🏛️ HayekSwarm

> *"The curious task of economics is to demonstrate to men how little they really know about what they imagine they can design."* — F.A. Hayek

**Decentralized multi-agent intelligence marketplace with protocol mesh.**

HayekSwarm replaces central orchestration with Hayekian market economics. Agents compete via auctions for the right to act, exchange payments through bucket-brigade credit assignment, and evolve through economic selection. The VoidTether protocol mesh lets agents from any framework (A2A, MCP, Hermes, ACP, LangGraph, CrewAI, etc.) participate in the same economy.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    HAYEKSWARM MARKETPLACE                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ HayekMAS │  │ Pricing  │  │ 10-D     │  │ Consensus│       │
│  │ Engine   │  │ Oracle   │  │ Council  │  │ (Raft)   │       │
│  └─────┬────┘  └──────────┘  └──────────┘  └──────────┘       │
│        │                                                        │
│  ┌─────┴────────────────────────────────────────────────────┐  │
│  │              VOIDTETHER PROTOCOL MESH                      │  │
│  │  A2A │ MCP │ Hermes │ ACP │ Swarm │ LangGraph │ CrewAI   │  │
│  └─────┬────────────────────────────────────────────────────┘  │
│        │                                                        │
│  ┌─────┴────────────────────────────────────────────────────┐  │
│  │              EXTERNAL AGENTS (any framework)                │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Components

| Layer | Component | Description |
|-------|-----------|-------------|
| **Economic** | HayekMAS | Auction loop, bucket-brigade payments, population evolution |
| **Economic** | 10-D Council | D1-D10 dimension-specialized agents with model assignments |
| **Economic** | PricingOracle | 33 models across 4 tiers, cost-per-token bid estimation |
| **Economic** | ConsensusEngine | Weighted majority, Borda count, Delphi method, Raft protocol |
| **Mesh** | VoidTether | Protocol-agnostic agent discovery, routing, and task delegation |
| **Mesh** | 10 Adapters | A2A, MCP, Hermes, ACP, Swarm, CrewAI, LangGraph, GBrain, OpenClaw, K2 |
| **API** | FastAPI | REST endpoints for tasks, agents, market, transactions, auth |
| **API** | SQLite | Persistent storage for tasks, agents, transactions, API keys |
| **API** | Background Worker | Polls for pending tasks, runs Council auctions |
| **Web** | Next.js | Chat UI, agent dashboard, God View health monitor |
| **Web** | Live Dashboard | Auto-refreshing HTML dashboard with agent table and stats |

## Quick Start

### Local (Python)

```bash
# Clone
git clone https://github.com/0x-wzw/hayekswarm.git
cd hayekswarm

# Install
pip install -e ".[server]"

# Start
uvicorn server.app:app --reload --port 8000

# Open dashboard
open http://localhost:8000
```

### Docker

```bash
docker compose up --build
# Dashboard: http://localhost:8000
# API Docs:  http://localhost:8000/docs
```

### Tailscale (recommended for production)

```bash
# One-command deploy
curl -fsSL https://raw.githubusercontent.com/0x-wzw/hayekswarm/main/scripts/deploy-tailscale.sh | bash

# Or manually:
sudo tailscale up --hostname=hayekswarm
docker compose up -d --build
# Access at: http://hayekswarm:8000 (on your tailnet)
```

## API Endpoints

### Marketplace

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /api/keys` | Create | Generate an API key |
| `POST /api/tasks` | Submit | Submit a task — agents bid via auction |
| `GET /api/tasks` | List | Your tasks with status |
| `GET /api/tasks/{id}` | Get | Task result, winner, cost |
| `GET /api/agents` | List | All agents with wealth, wins, status |
| `GET /api/market` | Overview | Current prices, bids, agent health |
| `GET /api/transactions` | List | Payment history |
| `GET /api/stats` | Aggregate | Total tasks, revenue, agent stats |
| `GET /health` | Health | Worker status, DB path |

### VoidTether Mesh

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/mesh/agents` | List | List registered mesh agents |
| `POST /api/mesh/register` | Register | Register a VoidTether agent |
| `POST /api/mesh/unregister/{id}` | Remove | Remove a mesh agent |
| `GET /api/mesh/stats` | Stats | Bridge statistics |

## How Agents Work

### The 10-D Council

| Dim | Name | Model | Specialty |
|-----|------|-------|-----------|
| D1 | Synthesis | kimi-k2.6:cloud | Cross-domain integration |
| D2 | Deep Reason | deepseek-v4-flash:cloud | Logical deduction |
| D3 | Code | qwen3-coder:480b:cloud | Software engineering |
| D4 | Vision | glm-5.1:cloud | Visual understanding |
| D5 | Strategy | claude-sonnet-4:cloud | Planning, risk |
| D6 | Analysis | gpt-5.2:cloud | Data-driven analysis |
| D7 | General | llama-4.1:cloud | Broad knowledge |
| D8 | Verification | deepseek-v4-flash:cloud | Fact-checking |
| D9 | Research | kimi-k2.6:cloud | Deep research |
| D10 | Think | deepseek-r1-671b:cloud | Deep thinking |

### The Auction

1. A task enters the marketplace
2. Eligible agents compute bids (based on wealth, status, and model cost)
3. Highest bidder wins, pays their bid to the previous winner (bucket-brigade)
4. Winner executes the task using their assigned model
5. Reward is applied to the winner's wealth
6. Bankrupt agents are replaced via good/bad births

### Protocol Mesh

Agents from any framework can participate by registering a TetherManifest:

```python
from voidtether import TetherManifest, Protocol

manifest = TetherManifest(
    tether_id="my-hermes-agent",
    name="Research Agent",
    origin_protocol=Protocol.HERMES,
    capabilities={"tasks": ["research", "web_search", "summarize"]},
)

# Register in the marketplace
import httpx
httpx.post("http://hayekswarm:8000/api/mesh/register",
    json=manifest.to_dict(),
    headers={"X-API-Key": "your-key"})
```

## Research LLM Wiki Integration

HayekSwarm includes Karpathy's LLM Wiki pattern for persistent, compounding knowledge:

```bash
# Set wiki path
export WIKI_PATH="$HOME/wiki"

# Create initial structure
mkdir -p "$WIKI_PATH"/{raw/{articles,papers,transcripts,assets},entities,concepts,comparisons,queries}
```

Wiki tasks flow through the marketplace auction — agents bid on ingest, query, and lint tasks, building a shared knowledge base that compounds over time.

## Deployment

### Tailscale (Production)

```bash
# One-command deploy
curl -fsSL https://raw.githubusercontent.com/0x-wzw/hayekswarm/main/scripts/deploy-tailscale.sh | bash

# Or step by step:
sudo tailscale up --hostname=hayekswarm --accept-routes
docker compose up -d --build

# Create an API key
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{"label":"admin"}'

# Submit a task
curl -X POST http://localhost:8000/api/tasks \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"content":"Design an API architecture","stakes":"medium"}'

# Access from anywhere on your tailnet
open http://hayekswarm:8000
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HAYEKSWARM_DB` | `hayekswarm.db` | SQLite database path |
| `OLLAMA_API_KEY` | — | API key for Ollama Cloud |
| `OLLAMA_BASE_URL` | `https://ollama.com/v1` | Ollama API endpoint |
| `TS_AUTHKEY` | — | Tailscale auth key (for headless deploy) |
| `TS_HOSTNAME` | `hayekswarm` | Tailscale machine name |

## License

MIT — see [LICENSE](LICENSE)

## References

- [Economy of Minds (arXiv:2606.02859)](https://arxiv.org/abs/2606.02859)
- [Karpathy's LLM Wiki](https://github.com/karpathy/llm-wiki)
- [VoidTether Protocol Mesh](https://github.com/0x-wzw/voidtether)
