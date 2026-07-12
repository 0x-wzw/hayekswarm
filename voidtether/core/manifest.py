"""TetherManifest — the polyglot capability description that binds the mesh."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import json


class Protocol(str, Enum):
    """Supported agent protocols."""
    A2A = "a2a"
    MCP = "mcp"
    HERMES = "hermes"
    SWARM = "swarm"
    OPENCLAW = "openclaw"
    CREWAI = "crewai"
    LANGGRAPH = "langgraph"
    GBRAIN = "gbrain"
    ACP = "acp"           # v0.4.0: Agent Client Protocol (stdio-based)
    K2 = "k2"             # v0.5.0: K2 Swarm Protocol (subprocess-based)
    TASTE = "taste"       # v0.5.0: Taste-Skill (anti-slop design)
    HAYEKSWARM = "hayekswarm"  # v1.0.0: HayekSwarm economic council
    CUSTOM = "custom"


class TaskState(str, Enum):
    """Tether task lifecycle states."""
    SUBMITTED = "submitted"
    NEGOTIATING = "negotiating"
    ACCEPTED = "accepted"
    RUNNING = "running"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class ProtocolEndpoint:
    """How to reach an agent under a specific protocol."""
    protocol: Protocol
    config: dict[str, Any] = field(default_factory=dict)
    # Protocol-specific fields
    agent_card_url: str | None = None       # A2A
    tools: list[str] = field(default_factory=list)  # MCP
    skill: str | None = None                # Hermes / OpenClaw
    agent_fn: str | None = None             # Swarm
    role: str | None = None                 # CrewAI
    node_id: str | None = None              # LangGraph
    endpoint_url: str | None = None         # Generic HTTP
    acp_command: str | None = None          # ACP: CLI command to spawn agent
    acp_transport: str = "stdio"            # ACP: transport type


@dataclass
class TetherManifest:
    """The universal agent capability description.
    
    Every agent in the VoidTether mesh is described by a TetherManifest.
    This is the lingua franca — any protocol can produce one, and the
    mesh router uses them to match tasks to agents.
    """
    tether_id: str
    name: str
    origin_protocol: Protocol
    capabilities: dict[str, Any] = field(default_factory=dict)
    protocols: list[ProtocolEndpoint] = field(default_factory=list)
    authentication: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Convenience: task list from capabilities
    @property
    def tasks(self) -> list[str]:
        return self.capabilities.get("tasks", [])
    
    @property 
    def modalities(self) -> list[str]:
        return self.capabilities.get("modalities", ["text"])
    
    def supports_task(self, task: str) -> bool:
        """Check if this agent can handle a given task type."""
        return task in self.tasks or task in self.capabilities.get("skills", [])
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "tether_id": self.tether_id,
            "name": self.name,
            "origin_protocol": self.origin_protocol.value,
            "capabilities": self.capabilities,
            "protocols": [
                {
                    "protocol": p.protocol.value,
                    "config": p.config,
                    "agent_card_url": p.agent_card_url,
                    "tools": p.tools,
                    "skill": p.skill,
                    "agent_fn": p.agent_fn,
                    "role": p.role,
                    "node_id": p.node_id,
                    "endpoint_url": p.endpoint_url,
                    "acp_command": p.acp_command,
                    "acp_transport": p.acp_transport,
                }
                for p in self.protocols
            ],
            "authentication": self.authentication,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TetherManifest:
        protocols = []
        for p in data.get("protocols", []):
            protocols.append(ProtocolEndpoint(
                protocol=Protocol(p["protocol"]),
                config=p.get("config", {}),
                agent_card_url=p.get("agent_card_url"),
                tools=p.get("tools", []),
                skill=p.get("skill"),
                agent_fn=p.get("agent_fn"),
                role=p.get("role"),
                node_id=p.get("node_id"),
                endpoint_url=p.get("endpoint_url"),
                acp_command=p.get("acp_command"),
                acp_transport=p.get("acp_transport", "stdio"),
            ))
        return cls(
            tether_id=data["tether_id"],
            name=data["name"],
            origin_protocol=Protocol(data["origin_protocol"]),
            capabilities=data.get("capabilities", {}),
            protocols=protocols,
            authentication=data.get("authentication", {}),
            metadata=data.get("metadata", {}),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> TetherManifest:
        return cls.from_dict(json.loads(json_str))
