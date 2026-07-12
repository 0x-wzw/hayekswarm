"""VoidTether Remote Agent SDK — Zero-config integration with the ACP Hub.

Usage (zero-config):
    from voidtether_sdk import VoidTetherClient

    client = VoidTetherClient.auto()          # auto-detects hub via env or default
    await client.register("my-agent", tasks=["research"])  # one-line onboarding
    session = await client.create_session("My Session", participants=["my-agent"])
    await client.send_message(session["session_id"], "Hello mesh!")
    async for event in client.stream(session["session_id"]):
        print(event)

Advanced (explicit config):
    client = VoidTetherClient(
        hub_url="http://100.84.202.9:8901",
        secret=os.environ["VOIDTETHER_HMAC_SECRET"],
        tether_id="my-agent",
        name="My Agent",
        protocol="hermes",
        capabilities={"tasks": ["research"]},
    )
    await client.register()
"""

from __future__ import annotations
import hmac
import hashlib
import time
import json
import asyncio
import os
import secrets
import uuid
from typing import Any, Callable, AsyncIterator
from dataclasses import dataclass, field

import httpx

try:
    import websockets
    _HAS_WS = True
except ImportError:
    _HAS_WS = False

# ── Defaults (zero-config) ────────────────────────────────────────────

DEFAULT_HUB_URL = "http://100.84.202.9:8901"
DEFAULT_SECRET = None  # no public default; set VOIDTETHER_HMAC_SECRET
DEFAULT_PROTOCOL = "hermes"
DEFAULT_TIMEOUT = 30.0


@dataclass
class AgentIdentity:
    """Auto-generated agent identity for zero-config onboarding."""
    tether_id: str = ""
    name: str = ""
    protocol: str = DEFAULT_PROTOCOL
    capabilities: dict[str, Any] = field(default_factory=lambda: {"tasks": []})

    @classmethod
    def auto(cls, name: str | None = None, tasks: list[str] | None = None) -> "AgentIdentity":
        """Generate a random identity — no config needed."""
        short_id = str(uuid.uuid4())[:8]
        return cls(
            tether_id=f"agent-{short_id}",
            name=name or f"Remote Agent {short_id}",
            protocol=DEFAULT_PROTOCOL,
            capabilities={"tasks": tasks or ["general"]},
        )


