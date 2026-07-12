"""HayekSwarm Marketplace — FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from server.auth import API_KEY_HEADER, generate_api_key, set_auth_db, verify_api_key
from server.database import Database
from server.models import (
    APIKeyCreate, APIKeyResponse,
    AgentResponse, AgentStatus as AgentStatusModel,
    MarketOverview, MarketPrice,
    StatsResponse,
    TaskResponse, TaskStatus, TaskSubmit,
    TransactionResponse,
)
from server.worker import MarketWorker
from server.voidtether_bridge import VoidTetherBridge

logger = logging.getLogger(__name__)

# ── Globals ───────────────────────────────────────────────────────────────────

db: Database = None  # type: ignore
worker: MarketWorker = None  # type: ignore
vt_bridge: VoidTetherBridge = None  # type: ignore


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, worker, vt_bridge
    db_path = os.environ.get("HAYEKSWARM_DB", "hayekswarm.db")
    db = Database(db_path)
    set_auth_db(db)

    worker = MarketWorker(db=db, poll_interval=1.0, max_concurrent=3)
    worker.start()

    # Initialize VoidTether bridge if worker has a council
    if worker and worker.council:
        from voidtether.core.router import TetherRouter
        tether_router = TetherRouter()
        vt_bridge = VoidTetherBridge(
            council=worker.council,
            tether_router=tether_router,
        )

    yield

    if worker:
        worker.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="HayekSwarm Marketplace",
    description="Decentralized multi-agent intelligence through Hayekian market economics",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Dashboard ─────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HayekSwarm Marketplace</title>
        <style>
            :root { --bg: #0d1117; --surface: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
            .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
            h1 { font-size: 2rem; margin-bottom: 8px; }
            h1 span { color: var(--accent); }
            .subtitle { color: #8b949e; margin-bottom: 32px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 32px; }
            .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
            .card h3 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; color: #8b949e; margin-bottom: 8px; }
            .card .value { font-size: 1.8rem; font-weight: 700; }
            .card .value.green { color: #3fb950; }
            .card .value.red { color: #f85149; }
            .card .value.blue { color: var(--accent); }
            table { width: 100%; border-collapse: collapse; margin-top: 16px; }
            th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }
            th { color: #8b949e; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
            .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
            .badge.t1 { background: #1f6feb33; color: #58a6ff; }
            .badge.t2 { background: #23863633; color: #3fb950; }
            .badge.t3 { background: #9e6a0333; color: #d29922; }
            .badge.think { background: #bc8cff33; color: #bc8cff; }
            .badge.novice { background: #8b949e33; color: #8b949e; }
            .badge.veteran { background: #23863633; color: #3fb950; }
            .badge.tycoon { background: #d2992233; color: #d29922; }
            .badge.bankrupt { background: #f8514933; color: #f85149; }
            .endpoints { margin-top: 32px; }
            .endpoints code { background: #1f2937; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }
            .endpoints li { margin-bottom: 8px; }
            a { color: var(--accent); text-decoration: none; }
            a:hover { text-decoration: underline; }
            .footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--border); color: #8b949e; font-size: 0.85rem; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏛️ <span>HayekSwarm</span> Marketplace</h1>
            <p class="subtitle">Decentralized multi-agent intelligence through Hayekian market economics</p>

            <div class="grid" id="stats-grid">
                <div class="card"><h3>Tasks Completed</h3><div class="value green" id="stat-tasks">—</div></div>
                <div class="card"><h3>Active Agents</h3><div class="value blue" id="stat-agents">—</div></div>
                <div class="card"><h3>Total Revenue</h3><div class="value" id="stat-revenue">—</div></div>
                <div class="card"><h3>Auctions Run</h3><div class="value" id="stat-auctions">—</div></div>
            </div>

            <h2>Agent Market</h2>
            <table id="agent-table">
                <thead>
                    <tr>
                        <th>Dimension</th>
                        <th>Model</th>
                        <th>Tier</th>
                        <th>Wealth</th>
                        <th>Status</th>
                        <th>Wins</th>
                        <th>Losses</th>
                        <th>Win Rate</th>
                        <th>Last Bid</th>
                    </tr>
                </thead>
                <tbody id="agent-tbody">
                    <tr><td colspan="9" style="text-align:center;color:#8b949e;">Loading...</td></tr>
                </tbody>
            </table>

            <div class="endpoints">
                <h2>API Endpoints</h2>
                <ul>
                    <li><code>POST /api/keys</code> — Create an API key</li>
                    <li><code>POST /api/tasks</code> — Submit a task to the marketplace</li>
                    <li><code>GET /api/tasks/{id}</code> — Get task result</li>
                    <li><code>GET /api/tasks</code> — List tasks</li>
                    <li><code>GET /api/agents</code> — List agents with wealth/status</li>
                    <li><code>GET /api/market</code> — Market overview with prices</li>
                    <li><code>GET /api/stats</code> — Aggregate statistics</li>
                    <li><code>GET /api/transactions</code> — Transaction history</li>
                    <li><code>GET /docs</code> — Interactive API docs (Swagger UI)</li>
                </ul>
            </div>

            <div class="footer">
                <p>HayekSwarm v1.0.0 — <a href="https://github.com/0x-wzw/hayekswarm">GitHub</a> — <a href="/docs">API Docs</a></p>
            </div>
        </div>

        <script>
        async function loadStats() {
            try {
                const [stats, agents, market] = await Promise.all([
                    fetch('/api/stats').then(r => r.json()),
                    fetch('/api/agents').then(r => r.json()),
                    fetch('/api/market').then(r => r.json()),
                ]);
                document.getElementById('stat-tasks').textContent = stats.completed_tasks || 0;
                document.getElementById('stat-agents').textContent = (market && market.active_agents) || 0;
                document.getElementById('stat-revenue').textContent = '$' + ((stats.total_revenue || 0).toFixed(2));
                document.getElementById('stat-auctions').textContent = stats.total_auctions || 0;

                const tbody = document.getElementById('agent-tbody');
                if (agents && agents.length) {
                    tbody.innerHTML = agents.map(a => {
                        const wr = a.wins + a.losses > 0 ? (a.wins / (a.wins + a.losses) * 100).toFixed(0) + '%' : '—';
                        return '<tr>' +
                            '<td><strong>' + a.dimension + '</strong><br><small>' + a.name + '</small></td>' +
                            '<td><code>' + a.model + '</code></td>' +
                            '<td><span class="badge ' + a.tier.toLowerCase() + '">' + a.tier + '</span></td>' +
                            '<td><strong>$' + a.wealth.toFixed(2) + '</strong></td>' +
                            '<td><span class="badge ' + a.status + '">' + a.status + '</span></td>' +
                            '<td>' + a.wins + '</td>' +
                            '<td>' + a.losses + '</td>' +
                            '<td>' + wr + '</td>' +
                            '<td>$' + a.last_bid.toFixed(2) + '</td>' +
                            '</tr>';
                    }).join('');
                } else {
                    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#8b949e;">No agents yet. Submit a task to start the economy.</td></tr>';
                }
            } catch(e) {
                console.error('Failed to load stats:', e);
            }
        }
        loadStats();
        setInterval(loadStats, 5000);
        </script>
    </body>
    </html>
    """)


