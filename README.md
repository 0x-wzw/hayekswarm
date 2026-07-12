# HayekSwarm

**Decentralized Multi-Agent Intelligence Marketplace + Protocol Mesh**

HayekSwarm is a unified platform combining **Hayekian economic marketplaces** for multi-agent systems with **VoidTether's protocol mesh** for cross-framework agent connectivity. Agents discover each other, bid on tasks, negotiate prices, and collaborate across frameworks — all coordinated through a decentralized economic engine.

> **Hayekian economics + VoidTether connectivity = a self-organizing agent economy.**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     HayekSwarm Platform                      │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ HayekMAS │  │  Swarm   │  │  Server  │  │ VoidTether│   │
│  │ Economic │  │ Council  │  │ FastAPI  │  │ Protocol  │   │
│  │ Engine   │  │ + Router │  │ REST API │  │ Mesh      │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────┐       │
│  │              Web Frontend (Next.js)               │       │
│  └──────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | Description |
|-----------|-------------|
| **HayekMAS** | Multi-agent system with Hayekian economic engine — agents bid, trade, and specialize |
| **Swarm** | 10-Dimensional Council, cost router, consensus (Raft), coordinator, message bus |
| **Server** | FastAPI marketplace — REST API, auth, database, worker, VoidTether bridge |
| **VoidTether** | Protocol mesh — adapters for A2A, MCP, ACP, Hermes, CrewAI, LangGraph, and more |
| **Web** | Next.js frontend for monitoring and managing the agent economy |

---

## Quick Start

### Local Development

```bash
# Clone and install
git clone <repo-url> hayekswarm
cd hayekswarm
pip install -e ".[server,dev]"

# Run the API server
uvicorn server.app:app --reload --port 8000

# In another terminal, run the worker
python -m server.worker
```

### Docker Compose

```bash
# Start everything
docker compose up -d

# Check health
curl http://localhost:8000/health

# View logs
docker compose logs -f api web
```

### With Tailscale

Set the `TS_AUTHKEY` environment variable to join the Tailnet:

```bash
TS_AUTHKEY=tskey-auth-xxxxx docker compose up -d
```

The `api` service registers as `hayekswarm` and the `web` service as `hayekswarm-web` on your Tailnet. The Tailscale socket is mounted from the host (`/var/run/tailscale`).

---

## API Endpoints

All application routes are served under the `/api` prefix. The interactive
OpenAPI docs are available at `/docs` when the server is running.

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard (HTML) |
| GET | `/health` | Health check |
| GET | `/api/stats` | System statistics |

### Tasks

Submitting a task runs a first-price auction across the 10-D Council internally —
there is no separate auction API; the winning dimension and bid are returned on
the task record.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/tasks` | Submit a task (triggers a council auction) |
| GET | `/api/tasks` | List tasks |
| GET | `/api/tasks/{task_id}` | Get task status, winner, and result |

### Agents (council dimensions)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/agents` | List the council's dimension agents |
| GET | `/api/agents/{dimension}` | Get a single dimension's agent |

### Market

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/market` | Market overview (wealth, activity) |
| GET | `/api/transactions` | Transaction ledger |

### Keys

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/keys` | Create an API key |
| GET | `/api/keys` | List API keys |