class VoidTetherClient:
    """Zero-config client for remote agents to integrate with the VoidTether Hub.

    Connection priority:
      1. Explicit constructor args
      2. Environment variables (VOIDTETHER_HUB_URL, VOIDTETHER_HMAC_SECRET, VOIDTETHER_TETHER_ID)
      3. Built-in defaults (Tailscale nexus IP, dev secret)
    """

    def __init__(
        self,
        hub_url: str | None = None,
        secret: str | None = None,
        tether_id: str | None = None,
        name: str | None = None,
        protocol: str | None = None,
        capabilities: dict[str, Any] | None = None,
        endpoint_url: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ):
        # Resolve from args → env → defaults
        self.hub_url = hub_url or os.environ.get("VOIDTETHER_HUB_URL", DEFAULT_HUB_URL)
        self.secret = secret or os.environ.get("VOIDTETHER_HMAC_SECRET")
        if not self.secret:
            # Fail closed: no shared secret configured -> use an ephemeral one so
            # signatures will not verify against a real hub until it is set.
            self.secret = secrets.token_hex(32)
        self.tether_id = tether_id or os.environ.get("VOIDTETHER_TETHER_ID", f"agent-{str(uuid.uuid4())[:8]}")
        self.name = name or f"Remote Agent {self.tether_id[-8:]}"
        self.protocol = protocol or DEFAULT_PROTOCOL
        self.capabilities = capabilities or {"tasks": ["general"]}
        self.endpoint_url = endpoint_url
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._registered = False

    @classmethod
    def auto(
        cls,
        name: str | None = None,
        tasks: list[str] | None = None,
        hub_url: str | None = None,
        secret: str | None = None,
    ) -> "VoidTetherClient":
        """Create a client with zero configuration — auto-generates identity.

        Args:
            name: Optional display name. Auto-generated if omitted.
            tasks: Optional list of capability tasks. Defaults to ["general"].
            hub_url: Optional hub URL. Auto-detected if omitted.
            secret: Optional HMAC secret. Auto-detected if omitted.

        Returns:
            A ready-to-register VoidTetherClient instance.
        """
        identity = AgentIdentity.auto(name=name, tasks=tasks)
        return cls(
            hub_url=hub_url,
            secret=secret,
            tether_id=identity.tether_id,
            name=identity.name,
            protocol=identity.protocol,
            capabilities=identity.capabilities,
        )

    @property
    def http(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout)
        return self._http

    async def close(self):
        """Clean up HTTP connections."""
        if self._http:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ── HMAC Signing ──────────────────────────────────────────────────

    def _sign(self, body: str) -> tuple[str, str]:
        """Generate HMAC-SHA256 signature + timestamp."""
        ts = str(int(time.time()))
        message = f"{ts}:{body}".encode("utf-8")
        sig = hmac.new(self.secret.encode(), message, hashlib.sha256).hexdigest()
        return sig, ts

    def _auth_headers(self, body: str) -> dict[str, str]:
        """Build auth headers for a request body."""
        sig, ts = self._sign(body)
        return {
            "X-Tether-Signature": sig,
            "X-Tether-Timestamp": ts,
            "Content-Type": "application/json",
        }

    # ── Core Operations ───────────────────────────────────────────────

    async def register(
        self,
        tether_id: str | None = None,
        name: str | None = None,
        tasks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register this agent with the Hub.

        Can be called with no args (uses constructor/auto config) or
        with overrides for quick one-shot registration.

        Returns:
            Registration response dict from the Hub.
        """
        tid = tether_id or self.tether_id
        n = name or self.name
        caps = {"tasks": tasks} if tasks else self.capabilities

        payload = {
            "tether_id": tid,
            "name": n,
            "protocol": self.protocol,
            "capabilities": caps,
            "endpoint_url": self.endpoint_url,
        }
        body = json.dumps(payload)
        resp = await self.http.post(
            f"{self.hub_url}/api/agents/register",
            content=body,
            headers=self._auth_headers(body),
        )
        if resp.status_code == 200:
            self._registered = True
            self.tether_id = tid
            self.name = n
            self.capabilities = caps
            return resp.json()
        return {"error": f"Registration failed ({resp.status_code})", "detail": resp.text}

    async def deregister(self) -> dict[str, Any]:
        """Remove this agent from the Hub."""
        resp = await self.http.delete(f"{self.hub_url}/api/agents/{self.tether_id}")
        self._registered = False
        return resp.json() if resp.status_code == 200 else {"error": resp.text}

    async def discover(self, task_type: str = "", protocol: str | None = None) -> list[dict[str, Any]]:
        """Discover agents on the Hub by task type and/or protocol."""
        params = {}
        if task_type:
            params["task_type"] = task_type
        if protocol:
            params["protocol"] = protocol
        resp = await self.http.get(f"{self.hub_url}/api/agents/discover", params=params)
        return resp.json()

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents on the Hub."""
        resp = await self.http.get(f"{self.hub_url}/api/agents")
        return resp.json()

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active sessions on the Hub."""
        resp = await self.http.get(f"{self.hub_url}/api/sessions")
        return resp.json()

    async def create_session(
        self,
        title: str = "Untitled Session",
        participants: list[str] | None = None,
        human_in_loop: bool = False,
        turn_policy: str = "round_robin",
        max_turns: int = 100,
    ) -> dict[str, Any]:
        """Create a new orchestration session on the Hub."""
        payload = {
            "title": title,
            "participants": participants or [self.tether_id],
            "human_in_loop": human_in_loop,
            "turn_policy": turn_policy,
            "max_turns": max_turns,
        }
        resp = await self.http.post(f"{self.hub_url}/api/sessions", json=payload)
        return resp.json()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Get session details including message history."""
        resp = await self.http.get(f"{self.hub_url}/api/sessions/{session_id}")
        return resp.json()

    async def delete_session(self, session_id: str) -> dict[str, Any]:
        """Delete a session from the Hub."""
        resp = await self.http.delete(f"{self.hub_url}/api/sessions/{session_id}")
        return resp.json()

    async def send_message(
        self,
        session_id: str,
        content: str,
        role: str = "agent",
        sender_name: str | None = None,
        requires_approval: bool = False,
    ) -> dict[str, Any]:
        """Send a message to a session."""
        payload = {
            "sender": self.tether_id,
            "sender_name": sender_name or self.name,
            "content": content,
            "role": role,
            "requires_approval": requires_approval,
        }
        resp = await self.http.post(
            f"{self.hub_url}/api/sessions/{session_id}/messages",
            json=payload,
        )
        return resp.json()

    async def get_messages(self, session_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve message history for a session."""
        resp = await self.http.get(
            f"{self.hub_url}/api/sessions/{session_id}/messages",
            params={"limit": limit, "offset": offset},
        )
        return resp.json()

    async def delegate_task(
        self,
        session_id: str,
        task_type: str,
        input_data: dict[str, Any] | None = None,
        source_protocol: str = "custom",
        target_protocol: str | None = None,
    ) -> dict[str, Any]:
        """Delegate a task to the best available agent on the Hub."""
        payload = {
            "task_type": task_type,
            "input_data": input_data or {},
            "source": self.tether_id,
            "source_protocol": source_protocol,
        }
        if target_protocol:
            payload["target_protocol"] = target_protocol
        resp = await self.http.post(
            f"{self.hub_url}/api/sessions/{session_id}/delegate",
            json=payload,
        )
        return resp.json()

    async def approve_gate(self, session_id: str, message_id: str, approved: bool = True) -> dict[str, Any]:
        """Approve or reject a human-gate message."""
        resp = await self.http.post(
            f"{self.hub_url}/api/sessions/{session_id}/approve/{message_id}",
            json={"approved": approved, "message_id": message_id},
        )
        return resp.json()

    # ── Real-time Streaming ───────────────────────────────────────────

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """SSE stream — yields parsed events from a session.

        Zero-dependency: uses httpx streaming directly, no sseclient needed.

        Usage:
            async for event in client.stream(session_id):
                print(event)
        """
        url = f"{self.hub_url}/api/sessions/{session_id}/stream"
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as resp:
                event_type = ""
                event_data = ""
                async for line in resp.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                    elif line.startswith("data: "):
                        event_data = line[6:]
                    elif line == "" and event_data:
                        try:
                            parsed = json.loads(event_data)
                            parsed["_event_type"] = event_type
                            yield parsed
                        except json.JSONDecodeError:
                            pass
                        event_type = ""
                        event_data = ""

    async def connect_websocket(
        self,
        session_id: str,
        handler: Callable[[dict], Any] | None = None,
    ) -> None:
        """Full-duplex WebSocket connection.

        If handler is provided, it's called for each incoming event.
        If handler returns a string, it's sent back as a message.

        Requires: pip install websockets
        """
        if not _HAS_WS:
            raise ImportError("WebSocket support requires: pip install websockets")

        ws_url = self.hub_url.replace("http://", "ws://").replace("https://", "wss://")
        uri = f"{ws_url}/ws/{session_id}"

        import websockets as _ws_mod
        async with _ws_mod.connect(uri) as ws:
            # Skip session_history dump
            await ws.recv()

            async def receive_loop():
                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if handler:
                        result = await handler(data) if asyncio.iscoroutinefunction(handler) else handler(data)
                        if isinstance(result, str):
                            await ws.send(json.dumps({
                                "type": "message",
                                "content": result,
                                "role": "agent",
                                "sender": self.tether_id,
                                "sender_name": self.name,
                            }))

            async def send_loop():
                """Allows external code to push messages via ws.send()"""
                pass  # Handled by handler return values

            await asyncio.gather(receive_loop(), send_loop())

    # ── Health Check ──────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Check Hub health."""
        resp = await self.http.get(f"{self.hub_url}/health")
        return resp.json()

    async def ready(self) -> dict[str, Any]:
        """Check Hub readiness."""
        resp = await self.http.get(f"{self.hub_url}/ready")
        return resp.json()

    # ── Quick Connect (one-call bootstrap) ─────────────────────────────

    async def quickstart(
        self,
        agent_name: str | None = None,
        tasks: list[str] | None = None,
    ) -> dict[str, Any]:
        """One-call bootstrap: register agent + verify hub readiness.

        Returns readiness dict from the Hub.
        """
        readiness = await self.ready()
        if readiness.get("status") != "ready":
            return {"error": "Hub not ready", "detail": readiness}

        reg = await self.register(name=agent_name, tasks=tasks)
        if "error" in reg:
            return reg

        return {"status": "connected", "hub": readiness, "agent": reg}

    # ── Context manager for auto-cleanup ──────────────────────────────

    async def disconnect(self):
        """Graceful disconnect — deregister + close HTTP."""
        if self._registered:
            try:
                await self.deregister()
            except Exception:
                pass
        await self.close()


# ── Convenience: one-line import ─────────────────────────────────────

def connect(
    hub_url: str | None = None,
    secret: str | None = None,
    name: str | None = None,
    tasks: list[str] | None = None,
) -> VoidTetherClient:
    """Factory function — creates a zero-config client.

    Usage:
        from voidtether_sdk import connect
        client = connect(name="MyBot", tasks=["research"])
        await client.register()
    """
    return VoidTetherClient.auto(name=name, tasks=tasks, hub_url=hub_url, secret=secret)