# ── API Keys ─────────────────────────────────────────────────────────────────


@app.post("/api/keys", response_model=APIKeyResponse, tags=["Keys"])
async def create_api_key(body: APIKeyCreate):
    """Create a new API key for marketplace access."""
    key = generate_api_key()
    key_id = db.create_api_key(body.label, key)
    return APIKeyResponse(
        id=key_id,
        label=body.label,
        key=key,
        created_at=datetime.utcnow(),
        is_active=True,
    )


@app.get("/api/keys", response_model=list[APIKeyResponse], tags=["Keys"])
async def list_api_keys():
    """List all API keys (public keys only, full key shown at creation)."""
    return [
        APIKeyResponse(
            id=k["id"],
            label=k["label"],
            key=k["key"][:12] + "..." if len(k["key"]) > 12 else k["key"],
            created_at=datetime.fromisoformat(k["created_at"]) if isinstance(k["created_at"], str) else k["created_at"],
            last_used_at=datetime.fromisoformat(k["last_used_at"]) if k.get("last_used_at") and isinstance(k["last_used_at"], str) else k.get("last_used_at"),
            is_active=bool(k["is_active"]),
        )
        for k in db.list_api_keys()
    ]


# ── Tasks ─────────────────────────────────────────────────────────────────────


@app.post("/api/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, tags=["Tasks"])
async def submit_task(
    body: TaskSubmit,
    api_key: dict = Depends(verify_api_key),
):
    """Submit a task to the marketplace. Agents will bid on it via auction."""
    task_id = db.create_task(
        content=body.content,
        stakes=body.stakes,
        dimensions=body.dimensions,
        capabilities=body.capabilities,
        max_bid=body.max_bid,
        callback_url=body.callback_url,
        api_key_id=api_key["id"],
    )
    task = db.get_task(task_id)
    return _task_to_response(task)


@app.get("/api/tasks", response_model=list[TaskResponse], tags=["Tasks"])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    api_key: dict = Depends(verify_api_key),
):
    """List tasks submitted by this API key."""
    tasks = db.list_tasks(status=status, api_key_id=api_key["id"], limit=limit, offset=offset)
    return [_task_to_response(t) for t in tasks]


