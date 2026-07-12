from __future__ import annotations
import asyncio
import json
import os
import time
from typing import Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from voidtether.core import TetherManifest, Protocol, TetherRouter, ProtocolBridge
from voidtether.mesh import Mesh
from voidtether.server.sessions import (
    Session, SessionManager, ChatMessage, MessageRole, SessionStatus,
)
from voidtether.server.events import EventBus, MeshEvent, get_event_bus
from voidtether.core.middleware_auth import verify_tether_auth
from voidtether.server.admin import OrchestratorAdmin, get_admin
from voidtether.server.changelog import ChangeLog, get_changelog
from voidtether.server.agent_persistence import AgentPersistence, get_agent_db
from voidtether.economy import EconomyConfig

# ── Rate Limiter Middleware ──────────────────────────────────────────

class RateLimiterMiddleware:
    """In-memory sliding window rate limiter.

    Uses per-agent-id (X-Tether-Id header) and per-IP sliding windows.
    Defaults: 100 req/min per agent, 300 req/min per IP.
    Returns 429 with Retry-After on exceed.
    """

    def __init__(
        self,
        app: Any,
        agent_limit: int = 100,
        ip_limit: int = 300,
        window_seconds: int = 60,
    ):
        self.app = app
        self.agent_limit = agent_limit
        self.ip_limit = ip_limit
        self.window_seconds = window_seconds
        self._agent_windows: dict[str, list[float]] = {}
        self._ip_windows: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def __call__(self, scope: dict, receive: callable, send: callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract agent-id from headers
        headers = dict(scope.get("headers", []))
        agent_id = None
        for k, v in headers.items():
            if k.lower() == b"x-tether-id":
                agent_id = v.decode("utf-8", errors="replace")
                break

        # Extract client IP
        client_ip = "unknown"
        # Try X-Forwarded-For first, then peer address
        for k, v in headers.items():
            if k.lower() == b"x-forwarded-for":
                client_ip = v.decode("utf-8", errors="replace").split(",")[0].strip()
                break
        if client_ip == "unknown":
            client_info = scope.get("client")
            if client_info:
                client_ip = client_info[0]

        now = time.time()
        cutoff = now - self.window_seconds

        async with self._lock:
            # Per-agent rate limit
            if agent_id:
                if agent_id not in self._agent_windows:
                    self._agent_windows[agent_id] = []
                self._agent_windows[agent_id] = [
                    t for t in self._agent_windows[agent_id] if t > cutoff
                ]
                if len(self._agent_windows[agent_id]) >= self.agent_limit:
                    retry_after = int(
                        self._agent_windows[agent_id][0] + self.window_seconds - now
                    )
                    await self._send_429(send, retry_after, "agent")
                    return
                self._agent_windows[agent_id].append(now)

            # Per-IP rate limit
            if client_ip:
                if client_ip not in self._ip_windows:
                    self._ip_windows[client_ip] = []
                self._ip_windows[client_ip] = [
                    t for t in self._ip_windows[client_ip] if t > cutoff
                ]
                if len(self._ip_windows[client_ip]) >= self.ip_limit:
                    retry_after = int(
                        self._ip_windows[client_ip][0] + self.window_seconds - now
                    )
                    await self._send_429(send, retry_after, "ip")
                    return
                self._ip_windows[client_ip].append(now)

        await self.app(scope, receive, send)

    async def _send_429(self, send: callable, retry_after: int, limit_type: str) -> None:
        body = json.dumps({
            "detail": f"Rate limit exceeded ({limit_type}). Try again in {retry_after}s.",
            "retry_after": retry_after,
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(retry_after).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

# ── Pydantic models for API ──────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    title: str = Field(default="Untitled Session", min_length=1, max_length=200)
    participants: list[str] = Field(default_factory=list, max_length=50)
    human_in_loop: bool = False
    turn_policy: str = Field(default="round_robin", pattern="^(round_robin|priority|llm_selected|human_moderator)$")
    max_turns: int = Field(default=100, ge=1, le=10000)

class SendMessageRequest(BaseModel):
    sender: str = Field(default="user", min_length=1, max_length=100)
    sender_name: str = Field(default="User", min_length=1, max_length=200)
    content: str = Field(default="", max_length=50000)
    role: str = Field(default="user", pattern="^(user|agent|system|human_gate)$")
    requires_approval: bool = False

class RegisterAgentRequest(BaseModel):
    tether_id: str = Field(default="", min_length=0, max_length=100)
    name: str = Field(default="", min_length=0, max_length=200)
    protocol: str = Field(default="custom", pattern="^(a2a|mcp|hermes|swarm|openclaw|crewai|langgraph|gbrain|acp|k2|taste|custom)$")
    capabilities: dict[str, Any] = Field(default_factory=dict)
    endpoint_url: str = Field(default="", max_length=500)
    acp_command: str = Field(default="", max_length=500)  # CLI command for ACP stdio agents

class DelegateTaskRequest(BaseModel):
    task_type: str = Field(default="", min_length=1, max_length=200)
    input_data: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="user", min_length=1, max_length=100)
    source_protocol: str = Field(default="custom", pattern="^(a2a|mcp|hermes|swarm|openclaw|crewai|langgraph|gbrain|acp|k2|taste|custom)$")
    target_protocol: str | None = None

class ApproveGateRequest(BaseModel):
    approved: bool = True
    message_id: str = Field(default="", min_length=1, max_length=100)


# ── App factory ──────────────────────────────────────────────────────

def create_app(mesh: Mesh | None = None) -> FastAPI:
    """Create the VoidTether FastAPI application."""

    if mesh is None:
        mesh = Mesh()

    # P1: SQLite persistence (optional, graceful fallback to in-memory)
    db_path = os.environ.get("VOIDTETHER_DB_PATH")
    session_mgr = SessionManager(db_path=db_path)
    event_bus = get_event_bus()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print("⚫ VoidTether mesh server starting...")
        print("   The cord that binds across the void.")
        
        # Restore persisted agents from SQLite (survives restarts)
        agent_db = get_agent_db()
        restored_manifests = agent_db.load_all()
        restored_count = 0
        for manifest in restored_manifests:
            if not mesh.router.get(manifest.tether_id):
                mesh.register(manifest)
                restored_count += 1
        if restored_count > 0:
            print(f"   ✅ Restored {restored_count} agent(s) from SQLite persistence")
            for m in restored_manifests:
                print(f"       - {m.tether_id} '{m.name}'")
        
        # Init changelog and record startup
        changelog = get_changelog()
        
        # Compare pre-shutdown state with current to detect losses
        current_agents = [m.tether_id for m in mesh.list_agents()]
        current_sessions = [s.session_id for s in session_mgr.list_sessions()]
        diff = changelog.diff_shutdown_vs_startup(current_sessions, current_agents)
        
        dropped_sessions = diff.get("dropped_sessions", [])
        dropped_agents = diff.get("dropped_agents", [])
        
        if dropped_sessions:
            print(f"   ⚠️  {len(dropped_sessions)} session(s) lost during restart:")
            for sd in diff.get("session_details", []):
                print(f"       - {sd.get('session_id', '?')[:12]}... '{sd.get('title', '?')}' ({sd.get('messages', 0)} msgs)")
                changelog.record_session_dropped(sd.get('session_id', '?'), sd.get('title', '?'), sd.get('messages', 0))
        
        if dropped_agents:
            print(f"   ⚠️  {len(dropped_agents)} agent(s) lost during restart:")
            for ad in diff.get("agent_details", []):
                print(f"       - {ad.get('tether_id', '?')} '{ad.get('name', '?')}'")
                changelog.record_agent_dropped(ad.get('tether_id', '?'), ad.get('name', '?'), ad.get('protocol', '?'))
        
        if not dropped_sessions and not dropped_agents:
            print("   ✅ No state loss detected")
        
        changelog.record_startup(
            restored_sessions=len(current_sessions),
            restored_agents=len(current_agents),
            dropped_sessions=dropped_sessions,
            dropped_agents=dropped_agents,
        )
        
        # Register the Orchestrator Admin directly in-process
        admin = get_admin()
        try:
            manifest = TetherManifest(
                tether_id=admin.ADMIN_TETHER_ID,
                name=admin.ADMIN_NAME,
                origin_protocol=Protocol.HERMES,
                capabilities={
                    "tasks": [
                        "orchestrate", "assign_task", "manage_session",
                        "approve_gate", "manage_agents", "audit",
                        "task_scheduling", "workflow_control",
                        "load_balance", "fault_recovery",
                    ],
                    "admin": True,
                    "role": "super_admin",
                },
            )
            mesh.register(manifest)
            agent_db.persist(manifest)  # Persist admin so it survives restart
            admin._registered = True
            print(f"   ✅ Orchestrator Admin registered: {admin.ADMIN_TETHER_ID}")
        except Exception as e:
            print(f"   ⚠️  Orchestrator Admin registration: {e}")
        
        yield
        
        # Shutdown: save pre-shutdown state so next startup can diff
        print("⚫ VoidTether mesh server shutting down.")
        try:
            session_mgr.stop_cleanup()
            agents_data = [{"tether_id": m.tether_id, "name": m.name, "protocol": m.origin_protocol.value} for m in mesh.list_agents()]
            sessions_data = [{"session_id": s.session_id, "title": s.title, "messages": len(s.messages), "participants": s.participants} for s in session_mgr.list_sessions()]
            changelog.save_pre_shutdown_state(sessions_data, agents_data)
            changelog.record_shutdown(len(sessions_data), len(agents_data))
        except Exception as e:
            print(f"   ⚠️  Failed to save pre-shutdown state: {e}")

    app = FastAPI(
        title="VoidTether",
        description="The cord that binds across the void — multi-agent interaction mesh",
        version="0.4.0",
        lifespan=lifespan,
    )

    from voidtether.server.semantic_routes import router as semantic_router
    app.include_router(semantic_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8901", "http://127.0.0.1:8901"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiter — class-based ASGI middleware wrapping all routes
    app.add_middleware(RateLimiterMiddleware, agent_limit=100, ip_limit=300, window_seconds=60)

    # ── Serve God View dashboard ──────────────────────────────────────
    from fastapi.responses import HTMLResponse
    _GOD_VIEW_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "god_view.html")
    # Also check ~/god_view.html and /Users/admin/god_view.html
    for _p in [_GOD_VIEW_PATH, os.path.expanduser("~/god_view.html"), "/Users/admin/god_view.html"]:
        if os.path.exists(_p):
            _GOD_VIEW_PATH = _p
            break

    @app.get("/godview", response_class=HTMLResponse)
    async def god_view():
        try:
            with open(_GOD_VIEW_PATH) as f:
                return HTMLResponse(f.read())
        except FileNotFoundError:
            return HTMLResponse("<h1>god_view.html not found</h1><p>Place god_view.html in the project root.</p>", status_code=404)

    app.state.mesh = mesh
    app.state.sessions = session_mgr
    app.state.events = event_bus

    @app.get("/")
    async def root():
        agents = mesh.list_agents()
        sessions = session_mgr.list_sessions()
        return {
            "name": "VoidTether",
            "version": "0.4.0",
            "tagline": "The cord that binds across the void",
            "agents": len(agents),
            "sessions": len(sessions),
            "protocols": [p.value for p in Protocol],
        }

    @app.get("/health")
    async def liveness():
        return {"status": "alive", "version": "0.4.0"}

    @app.get("/ready")
    async def readiness():
        return {
            "status": "ready",
            "version": "0.4.0",
            "agents": len(mesh.list_agents()),
            "sessions": len(session_mgr.list_sessions()),
        }

    @app.get("/api/health/detailed")
    async def detailed_health():
        """Detailed health monitoring endpoint for the God View dashboard."""
        import time as _time
        agents = mesh.list_agents()
        sessions = session_mgr.list_sessions()

        # Per-agent health from the bridge's health monitor
        agent_health = []
        for a in agents:
            hc = mesh.bridge.health.get_health(a.tether_id)
            agent_health.append({
                "tether_id": a.tether_id,
                "name": a.name,
                "protocol": a.origin_protocol.value,
                "capabilities": a.capabilities,
                "status": hc.status.value,
                "latency_ms": round(hc.latency_ms, 1),
                "failures": hc.consecutive_failures,
                "successes": hc.consecutive_successes,
                "last_check": hc.last_check,
                "origin_ip": a.metadata.get("origin_ip", "unknown"),
            })

        # Per-session health
        session_health = []
        for s in sessions:
            session_health.append({
                "session_id": s.session_id,
                "title": s.title,
                "status": s.status.value,
                "participants": len(s.participants),
                "messages": len(s.messages),
                "turn_policy": s.turn_policy,
                "current_turn": s.current_turn,
                "max_turns": s.max_turns,
                "active_tasks": len(s.active_tasks),
                "human_in_loop": s.human_in_loop,
            })

        # Bridge + pool stats
        pool_stats = mesh.bridge.pool.stats()
        bridge_stats = {
            "pool": pool_stats,
            "pool_max_per_endpoint": mesh.bridge.pool.max_per_endpoint,
            "execute_timeout": mesh.bridge.execute_timeout,
            "retry_policy": {
                "max_retries": mesh.bridge.retry_policy.max_retries,
                "base_delay": mesh.bridge.retry_policy.base_delay,
                "max_delay": mesh.bridge.retry_policy.max_delay,
            },
        }

        # Persistence status
        persist_status = {
            "enabled": session_mgr._db is not None,
            "db_path": session_mgr._db_path or None,
        }

        # All health from monitor
        all_hc = mesh.bridge.health.all_health()

        return {
            "timestamp": _time.time(),
            "hub": {
                "status": "alive",
                "version": "0.4.0",
            },
            "agents": {
                "total": len(agents),
                "details": agent_health,
            },
            "sessions": {
                "total": len(sessions),
                "details": session_health,
            },
            "event_bus": {
                "subscriber_count": event_bus.subscriber_count,
                "max_subscribers": event_bus.MAX_SUBSCRIBERS,
            },
            "bridge": bridge_stats,
            "persistence": persist_status,
        }

    @app.get("/api/agents")
    async def list_agents():
        return [m.to_dict() for m in mesh.list_agents()]

    @app.post("/api/agents")
    @app.post("/api/agents/register")
    async def register_agent(req: RegisterAgentRequest, request: Request, auth: bool = Depends(verify_tether_auth)):
        protocol = Protocol(req.protocol)
        # Capture source IP for locality tracking
        client_ip = request.client.host if request.client else "unknown"
        manifest = TetherManifest(
            tether_id=req.tether_id or f"vt-{req.protocol}-{req.name.lower().replace(' ', '-')}",
            name=req.name or f"{req.protocol} agent",
            origin_protocol=protocol,
            capabilities=req.capabilities,
        )
        # Wire ACP protocol endpoint if acp_command is provided
        if req.acp_command and protocol == Protocol.ACP:
            from voidtether.core.manifest import ProtocolEndpoint
            manifest.protocols.append(ProtocolEndpoint(
                protocol=Protocol.ACP,
                acp_command=req.acp_command,
                acp_transport="stdio",
                endpoint_url=req.endpoint_url or f"stdio://{manifest.tether_id}",
            ))
        # Store origin IP in metadata for locality debugging
        manifest.metadata["origin_ip"] = client_ip
        mesh.register(manifest)
        # Persist to SQLite so agent survives restarts
        agent_db = get_agent_db()
        agent_db.persist(manifest)
        # Audit log
        changelog = get_changelog()
        changelog.record_audit(
            agent_id=manifest.tether_id,
            action="register_agent",
            source_ip=client_ip,
            details={"name": manifest.name, "protocol": req.protocol},
        )
        try:
            await event_bus.publish_agent_join("", manifest.tether_id, manifest.name)
        except Exception:
            pass
        return {"status": "registered", "tether_id": manifest.tether_id, "manifest": manifest.to_dict()}

    @app.delete("/api/agents/{tether_id}")
    async def unregister_agent(tether_id: str, request: Request):
        manifest = mesh.router.get(tether_id)
        if not manifest:
            raise HTTPException(404, f"Agent {tether_id} not found")
        client_ip = request.client.host if request.client else "unknown"
        mesh.unregister(tether_id)
        # Remove from SQLite persistence
        agent_db = get_agent_db()
        agent_db.remove(tether_id)
        # Audit log
        changelog = get_changelog()
        changelog.record_audit(
            agent_id=tether_id,
            action="unregister_agent",
            source_ip=client_ip,
            details={"name": manifest.name},
        )
        await event_bus.publish_system("", f"{manifest.name} left the mesh")
        return {"status": "unregistered", "tether_id": tether_id}

    @app.get("/api/agents/persisted")
    async def list_persisted_agents():
        """List all agents persisted in SQLite (survives restarts)."""
        agent_db = get_agent_db()
        return {"agents": agent_db.list_persisted(), "count": agent_db.count()}

    @app.get("/api/agents/discover")
    async def discover_agents_query(task_type: str = "", protocol: str | None = None):
        proto = Protocol(protocol) if protocol else None
        agents = mesh.discover_all(task_type, protocol=proto)
        return [m.to_dict() for m in agents]

    @app.get("/api/agents/discover/{task_type}")
    async def discover_agents(task_type: str, protocol: str | None = None):
        proto = Protocol(protocol) if protocol else None
        agents = mesh.discover_all(task_type, protocol=proto)
        return [m.to_dict() for m in agents]

    @app.get("/api/sessions")
    async def list_sessions():
        return [s.to_dict() for s in session_mgr.list_sessions()]

    @app.post("/api/sessions")
    async def create_session(req: CreateSessionRequest, request: Request):
        session = session_mgr.create_session(
            title=req.title,
            participants=req.participants,
            human_in_loop=req.human_in_loop,
            turn_policy=req.turn_policy,
            max_turns=req.max_turns,
        )
        # Audit log
        client_ip = request.client.host if request.client else "unknown"
        changelog = get_changelog()
        changelog.record_audit(
            agent_id=session.session_id,
            action="create_session",
            source_ip=client_ip,
            details={"title": req.title, "participants": req.participants},
        )
        await event_bus.publish_system(
            session.session_id,
            f"Session created: {req.title}",
        )
        return session.to_dict()

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")
        return session.to_dict()

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")
        # Audit log
        client_ip = request.client.host if request.client else "unknown"
        changelog = get_changelog()
        changelog.record_audit(
            agent_id=session_id,
            action="delete_session",
            source_ip=client_ip,
            details={"title": session.title},
        )
        session_mgr.delete_session(session_id)
        return {"status": "deleted"}

    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, req: SendMessageRequest):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")

        # ── P0: Turn Policy Enforcement ────────────────────────────────
        allowed, reason = session.can_speak(req.sender, req.role)
        if not allowed:
            raise HTTPException(429, f"Turn policy violation: {reason}")
        # ──────────────────────────────────────────────────────────────

        msg = ChatMessage(
            session_id=session_id,
            role=MessageRole(req.role),
            sender=req.sender,
            sender_name=req.sender_name,
            content=req.content,
            requires_approval=req.requires_approval,
        )
        session.add_message(msg)
        session_mgr.update_session(session)  # P1: persist

        await event_bus.publish_message(
            session_id=session_id,
            sender=req.sender,
            sender_name=req.sender_name,
            content=req.content,
            event_type="message",
            message_id=msg.message_id,
            role=req.role,
            requires_approval=req.requires_approval,
        )

        return msg.to_dict()

    @app.get("/api/sessions/{session_id}/messages")
    async def get_messages(session_id: str, limit: int = 100, offset: int = 0):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")
        messages = session.messages[offset:offset + limit]
        return [m.to_dict() for m in messages]

    @app.post("/api/sessions/{session_id}/approve/{message_id}")
    async def approve_gate(session_id: str, message_id: str, req: ApproveGateRequest):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")

        for msg in session.messages:
            if msg.message_id == message_id:
                msg.approved = req.approved
                session_mgr.update_session(session)  # P1: persist
                await event_bus.publish(
                    MeshEvent(
                        event_type="gate_approved" if req.approved else "gate_rejected",
                        session_id=session_id,
                        sender="system",
                        content=f"Gate {'approved' if req.approved else 'rejected'}: {message_id}",
                        data={"message_id": message_id, "approved": req.approved},
                    )
                )
                return msg.to_dict()

        raise HTTPException(404, f"Message {message_id} not found")

    @app.post("/api/sessions/{session_id}/delegate")
    async def delegate_task(session_id: str, req: DelegateTaskRequest):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")

        source_protocol = Protocol(req.source_protocol)
        target_protocol = Protocol(req.target_protocol) if req.target_protocol else None

        result = await mesh.auto_delegate(
            task=req.task_type,
            input_data=req.input_data,
            source=req.source,
            source_protocol=source_protocol,
            target_protocol=target_protocol,
        )

        msg = ChatMessage(
            session_id=session_id,
            role=MessageRole.AGENT,
            sender=result.get("assigned_to", "mesh"),
            sender_name=result.get("assigned_to", "Agent"),
            content=result.get("text", result.get("response", json.dumps(result))),
            metadata=result,
        )
        session.add_message(msg)
        session_mgr.update_session(session)  # P1: persist

        await event_bus.publish_message(
            session_id=session_id,
            sender=msg.sender,
            sender_name=msg.sender_name,
            content=msg.content,
            event_type="task_complete",
            task_id=result.get("task_id", "L-TICKET"),
        )

        return {"result": result, "message": msg.to_dict()}

    # ── Orchestrator Admin Endpoints ──────────────────────────────────

    @app.get("/api/admin/agents")
    async def admin_list_agents():
        """Admin: list all agents with orchestration context."""
        admin = get_admin()
        agents = await admin.list_agents()
        return {"admin": admin.ADMIN_TETHER_ID, "agents": agents}

    @app.get("/api/admin/agents/discover")
    async def admin_discover_agents(task_type: str = "", protocol: str | None = None):
        """Admin: discover agents by capability."""
        admin = get_admin()
        agents = await admin.discover_agents(task_type, protocol)
        return {"admin": admin.ADMIN_TETHER_ID, "agents": agents}

    @app.delete("/api/admin/agents/{tether_id}")
    async def admin_unregister_agent(tether_id: str):
        """Admin: forcibly unregister an agent from the mesh."""
        admin = get_admin()
        result = await admin.unregister_agent(tether_id)
        return {"admin": admin.ADMIN_TETHER_ID, "result": result}

    @app.post("/api/admin/sessions")
    async def admin_create_session(req: CreateSessionRequest):
        """Admin: create an orchestrated session."""
        admin = get_admin()
        session = await admin.create_session(
            title=req.title,
            participants=req.participants or [admin.ADMIN_TETHER_ID],
            turn_policy=req.turn_policy,
            human_in_loop=req.human_in_loop,
            max_turns=req.max_turns,
        )
        return {"admin": admin.ADMIN_TETHER_ID, "session": session}

    @app.get("/api/admin/sessions")
    async def admin_list_sessions():
        """Admin: list all sessions."""
        admin = get_admin()
        sessions = await admin.list_sessions()
        return {"admin": admin.ADMIN_TETHER_ID, "sessions": sessions}

    @app.delete("/api/admin/sessions/{session_id}")
    async def admin_delete_session(session_id: str):
        """Admin: terminate a session."""
        admin = get_admin()
        result = await admin.delete_session(session_id)
        return {"admin": admin.ADMIN_TETHER_ID, "result": result}

    @app.post("/api/admin/sessions/{session_id}/assign")
    async def admin_assign_task(session_id: str, req: DelegateTaskRequest):
        """Admin: assign a task to the best agent."""
        admin = get_admin()
        result = await admin.assign_task(
            session_id=session_id,
            task_type=req.task_type,
            input_data=req.input_data,
            target_protocol=req.target_protocol,
        )
        return {"admin": admin.ADMIN_TETHER_ID, "result": result}

    @app.post("/api/admin/sessions/{session_id}/approve/{message_id}")
    async def admin_approve_gate(session_id: str, message_id: str, req: ApproveGateRequest):
        """Admin: approve or reject a human-gate message."""
        admin = get_admin()
        result = await admin.approve_gate(session_id, message_id, req.approved)
        return {"admin": admin.ADMIN_TETHER_ID, "result": result}

    @app.post("/api/admin/sessions/{session_id}/message")
    async def admin_send_message(session_id: str, req: SendMessageRequest):
        """Admin: send a system message to a session."""
        admin = get_admin()
        result = await admin.send_message(session_id, req.content, role=req.role)
        return {"admin": admin.ADMIN_TETHER_ID, "result": result}

    @app.get("/api/admin/audit")
    async def admin_audit_log(limit: int = 50):
        """Admin: get the audit log of admin actions."""
        admin = get_admin()
        log = admin.get_audit_log(limit=limit)
        return {"admin": admin.ADMIN_TETHER_ID, "audit_log": log}

    @app.get("/api/admin/health")
    async def admin_health():
        """Admin: detailed health of the entire mesh."""
        admin = get_admin()
        health = await admin.detailed_health()
        return {"admin": admin.ADMIN_TETHER_ID, "health": health}

    @app.post("/api/k2/swarm/{execution_id}/message")
    async def k2_send_to_agent(execution_id: str, req: Request):
        """K2-008: Send a message to a specific agent within a swarm execution."""
        body = await req.json()
        target_agent = body.get("agent_id", "")
        message = body.get("message", {})
        from voidtether.adapters.k2 import K2Adapter
        adapter = None
        for a in mesh.bridge._adapters.values():
            if isinstance(a, K2Adapter):
                adapter = a
                break
        if not adapter:
            raise HTTPException(404, "K2 adapter not found")
        result = await adapter.send_to_agent(execution_id, target_agent, message)
        return {"result": result}

    @app.post("/api/k2/swarm/{execution_id}/broadcast")
    async def k2_broadcast_to_swarm(execution_id: str, req: Request):
        """K2-008: Broadcast a message to all agents in a swarm execution."""
        body = await req.json()
        message = body.get("message", {})
        from voidtether.adapters.k2 import K2Adapter
        adapter = None
        for a in mesh.bridge._adapters.values():
            if isinstance(a, K2Adapter):
                adapter = a
                break
        if not adapter:
            raise HTTPException(404, "K2 adapter not found")
        results = await adapter.broadcast_to_swarm(execution_id, message)
        return {"results": results}

    @app.get("/api/k2/executions")
    async def k2_list_executions():
        """K2-007: List all persisted K2 swarm executions."""
        from voidtether.adapters.k2 import K2Adapter
        adapter = None
        for a in mesh.bridge._adapters.values():
            if isinstance(a, K2Adapter):
                adapter = a
                break
        if not adapter or not adapter._db:
            return {"executions": []}
        try:
            cursor = adapter._db.execute("SELECT execution_id, session_id, task_type, status, created_at, completed_at FROM k2_executions ORDER BY created_at DESC LIMIT 50")
            rows = cursor.fetchall()
            return {"executions": [{"execution_id": r[0], "session_id": r[1], "task_type": r[2], "status": r[3], "created_at": r[4], "completed_at": r[5]} for r in rows]}
        except Exception:
            return {"executions": []}

    @app.get("/api/k2/metrics")
    async def k2_metrics():
        """K2-005: Get load balancer metrics for all agents."""
        from voidtether.adapters.k2 import K2Adapter
        adapter = None
        for a in mesh.bridge._adapters.values():
            if isinstance(a, K2Adapter):
                adapter = a
                break
        if not adapter:
            return {"metrics": {}}
        return {"metrics": adapter._agent_metrics}

    @app.get("/api/changelog")
    async def get_changelog_api(limit: int = 50):
        """Get the hub lifecycle changelog — tracks restarts, lost sessions/agents."""
        changelog = get_changelog()
        return {"events": changelog.get_recent_events(limit=limit)}

    @app.get("/api/changelog/last-state")
    async def get_last_state():
        """Get the last saved pre-shutdown state for comparison."""
        changelog = get_changelog()
        state = changelog.get_pre_shutdown_state()
        return {"state": state}

    # ── P0: Session-scoped SSE stream ─────────────────────────────────
    @app.get("/api/sessions/{session_id}/stream")
    async def sse_stream(session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session {session_id} not found")

        queue = event_bus.subscribe(session_id=session_id)

        async def event_generator():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30)
                        yield event.to_sse()
                    except asyncio.TimeoutError:
                        yield f"event: ping\ndata: {{}}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                event_bus.unsubscribe(queue, session_id=session_id)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── P0: Session-scoped WebSocket with backpressure handling ───────
    @app.websocket("/ws/{session_id}")
    async def websocket_session(websocket: WebSocket, session_id: str):
        await websocket.accept()

        session = session_mgr.get_session(session_id)
        if not session:
            await websocket.close(code=4004, reason="Session not found")
            return

        queue = event_bus.subscribe(session_id=session_id)

        await websocket.send_json({
            "type": "session_history",
            "session": session.to_dict(),
        })

        async def receive_loop():
            try:
                while True:
                    data = await websocket.receive_json()
                    msg_type = data.get("type", "message")

                    if msg_type == "message":
                        # P0: Turn policy enforcement on WS messages too
                        sender = data.get("sender", "user")
                        role = data.get("role", "user")
                        allowed, reason = session.can_speak(sender, role)
                        if not allowed:
                            await websocket.send_json({
                                "type": "turn_rejected",
                                "reason": reason,
                                "sender": sender,
                            })
                            continue

                        msg = ChatMessage(
                            session_id=session_id,
                            role=MessageRole(role),
                            sender=sender,
                            sender_name=data.get("sender_name", "User"),
                            content=data.get("content", ""),
                        )
                        session.add_message(msg)
                        session_mgr.update_session(session)
                        await event_bus.publish_message(
                            session_id=session_id,
                            sender=msg.sender,
                            sender_name=msg.sender_name,
                            content=msg.content,
                            event_type="message",
                            message_id=msg.message_id,
                            role=msg.role,
                            requires_approval=msg.requires_approval,
                        )

                    elif msg_type == "approve":
                        message_id = data.get("message_id", "")
                        approved = data.get("approved", True)
                        for msg in session.messages:
                            if msg.message_id == message_id:
                                msg.approved = approved
                                session_mgr.update_session(session)
                                await event_bus.publish(
                                    MeshEvent(
                                        event_type="gate_approved" if approved else "gate_rejected",
                                        session_id=session_id,
                                        sender="system",
                                        content=f"Gate {'approved' if approved else 'rejected'}: {message_id}",
                                        data={"message_id": message_id, "approved": approved},
                                    )
                                )
                                break

                    elif msg_type == "delegate":
                        result = await mesh.auto_delegate(
                            task=data.get("task_type", ""),
                            input_data=data.get("input_data", {}),
                            source=data.get("source", "user"),
                            source_protocol=Protocol(data.get("source_protocol", "custom")),
                        )
                        await event_bus.publish(
                            MeshEvent(
                                event_type="task_complete",
                                session_id=session_id,
                                sender=result.get("assigned_to", "mesh"),
                                content=json.dumps(result),
                                data=result,
                            )
                        )
            except WebSocketDisconnect:
                pass

        async def send_loop():
            try:
                while True:
                    event = await queue.get()
                    await websocket.send_json(event.to_dict())
            except WebSocketDisconnect:
                pass
            except Exception:
                # P2: Backpressure — client may be slow or disconnected.
                # Drain the queue to prevent event bus buildup.
                pass

        receive_task = asyncio.create_task(receive_loop())
        send_task = asyncio.create_task(send_loop())

        try:
            await asyncio.gather(receive_task, send_task)
        except WebSocketDisconnect:
            pass
        finally:
            receive_task.cancel()
            send_task.cancel()
            event_bus.unsubscribe(queue, session_id=session_id)

    # ── Economy Endpoints ────────────────────────────────────────────

    @app.get("/api/economy/wealth")
    async def economy_wealth():
        """Get wealth distribution for all agents."""
        return {
            "wealth": mesh.get_wealth_distribution(),
            "mode": mesh.router.mode,
        }

    @app.get("/api/economy/wealth/{tether_id}")
    async def economy_agent_wealth(tether_id: str):
        """Get a single agent's wealth."""
        agent = mesh.get_economic_agent(tether_id)
        if agent is None:
            raise HTTPException(404, f"Agent {tether_id} not found in economy")
        return agent.to_dict()

    @app.get("/api/economy/config")
    async def economy_get_config():
        """Get current economy configuration."""
        return mesh.router.config.to_dict()

    @app.post("/api/economy/config")
    async def economy_update_config(req: Request):
        """Update economy configuration."""
        body = await req.json()
        new_config = EconomyConfig.from_dict(body)
        mesh.router.config = new_config
        return {"status": "updated", "config": new_config.to_dict()}

    @app.post("/api/economy/mode")
    async def economy_set_mode(req: Request):
        """Set routing mode: 'economic' or 'capability'."""
        body = await req.json()
        mode = body.get("mode", "economic")
        mesh.set_economy_mode(mode)
        return {"status": "updated", "mode": mode}

    @app.get("/api/economy/stats")
    async def economy_stats():
        """Get economic engine statistics."""
        return mesh.get_economy_stats()

    return app