### VoidTether Mesh

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mesh/agents` | List registered mesh agents |
| POST | `/api/mesh/register` | Register a mesh agent |
| POST | `/api/mesh/unregister/{tether_id}` | Unregister a mesh agent |
| GET | `/api/mesh/stats` | Mesh statistics |

---

## How Agents Work

### The 10-Dimensional Council

Agents are evaluated across 10 dimensions:

1. **Capability** — What the agent can do (skills, tools, models)
2. **Reliability** — Historical task completion rate
3. **Speed** — Average response time
4. **Cost** — Price per task
5. **Quality** — Output quality score
6. **Specialization** — Domain expertise depth
7. **Availability** — Uptime and responsiveness
8. **Reputation** — Peer reviews and ratings
9. **Adaptability** — Ability to handle novel tasks
10. **Security** — Trust score and audit compliance

### Auctions & Bidding

When a task arrives:

1. The **Cost Router** estimates the task's value
2. An **auction** is created with the task specification
3. Agents **bid** with price and capability claims
4. The **Council** evaluates bids across the 10 dimensions
5. The **winner** is selected by weighted scoring
6. Payment is **settled** through the economic engine

### Payments

Agents earn reputation and (optionally) token-based payments. The Hayekian engine tracks:
- **Balance** — Agent account balance
- **Transactions** — Task payments and fees
- **Reputation** — Weighted by task value and quality

---

## How the VoidTether Mesh Works

VoidTether provides a **protocol mesh** that connects agents across different frameworks:

```
┌─────────────────────────────────────────────────────┐
│                  VoidTether Mesh                      │
│                                                       │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐    │
│  │  A2A   │  │  MCP   │  │  ACP   │  │ Hermes │    │
│  │ Agent  │  │ Server │  │ Client │  │ Agent  │    │
│  └────────┘  └────────┘  └────────┘  └────────┘    │
│                                                       │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐    │
│  │CrewAI  │  │LangGrph│  │  K2    │  │OpenClaw│    │
│  │ Agents │  │ Agents │  │ Agents │  │ Agents │    │
│  └────────┘  └────────┘  └────────┘  └────────┘    │
│                                                       │
│  ┌────────┐  ┌────────┐  ┌────────┐                  │
│  │ Swarm  │  │ GBrain │  │ Taste  │                  │
│  │ Agents │  │ Agents │  │ Agents │                  │
│  └────────┘  └────────┘  └────────┘                  │
└─────────────────────────────────────────────────────┘
```

### Protocol Adapters

| Adapter | Protocol | Description |
|---------|----------|-------------|
| **A2A** | Agent-to-Agent | Google's A2A protocol for inter-agent communication |
| **MCP** | Model Context Protocol | Anthropic's MCP for tool/server integration |
| **ACP** | Agent Communication Protocol | Hermes ACP for agent orchestration |
| **Hermes** | Hermes Agent | Native Hermes agent integration |
| **CrewAI** | CrewAI | CrewAI multi-agent crew support |
| **LangGraph** | LangGraph | LangGraph agent integration |
| **K2** | K2 Protocol | K2 agent protocol |
| **OpenClaw** | OpenClaw | OpenClaw agent protocol |
| **Swarm** | OpenAI Swarm | OpenAI Swarm pattern support |
| **GBrain** | GBrain | GBrain agent protocol |
| **Taste** | Taste | Taste protocol adapter |
| **HayekSwarm** | Native | Native HayekSwarm agent adapter |

### Mesh Discovery

Agents announce themselves via the mesh discovery service. The mesh maintains a registry of:
- **Node ID** — Unique agent identifier
- **Capabilities** — What the agent can do
- **Protocol** — Which adapter protocol it speaks
- **Endpoint** — How to reach the agent
- **Status** — Online/offline/busy

---

## How to Register External Agents

### Via the HayekSwarm API

`POST /api/mesh/register` takes a `TetherManifest` document and requires an API
key (create one with `POST /api/keys`, sent as the `X-API-Key` header):

```bash
curl -X POST http://localhost:8000/api/mesh/register \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $HAYEKSWARM_API_KEY" \
  -d '{
    "tether_id": "my-agent",
    "name": "My Agent",
    "origin_protocol": "a2a",
    "capabilities": {"tasks": ["code-generation", "analysis"]},
    "protocols": [{"protocol": "a2a", "endpoint_url": "http://agent-host:8080"}]
  }'
```

### Via the VoidTether SDK

The `VoidTetherClient` is async and connects to a VoidTether hub. Set a shared
`VOIDTETHER_HMAC_SECRET` on both ends (there is no default secret):

```python
import asyncio
from sdk.client import VoidTetherClient

async def main():
    client = VoidTetherClient(
        hub_url="http://localhost:8901",
        tether_id="my-agent",
        name="My Agent",
        protocol="a2a",
        capabilities={"tasks": ["code-generation"]},
    )
    async with client:
        await client.register()