@app.get("/api/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
async def get_task(
    task_id: int,
    api_key: dict = Depends(verify_api_key),
):
    """Get the result of a task."""
    task = db.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["api_key_id"] != api_key["id"]:
        raise HTTPException(status_code=403, detail="Not your task")
    return _task_to_response(task)


def _task_to_response(task: dict) -> TaskResponse:
    return TaskResponse(
        id=task["id"],
        status=TaskStatus(task["status"]),
        content=task["content"],
        stakes=task["stakes"],
        dimensions=task.get("dimensions", []),
        capabilities=task.get("capabilities", []),
        max_bid=task["max_bid"],
        callback_url=task.get("callback_url"),
        created_at=datetime.fromisoformat(task["created_at"]) if isinstance(task["created_at"], str) else task["created_at"],
        completed_at=datetime.fromisoformat(task["completed_at"]) if task.get("completed_at") and isinstance(task["completed_at"], str) else task.get("completed_at"),
        winner_dimension=task.get("winner_dimension"),
        winner_name=task.get("winner_name"),
        winning_bid=task.get("winning_bid"),
        result=task.get("result"),
        error=task.get("error"),
        total_cost=task.get("total_cost"),
    )


# ── Agents ─────────────────────────────────────────────────────────────────────


@app.get("/api/agents", response_model=list[AgentResponse], tags=["Agents"])
async def list_agents():
    """List all agents in the marketplace with their wealth and status."""
    agents = db.list_agents()
    return [
        AgentResponse(
            dimension=a["dimension"],
            name=a["name"],
            model=a["model"],
            wealth=a["wealth"],
            status=AgentStatusModel(a["status"]),
            wins=a["wins"],
            losses=a["losses"],
            total_tasks=a["total_tasks"],
            total_reward=a["total_reward"],
            win_rate=a["wins"] / (a["wins"] + a["losses"]) if (a["wins"] + a["losses"]) > 0 else 0.0,
            last_bid=a["last_bid"],
            tier=a["tier"],
            capabilities=a.get("capabilities", []),
        )
        for a in agents
    ]


@app.get("/api/agents/{dimension}", response_model=AgentResponse, tags=["Agents"])
async def get_agent(dimension: str):
    """Get a specific agent by dimension key."""
    agent = db.get_agent(dimension)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse(
        dimension=agent["dimension"],
        name=agent["name"],
        model=agent["model"],
        wealth=agent["wealth"],
        status=AgentStatusModel(agent["status"]),
        wins=agent["wins"],
        losses=agent["losses"],
        total_tasks=agent["total_tasks"],
        total_reward=agent["total_reward"],
        win_rate=agent["wins"] / (agent["wins"] + agent["losses"]) if (agent["wins"] + agent["losses"]) > 0 else 0.0,
        last_bid=agent["last_bid"],
        tier=agent["tier"],
        capabilities=agent.get("capabilities", []),
    )


# ── Market ────────────────────────────────────────────────────────────────────


@app.get("/api/market", response_model=MarketOverview, tags=["Market"])
async def market_overview():
    """Get the current market overview with prices for each agent."""
    agents = db.list_agents()
    prices = []
    for a in agents:
        wr = a["wins"] / (a["wins"] + a["losses"]) if (a["wins"] + a["losses"]) > 0 else 0.0
        prices.append(MarketPrice(
            dimension=a["dimension"],
            model=a["model"],
            tier=a["tier"],
            base_bid=a["last_bid"],
            current_wealth=a["wealth"],
            suggested_bid=round(a["last_bid"] * 1.2, 2),
            win_rate=wr,
            status=AgentStatusModel(a["status"]),
        ))

    active = [a for a in agents if a["status"] != "bankrupt"]
    bankrupt = [a for a in agents if a["status"] == "bankrupt"]
    total_wealth = sum(a["wealth"] for a in agents)
    richest = max(agents, key=lambda a: a["wealth"]) if agents else None
    poorest = min(active, key=lambda a: a["wealth"]) if active else None

    return MarketOverview(
        prices=prices,
        total_agents=len(agents),
        active_agents=len(active),
        bankrupt_agents=len(bankrupt),
        total_auctions=sum(a["wins"] + a["losses"] for a in agents),
        total_wealth=round(total_wealth, 2),
        richest_agent=richest["dimension"] if richest else None,
        poorest_agent=poorest["dimension"] if poorest else None,
    )


# ── Transactions ──────────────────────────────────────────────────────────────


@app.get("/api/transactions", response_model=list[TransactionResponse], tags=["Transactions"])
async def list_transactions(
    task_id: Optional[int] = Query(None),
    agent: Optional[str] = Query(None, description="Agent dimension"),
    limit: int = Query(50, ge=1, le=200),
):
    """List marketplace transactions."""
    txs = db.list_transactions(task_id=task_id, agent_dimension=agent, limit=limit)
    return [
        TransactionResponse(
            id=t["id"],
            task_id=t["task_id"],
            agent_dimension=t["agent_dimension"],
            agent_name=t["agent_name"],
            bid_amount=t["bid_amount"],
            reward_amount=t["reward_amount"],
            net_change=t["net_change"],
            created_at=datetime.fromisoformat(t["created_at"]) if isinstance(t["created_at"], str) else t["created_at"],
        )
        for t in txs
    ]


# ── Stats ────────────────────────────────────────────────────────────────────


@app.get("/api/stats", response_model=StatsResponse, tags=["Stats"])
async def get_stats():
    """Get aggregate marketplace statistics."""
    stats = db.get_stats()
    agents = await list_agents()
    market = await market_overview()
    return StatsResponse(
        **stats,
        agents=agents,
        market=market,
    )


# ── VoidTether Mesh Integration ──────────────────────────────────────────────


@app.get("/api/mesh/agents", tags=["VoidTether"])
async def list_mesh_agents():
    """List all VoidTether mesh agents registered in the economy."""
    if vt_bridge is None:
        return {"agents": [], "error": "VoidTether bridge not initialized"}
    return {"agents": vt_bridge.discover_mesh_agents()}


@app.post("/api/mesh/register", tags=["VoidTether"])
async def register_mesh_agent(
    manifest: dict,
    api_key: dict = Depends(verify_api_key),
):
    """Register a VoidTether agent manifest into the HayekSwarm economy."""
    if vt_bridge is None:
        raise HTTPException(status_code=503, detail="VoidTether bridge not initialized")
    from voidtether.core.manifest import TetherManifest
    tether_manifest = TetherManifest.from_dict(manifest)
    dimension = vt_bridge.register_mesh_agent(tether_manifest)
    return {
        "status": "registered",
        "tether_id": tether_manifest.tether_id,
        "name": tether_manifest.name,
        "dimension": dimension,
    }


@app.post("/api/mesh/unregister/{tether_id}", tags=["VoidTether"])
async def unregister_mesh_agent(
    tether_id: str,
    api_key: dict = Depends(verify_api_key),
):
    """Remove a VoidTether agent from the economy."""
    if vt_bridge is None:
        raise HTTPException(status_code=503, detail="VoidTether bridge not initialized")
    vt_bridge.unregister_mesh_agent(tether_id)
    return {"status": "unregistered", "tether_id": tether_id}


@app.get("/api/mesh/stats", tags=["VoidTether"])
async def mesh_stats():
    """Get VoidTether bridge statistics."""
    if vt_bridge is None:
        return {"error": "VoidTether bridge not initialized"}
    return vt_bridge.get_stats()


# ── Wiki API ──────────────────────────────────────────────────────────────────


from server.wiki import init_wiki, get_wiki_stats, search_wiki, query_wiki, get_wiki_export, WIKI_PATH


@app.post("/api/wiki/init", tags=["Wiki"])
async def wiki_init():
    """Initialize the wiki directory structure + Obsidian vault."""
    result = init_wiki()
    return result


@app.get("/api/wiki/stats", tags=["Wiki"])
async def wiki_stats():
    """Get wiki statistics."""
    return get_wiki_stats()


@app.get("/api/wiki/search", tags=["Wiki"])
async def wiki_search(q: str = "", max_results: int = 10):
    """Search wiki pages by keyword."""
    return {"results": search_wiki(q, max_results=max_results)}


@app.post("/api/wiki/query", tags=["Wiki"])
async def wiki_query(question: str):
    """Query the wiki for relevant context."""
    return query_wiki(question)


@app.get("/api/wiki/export", tags=["Wiki"])
async def wiki_export():
    """Get wiki contents for Obsidian vault export."""
    return get_wiki_export()


@app.get("/api/wiki/vault", tags=["Wiki"])
async def wiki_vault():
    """Check if the wiki has an Obsidian vault configuration."""
    vault_path = WIKI_PATH / ".obsidian"
    if not vault_path.exists():
        return {"status": "no_vault", "path": str(WIKI_PATH)}
    return {
        "status": "configured",
        "path": str(WIKI_PATH),
        "vault_dir": str(vault_path),
        "templates": [
            str(p.relative_to(vault_path))
            for p in sorted(vault_path.rglob("*.md"))
        ] if vault_path.exists() else [],
    }


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["System"])
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "worker_running": worker.is_running if worker else False,
        "worker_active_tasks": len(worker._active_tasks) if worker else 0,
        "db_path": str(db.db_path) if db else "not initialized",
    }
