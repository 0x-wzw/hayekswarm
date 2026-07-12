"""HayekSwarm ↔ VoidTether Bridge — connects the marketplace to the mesh.

This module provides the integration layer between HayekSwarm's marketplace
API and VoidTether's protocol mesh. It allows:

1. VoidTether agents to register in the HayekSwarm economy
2. HayekSwarm tasks to be routed through VoidTether's protocol adapters
3. Cross-protocol agent participation in HayekSwarm auctions
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint
from voidtether.core.router import TetherRouter, TetherTask, TaskState
from voidtether.core.bridge import ProtocolBridge

from swarm.council.council import Council, CouncilAgent
from swarm.council.agents import create_agent_for_dimension
from swarm.council.dimension_map import (
    CAPABILITY_MAP, get_tier_for_dimension,
)

logger = logging.getLogger(__name__)


class VoidTetherBridge:
    """Bridges the HayekSwarm marketplace with the VoidTether mesh.

    Manages the lifecycle of VoidTether agents within the HayekSwarm
    economy: registration, capability mapping, task routing, and
    result delivery.

    Usage:
        bridge = VoidTetherBridge(council, router)
        bridge.register_mesh_agent(manifest)
        result = bridge.route_mesh_task(task)
    """

    def __init__(
        self,
        council: Council,
        tether_router: TetherRouter,
        protocol_bridge: Optional[ProtocolBridge] = None,
    ):
        self.council = council
        self.tether_router = tether_router
        self.protocol_bridge = protocol_bridge

        # Track mesh agents registered in the council
        # tether_id -> dimension
        self._mesh_agents: dict[str, str] = {}

    # ── Agent registration ─────────────────────────────────────────────

    def register_mesh_agent(self, manifest: TetherManifest) -> str:
        """Register a VoidTether mesh agent into the HayekSwarm council.

        Maps the agent's capabilities to the closest council dimension
        and creates a council agent entry.

        Args:
            manifest: The TetherManifest from the mesh.

        Returns:
            The assigned dimension key.
        """
        # Find best dimension match from capabilities
        tasks = manifest.capabilities.get("tasks", [])
        skills = manifest.capabilities.get("skills", [])
        all_caps = tasks + skills

        best_dim = "D7_general"
        best_score = 0
        for dim, caps in CAPABILITY_MAP.items():
            score = sum(1 for c in all_caps if c in caps or any(c in cap for cap in caps))
            if score > best_score:
                best_score = score
                best_dim = dim

        # Create council agent
        agent = create_agent_for_dimension(
            best_dim,
            name=manifest.name,
            wealth=100.0,
        )
        agent._tether_id = manifest.tether_id
        agent._mesh_protocol = manifest.origin_protocol.value

        # Register in council
        ca = CouncilAgent(agent=agent, dimension=best_dim)
        self.council._agents[best_dim] = ca

        # Register in tether router
        self.tether_router.register(manifest)

        # Track
        self._mesh_agents[manifest.tether_id] = best_dim

        logger.info(
            "Mesh agent %s (%s) registered -> dimension %s",
            manifest.name, manifest.origin_protocol.value, best_dim,
        )
        return best_dim

    def unregister_mesh_agent(self, tether_id: str) -> None:
        """Remove a mesh agent from the council and router."""
        dim = self._mesh_agents.pop(tether_id, None)
        if dim and dim in self.council._agents:
            del self.council._agents[dim]
        self.tether_router.unregister(tether_id)
        logger.info("Mesh agent %s unregistered (dim=%s)", tether_id, dim)

    # ── Task routing ──────────────────────────────────────────────────

    async def route_mesh_task(
        self,
        task_type: str,
        input_data: dict[str, Any],
        source_protocol: Protocol = Protocol.HAYEKSWARM,
        stakes: str = "medium",
    ) -> dict[str, Any]:
        """Route a task through the HayekSwarm council auction.

        If the winning agent is a mesh agent (from another protocol),
        the task is delegated through the VoidTether protocol bridge
        for cross-protocol execution.

        Args:
            task_type: The type of task.
            input_data: Task input data.
            source_protocol: The source protocol.
            stakes: Task stakes level.

        Returns:
            Task result dict with response, winner info, and cost.
        """
        # Build task for council
        task_dict = {
            "content": input_data.get("text", input_data.get("content", task_type)),
            "stakes": stakes,
            "dimensions": [],
            "capabilities": [],
        }

        # Run council auction
        result = self.council.deliberate(task_dict)
        if result.winner is None:
            return {"error": "No eligible agents found", "success": False}

        # Check if winner is a mesh agent (cross-protocol)
        winner_tether = getattr(result.winner.agent, "_tether_id", None)
        winner_protocol = getattr(result.winner.agent, "_mesh_protocol", None)

        if winner_tether and winner_protocol and winner_protocol != "hayekswarm":
            # Route through VoidTether protocol bridge
            if self.protocol_bridge:
                target_manifest = self.tether_router.get(winner_tether)
                if target_manifest:
                    tether_task = TetherTask(
                        task_id=f"hs-{self.council._auction_history[-1].__hash__() if self.council._auction_history else 0}",
                        task_type=task_type,
                        input_data=input_data,
                        source_agent="hayekswarm-marketplace",
                        source_protocol=Protocol.HAYEKSWARM,
                        target_protocol=Protocol(winner_protocol),
                    )
                    bridge_result = await self.protocol_bridge.delegate_with_manifest(
                        tether_task, target_manifest
                    )
                    return {
                        "response": bridge_result.get("response", bridge_result.get("text", "")),
                        "winner_dimension": result.winner.dimension,
                        "winner_name": result.winner.name,
                        "winner_protocol": winner_protocol,
                        "winning_bid": result.winning_bid,
                        "success": True,
                    }

        # Native HayekSwarm agent — return council result directly
        return {
            "response": getattr(result.winner.agent, "_last_response", ""),
            "winner_dimension": result.winner.dimension,
            "winner_name": result.winner.name,
            "winner_protocol": "hayekswarm",
            "winning_bid": result.winning_bid,
            "total_participants": result.total_participants,
            "success": True,
        }

    # ── Agent discovery ────────────────────────────────────────────────

    def discover_mesh_agents(self) -> list[dict[str, Any]]:
        """List all mesh agents registered in the economy."""
        agents = []
        for tid, dim in self._mesh_agents.items():
            ca = self.council.get_agent_by_dimension(dim)
            if ca:
                agents.append({
                    "tether_id": tid,
                    "name": ca.name,
                    "dimension": dim,
                    "model": ca.model,
                    "wealth": ca.agent.wealth,
                    "status": ca.agent.status.value,
                    "wins": ca.wins,
                    "losses": ca.losses,
                    "protocol": getattr(ca.agent, "_mesh_protocol", "hayekswarm"),
                })
        return agents

    def get_mesh_agent_count(self) -> int:
        """Get the number of mesh agents registered."""
        return len(self._mesh_agents)

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics."""
        return {
            "mesh_agents_registered": len(self._mesh_agents),
            "council_agents": len(self.council.get_all_agents()),
            "council_active": self.council.active_count(),
            "total_auctions": len(self.council._auction_history),
        }
