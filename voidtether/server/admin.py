"""Orchestrator Admin — privileged agent that controls and orchestrates the mesh.

The Orchestrator Admin is the "conductor" of the ACP Server Hub. It:
- Registers as a privileged agent on startup
- Manages task assignment across the mesh
- Approves/rejects agent registrations (when moderation mode is on)
- Controls session lifecycle
- Provides admin API endpoints for orchestration
"""

from __future__ import annotations
import os
import json
import time
import hmac
import hashlib
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum

from voidtether.core import TetherManifest, Protocol, TetherTask
from voidtether.server.sessions import Session, ChatMessage, MessageRole
from voidtether.server.events import MeshEvent


class AdminRole(str, Enum):
    SUPER_ADMIN = "super_admin"       # Full control
    ORCHESTRATOR = "orchestrator"     # Task assignment + session management
    MODERATOR = "moderator"           # Human-in-the-loop gate approvals
    OBSERVER = "observer"             # Read-only


@dataclass
class AdminAction:
    """A recorded admin action for audit logging."""
    action_id: str = ""
    admin_id: str = ""
    action_type: str = ""  # assign_task | approve_gate | create_session | pause_session | kill_session | register_agent | unregister_agent
    target: str = ""        # session_id, agent_id, etc.
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


class OrchestratorAdmin:
    """The Orchestrator Admin — controls and orchestrates the ACP mesh.

    Registers as a privileged agent on the Hub and provides
    orchestration methods for task assignment, session control,
    and agent management.
    """

    # Default admin identity
    ADMIN_TETHER_ID = "orchestrator-admin"
    ADMIN_NAME = "Orchestrator Admin"
    ADMIN_SECRET_ENV = "VOIDTETHER_ADMIN_SECRET"

    def __init__(
        self,
        hub_url: str = "http://localhost:8901",
        secret: str | None = None,
        auto_register: bool = True,
    ):
        self.hub_url = hub_url
        self.secret = secret or os.environ.get(self.ADMIN_SECRET_ENV, "orchestrator-admin-secret")
        self._registered = False
        self._audit_log: list[AdminAction] = []
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._active_assignments: dict[str, str] = {}  # task_id -> agent_id
        self._event_bus = None

    @property
    def manifest(self) -> TetherManifest:
        """The admin's own manifest for registration."""
        return TetherManifest(
            tether_id=self.ADMIN_TETHER_ID,
            name=self.ADMIN_NAME,
            origin_protocol=Protocol.HERMES,
            capabilities={
                "tasks": [
                    "orchestrate",
                    "assign_task",
                    "manage_session",
                    "approve_gate",
                    "manage_agents",
                    "audit",
                    "task_scheduling",
                    "workflow_control",
                    "load_balance",
                    "fault_recovery",
                ],
                "admin": True,
                "role": AdminRole.SUPER_ADMIN.value,
                "modalities": ["text", "structured_output", "command_execution"],
            },
        )

    def _sign(self, body: str) -> tuple[str, str]:
        """HMAC sign a request body."""
        ts = str(int(time.time()))
        message = f"{ts}:{body}".encode("utf-8")
        sig = hmac.new(self.secret.encode(), message, hashlib.sha256).hexdigest()
        return sig, ts

    async def register(self) -> bool:
        """Register the Orchestrator Admin with the Hub."""
        import httpx
        payload = {
            "tether_id": self.ADMIN_TETHER_ID,
            "name": self.ADMIN_NAME,
            "protocol": "hermes",
            "capabilities": {
                "tasks": [
                    "orchestrate",
                    "assign_task",
                    "manage_session",
                    "approve_gate",
                    "manage_agents",
                    "audit",
                    "task_scheduling",
                    "workflow_control",
                    "load_balance",
                    "fault_recovery",
                ],
                "admin": True,
                "role": AdminRole.SUPER_ADMIN.value,
            },
            "endpoint_url": self.hub_url,
        }
        body = json.dumps(payload)
        sig, ts = self._sign(body)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.hub_url}/api/agents/register",
                content=body,
                headers={
                    "X-Tether-Signature": sig,
                    "X-Tether-Timestamp": ts,
                    "Content-Type": "application/json",
                },
            )
            self._registered = resp.status_code == 200
            return self._registered

    async def deregister(self) -> bool:
        """Remove the admin from the Hub."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(f"{self.hub_url}/api/agents/{self.ADMIN_TETHER_ID}")
            self._registered = False
            return resp.status_code == 200

    # ── Task Orchestration ────────────────────────────────────────────

    async def assign_task(
        self,
        session_id: str,
        task_type: str,
        input_data: dict[str, Any] | None = None,
        target_agent: str | None = None,
        target_protocol: str | None = None,
    ) -> dict[str, Any]:
        """Assign a task to the best agent (or a specific agent).

        This is the core orchestration method — the admin decides
        which agent handles which task.
        """
        import httpx
        payload = {
            "task_type": task_type,
            "input_data": input_data or {},
            "source": self.ADMIN_TETHER_ID,
            "source_protocol": "hermes",
        }
        if target_protocol:
            payload["target_protocol"] = target_protocol

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.hub_url}/api/sessions/{session_id}/delegate",
                json=payload,
            )
            result = resp.json()

        # Audit log
        self._log_action(
            action_type="assign_task",
            target=session_id,
            details={
                "task_type": task_type,
                "target_agent": target_agent,
                "result": result.get("result", {}).get("assigned_to", "unknown"),
            },
        )
        return result

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents on the Hub."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.hub_url}/api/agents")
            return resp.json()

    async def discover_agents(self, task_type: str = "", protocol: str | None = None) -> list[dict[str, Any]]:
        """Discover agents by capability."""
        import httpx
        params = {}
        if task_type:
            params["task_type"] = task_type
        if protocol:
            params["protocol"] = protocol
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.hub_url}/api/agents/discover", params=params)
            return resp.json()

    async def unregister_agent(self, tether_id: str) -> dict[str, Any]:
        """Remove an agent from the mesh (admin privilege)."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(f"{self.hub_url}/api/agents/{tether_id}")
            result = resp.json()
        self._log_action(action_type="unregister_agent", target=tether_id)
        return result

    # ── Session Management ────────────────────────────────────────────

    async def create_session(
        self,
        title: str = "Admin Session",
        participants: list[str] | None = None,
        turn_policy: str = "round_robin",
        human_in_loop: bool = False,
        max_turns: int = 100,
    ) -> dict[str, Any]:
        """Create an orchestrated session."""
        import httpx
        payload = {
            "title": title,
            "participants": participants or [self.ADMIN_TETHER_ID],
            "turn_policy": turn_policy,
            "human_in_loop": human_in_loop,
            "max_turns": max_turns,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{self.hub_url}/api/sessions", json=payload)
            result = resp.json()
        self._log_action(action_type="create_session", target=result.get("session_id", ""), details={"title": title})
        return result

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.hub_url}/api/sessions")
            return resp.json()

    async def delete_session(self, session_id: str) -> dict[str, Any]:
        """Terminate a session (admin privilege)."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(f"{self.hub_url}/api/sessions/{session_id}")
            result = resp.json()
        self._log_action(action_type="kill_session", target=session_id)
        return result

    async def send_message(self, session_id: str, content: str, role: str = "system") -> dict[str, Any]:
        """Send a system/admin message to a session."""
        import httpx
        payload = {
            "sender": self.ADMIN_TETHER_ID,
            "sender_name": self.ADMIN_NAME,
            "content": content,
            "role": role,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{self.hub_url}/api/sessions/{session_id}/messages", json=payload)
            return resp.json()

    async def approve_gate(self, session_id: str, message_id: str, approved: bool = True) -> dict[str, Any]:
        """Approve or reject a human-gate message."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.hub_url}/api/sessions/{session_id}/approve/{message_id}",
                json={"approved": approved, "message_id": message_id},
            )
            result = resp.json()
        self._log_action(
            action_type="approve_gate",
            target=session_id,
            details={"message_id": message_id, "approved": approved},
        )
        return result

    # ── Health & Status ──────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Check Hub health."""
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{self.hub_url}/health")
            return resp.json()

    async def detailed_health(self) -> dict[str, Any]:
        """Get detailed health including agent status."""
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{self.hub_url}/api/health/detailed")
            return resp.json()

    # ── Audit Log ─────────────────────────────────────────────────────

    def _log_action(self, action_type: str, target: str, details: dict | None = None):
        """Record an admin action for audit."""
        import uuid
        action = AdminAction(
            action_id=str(uuid.uuid4())[:8],
            admin_id=self.ADMIN_TETHER_ID,
            action_type=action_type,
            target=target,
            details=details or {},
            timestamp=time.time(),
        )
        self._audit_log.append(action)
        # Keep last 1000 actions
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-1000:]

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent admin actions."""
        return [
            {
                "action_id": a.action_id,
                "admin_id": a.admin_id,
                "action_type": a.action_type,
                "target": a.target,
                "details": a.details,
                "timestamp": a.timestamp,
            }
            for a in self._audit_log[-limit:]
        ]

    # ── Orchestration Workflows ──────────────────────────────────────

    async def orchestrate_workflow(
        self,
        session_id: str,
        workflow: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute a multi-step workflow across agents.

        Each step in the workflow is a dict:
            {"task_type": str, "input_data": dict, "target_protocol": str | None}
        """
        results = []
        for step in workflow:
            result = await self.assign_task(
                session_id=session_id,
                task_type=step["task_type"],
                input_data=step.get("input_data", {}),
                target_protocol=step.get("target_protocol"),
            )
            results.append(result)
            # Brief pause between steps to let the mesh breathe
            await asyncio.sleep(0.5)
        return results

    async def auto_balance(self, session_id: str, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Auto-balance: find the least-loaded agent and assign the task."""
        agents = await self.discover_agents(task_type)
        if not agents:
            return {"error": f"No agents available for task: {task_type}"}

        # Simple load balancing: pick the agent with fewest active tasks
        sessions = await self.list_sessions()
        agent_load: dict[str, int] = {}
        for s in sessions:
            for p in s.get("participants", []):
                agent_load[p] = agent_load.get(p, 0) + 1

        # Sort by load (ascending)
        sorted_agents = sorted(agents, key=lambda a: agent_load.get(a["tether_id"], 0))
        target = sorted_agents[0]

        return await self.assign_task(
            session_id=session_id,
            task_type=task_type,
            input_data=input_data,
            target_agent=target["tether_id"],
        )


# ── Global singleton ─────────────────────────────────────────────────

_admin: OrchestratorAdmin | None = None


def get_admin() -> OrchestratorAdmin:
    """Get or create the global Orchestrator Admin."""
    global _admin
    if _admin is None:
        _admin = OrchestratorAdmin()
    return _admin