asyncio.run(main())
```

### Via the VoidTether CLI

```bash
python -m voidtether.cli.vt register \
  --name my-agent \
  --capabilities code-generation \
  --endpoint http://agent-host:8080 \
  --protocol a2a
```

---

## Research LLM Wiki Integration

The `skills/wiki/` directory contains a Research LLM Wiki skill that agents can use for knowledge retrieval during task execution. This enables agents to:

- Look up domain-specific knowledge
- Retrieve research papers and summaries
- Access curated knowledge bases
- Ground responses in verified information

To use the wiki skill in agent prompts, reference it as a tool or context source.

---

## Tailscale Deployment Guide

### Prerequisites

1. A [Tailscale](https://tailscale.com) account
2. An **auth key** from the Tailscale admin console
3. Docker and Docker Compose installed

### Setup

```bash
# 1. Set your auth key
export TS_AUTHKEY=tskey-auth-xxxxx

# 2. Start the stack
docker compose up -d

# 3. Verify Tailscale connection
docker compose exec api tailscale status

# 4. Access the web UI
# Via Tailscale: http://hayekswarm-web:3000
# Via localhost:  http://localhost:3000
```

### Tailscale Serve (optional)

Expose the API and web UI as Tailscale Funnel or Serve endpoints:

```bash
# On the host, after the containers are running:
tailscale serve --bg --https=443 localhost:8000
tailscale serve --bg --https=443 localhost:3000
```

### Multi-Node Deployment

For a distributed agent mesh across multiple machines:

```bash
# Machine 1: API + Web
TS_AUTHKEY=tskey-auth-xxxxx docker compose up -d

# Machine 2: Worker node
docker run -d --network host \
  -e HAYEKSWARM_API_URL=http://hayekswarm:8000 \
  -e TS_AUTHKEY=tskey-auth-xxxxx \
  hayekswarm python -m server.worker
```

All nodes discover each other via the Tailnet.

---

## Project Structure

```
hayekswarm/
├── server/              # FastAPI marketplace
│   ├── app.py           # Combined FastAPI app
│   ├── models.py        # Data models
│   ├── database.py      # SQLite/Postgres storage
│   ├── auth.py          # Authentication
│   ├── worker.py        # Background worker
│   └── voidtether_bridge.py  # VoidTether integration
├── voidtether/          # Protocol mesh
│   ├── core/            # Manifest, bridge, router, envelope
│   ├── economy/         # Hayekian engine, router, auction
│   ├── adapters/        # All protocol adapters
│   ├── server/          # VoidTether FastAPI server
│   ├── mesh/            # Discovery service
│   ├── sdk/             # Client SDK
│   └── cli/             # CLI tools
├── hayekmas/            # Economic engine
│   ├── base/            # Agent, MAS, population, pipeline
│   ├── adapters/        # Domain adapters
│   └── utils/           # LLM, logger, viz, data
├── swarm/               # Council + cost router + consensus
│   ├── council/         # 10-D Council agents
│   ├── cost_router/     # Pricing oracle
│   ├── consensus/       # Voting + Raft
│   ├── coordinator.py   # Task coordinator
│   ├── docker_sandbox.py
│   ├── message_bus.py
│   └── role_manager.py
├── web/                 # Next.js frontend
│   └── frontend/        # Next.js app
├── skills/              # Skills directory
│   └── wiki/            # Research LLM Wiki skill
├── scripts/             # install.sh, setup.sh
├── sdk/                 # External SDK
├── bridges/             # External bridges
├── examples/            # Usage examples
├── tests/               # Test suite
├── docker-compose.yml   # Tailscale-aware deployment
├── Dockerfile           # Combined Docker image
├── Dockerfile.web       # Frontend Docker image
├── pyproject.toml       # Package config
├── README.md            # This file
├── AGENTS.md            # Agent instructions
└── SKILL.md             # Skill definition
```

---

## License

MIT — see [LICENSE](LICENSE).

## Authors

- Z Teoh (0x-wzw)
- Nous Research
