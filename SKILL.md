---
name: hayekswarm
description: >
  HayekSwarm — decentralized multi-agent intelligence marketplace combining
  Hayekian economics with VoidTether protocol mesh. Agents discover, bid,
  negotiate, and collaborate across frameworks (A2A, MCP, ACP, Hermes, CrewAI,
  LangGraph, and more) through a self-organizing economic engine.
domain: multi-agent-systems
tags:
  - multi-agent
  - hayekian-economics
  - voidtether
  - protocol-mesh
  - fastapi
  - docker
  - tailscale
---

# HayekSwarm Skill

## Overview

HayekSwarm is a unified platform for running decentralized multi-agent intelligence
marketplaces. It combines a Hayekian economic engine (HayekMAS) with a protocol mesh
(VoidTether) to enable agents across different frameworks to discover each other,
bid on tasks, negotiate prices, and collaborate.

## Key Files

| File | Purpose |
|------|---------|
| `server/app.py` | FastAPI application entry point |
| `server/models.py` | Pydantic data models |
| `server/database.py` | Database operations |
| `server/auth.py` | Authentication |
| `server/worker.py` | Background task worker |
| `server/voidtether_bridge.py` | VoidTether integration |
| `voidtether/core/bridge.py` | Protocol bridge interface |
| `voidtether/core/manifest.py` | Agent manifest |
| `voidtether/core/router.py` | Message routing |
| `voidtether/economy/hayek_engine.py` | Hayekian economic engine |
| `voidtether/economy/auction.py` | Auction mechanism |
| `voidtether/adapters/` | Protocol adapters (A2A, MCP, ACP, etc.) |
| `hayekmas/base/agent.py` | Base agent class |
| `hayekmas/base/mas.py` | Multi-agent system |
| `hayekmas/base/population.py` | Agent population management |
| `swarm/council/council.py` | 10-D Council evaluation |
| `swarm/cost_router/` | Pricing oracle |
| `swarm/consensus/raft.py` | Raft consensus |
| `swarm/coordinator.py` | Task coordinator |
| `swarm/message_bus.py` | Inter-agent messaging |
| `docker-compose.yml` | Tailscale-aware deployment |
| `Dockerfile` | Combined API image |
| `Dockerfile.web` | Frontend image |

## Quick Commands

```bash
# Install
pip install -e ".[server,dev]"

# Run server
uvicorn server.app:app --reload --port 8000

# Run worker
python -m server.worker

# Run tests
pytest tests/

# Docker
docker compose up -d
```

## Architecture

The system has four main layers:

1. **HayekMAS** — Economic engine: agents, populations, pipelines, auctions
2. **Swarm** — Coordination: 10-D Council, cost router, Raft consensus, message bus
3. **Server** — API: FastAPI, auth, database, worker, VoidTether bridge
4. **VoidTether** — Connectivity: protocol adapters, mesh discovery, routing

## Protocol Adapters

VoidTether supports these agent protocols:
- A2A (Google Agent-to-Agent)
- MCP (Model Context Protocol)
- ACP (Agent Communication Protocol)
- Hermes Agent
- CrewAI
- LangGraph
- K2
- OpenClaw
- OpenAI Swarm
- GBrain
- Taste
- HayekSwarm (native)

## Tailscale Deployment

Set `TS_AUTHKEY` env var to join the Tailnet. The API registers as `hayekswarm`
and the web UI as `hayekswarm-web` on the Tailnet.
