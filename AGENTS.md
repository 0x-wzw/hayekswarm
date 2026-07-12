# HayekSwarm — Agent Instructions

This document provides guidance for AI agents working with the HayekSwarm codebase.

## Overview

HayekSwarm is a decentralized multi-agent intelligence marketplace. It combines:
- **HayekMAS** — Hayekian economic engine for agent markets
- **Swarm** — 10-D Council, cost router, consensus
- **Server** — FastAPI REST API
- **VoidTether** — Protocol mesh for cross-framework agent connectivity

## Key Principles

1. **Decentralized coordination** — No single orchestrator; agents negotiate via markets
2. **Hayekian economics** — Prices emerge from local knowledge and bidding
3. **Protocol agnostic** — Agents can use A2A, MCP, ACP, or any supported protocol
4. **Self-organizing** — The system adapts without central planning

## Architecture

```
hayekmas/  ← Economic engine (agent, MAS, population, pipeline)
swarm/     ← Coordination (council, cost router, consensus)
server/    ← API layer (FastAPI, auth, database)
voidtether/ ← Protocol mesh (adapters, core, economy, mesh)
```

## Common Tasks

### Adding a new protocol adapter

1. Create `voidtether/adapters/<name>/adapter.py` and `__init__.py`
2. Implement the adapter interface from `voidtether/core/bridge.py`
3. Register in the adapter registry

### Adding a new council dimension

1. Edit `swarm/council/dimension_map.py`
2. Add the dimension definition
3. Update the evaluation logic in `swarm/council/council.py`

### Extending the API

1. Add routes to `server/app.py`
2. Add models to `server/models.py`
3. Add database operations to `server/database.py`

## Running

```bash
# Install
pip install -e ".[server,dev]"

# Run server
uvicorn server.app:app --reload --port 8000

# Run worker
python -m server.worker
```

## Testing

```bash
pytest tests/
```

## Docker

```bash
docker compose up -d
```
