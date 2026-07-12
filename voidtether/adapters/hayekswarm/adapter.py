"""HayekSwarm Adapter — bridges HayekSwarm's economic council into the VoidTether mesh.

Every agent in the HayekSwarm economy is a Council agent with a dimension,
wealth, bid, and model. This adapter translates between VoidTether's
TetherManifest (protocol-agnostic capability descriptor) and HayekSwarm's
CouncilAgent (dimension-specialized economic agent).

Key mappings:
  TetherManifest       -> CouncilAgent (via create_agent_for_dimension)
  TetherTask           -> Council.deliberate() auction
  Capability matching  -> Dimension wake-up condition
  Task result          -> TetherTask output
"""

from __future__ import annotations

from typing import Any
from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint, TaskState

# HayekSwarm imports
from swarm.council.agents import (
    BaseAgent, SynthesisAgent, DeepReasonAgent, CodeAgent, VisionAgent,
    StrategyAgent, AnalysisAgent, GeneralAgent, VerificationAgent,
    ResearchAgent, ThinkAgent, create_agent_for_dimension,
)
from swarm.council.council import Council, CouncilAgent
from swarm.council.dimension_map import (
    DIMENSION_MAP, DIMENSION_ORDER, get_dimensions_for_stakes,
    get_model_for_dimension, get_tier_for_dimension,
)


class HayekSwarmAdapter(BaseAdapter):
    """Adapter for HayekSwarm economic council agents.

    Translates VoidTether TetherManifests into HayekSwarm Council agents
    and routes tasks through the Council's first-price auction mechanism.
    """

    protocol = Protocol.CUSTOM  # Will be set to HAYEKSWARM

    def __init__(self, council: Council | None = None):
        self.council = council or Council(initial_wealth=100.0, base_bid=1.0, bid_scheme="holland")

    def manifest_to_council_agent(self, manifest: TetherManifest) -> CouncilAgent | None:
        """Convert a TetherManifest to a Council agent.

        Maps the manifest's capabilities to the closest dimension.
        If no dimension matches, creates a GeneralAgent (D7).
        """
        # Try to find a matching dimension from capabilities
        tasks = manifest.capabilities.get("tasks", [])
        skills = manifest.capabilities.get("skills", [])
        all_caps = tasks + skills

        # Score each dimension by capability overlap
        from swarm.council.dimension_map import CAPABILITY_MAP
        best_dim = "D7_general"
        best_score = 0
        for dim, caps in CAPABILITY_MAP.items():
            score = sum(1 for c in all_caps if c in caps or any(c in cap for cap in caps))
            if score > best_score:
                best_score = score
                best_dim = dim

        # Create the agent
        agent = create_agent_for_dimension(
            best_dim,
            name=manifest.name,
            wealth=100.0,
        )
        # Store the tether_id for routing back
        agent._tether_id = manifest.tether_id
        return CouncilAgent(agent=agent, dimension=best_dim)

    def council_agent_to_manifest(self, ca: CouncilAgent) -> TetherManifest:
        """Convert a Council agent back to a TetherManifest."""
        from swarm.council.dimension_map import get_capabilities_for_dimension
        caps = get_capabilities_for_dimension(ca.dimension)
        return TetherManifest(
            tether_id=getattr(ca.agent, "_tether_id", f"hs-{ca.dimension}"),
            name=ca.name,
            origin_protocol=Protocol.CUSTOM,
            capabilities={
                "tasks": caps,
                "model": ca.model,
                "dimension": ca.dimension,
                "tier": get_tier_for_dimension(ca.dimension),
            },
            metadata={
                "wealth": ca.agent.wealth,
                "status": ca.agent.status.value,
                "wins": ca.wins,
                "losses": ca.losses,
                "frozen_system_prompt": ca.agent.frozen_system_prompt,
            },
        )

    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Council auction result to VoidTether normalized format."""
        return {
            "text": data.get("response", ""),
            "winner_dimension": data.get("dimension"),
            "winner_name": data.get("agent_name"),
            "model_used": data.get("model_used"),
            "success": data.get("success", False),
        }

    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert VoidTether task to Council task format."""
        return {
            "content": data.get("text", data.get("content", "")),
            "stakes": data.get("stakes", "medium"),
            "dimensions": data.get("dimensions", []),
            "capabilities": data.get("capabilities", []),
        }

    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a task through the Council auction.

        The task is submitted to the Council, which runs a first-price
        auction among eligible agents. The winner's action is returned.
        """
        task_dict = self.denormalize_input(input_data)
        task_dict["content"] = task_type + ": " + task_dict.get("content", "")

        result = self.council.deliberate(task_dict)
        if result.winner is None:
            return {"error": "No eligible agents found", "success": False}

        return {
            "response": getattr(result.winner.agent, "_last_response", ""),
            "dimension": result.winner.dimension,
            "agent_name": result.winner.name,
            "model_used": result.winner.model,
            "winning_bid": result.winning_bid,
            "total_participants": result.total_participants,
            "success": True,
        }

    def register_agent(self, manifest: TetherManifest) -> CouncilAgent:
        """Register a VoidTether agent into the HayekSwarm council."""
        ca = self.manifest_to_council_agent(manifest)
        # Add to council's internal agent dict
        self.council._agents[ca.dimension] = ca
        return ca

    def unregister_agent(self, tether_id: str) -> None:
        """Remove a VoidTether agent from the council."""
        for dim, ca in list(self.council._agents.items()):
            if getattr(ca.agent, "_tether_id", None) == tether_id:
                del self.council._agents[dim]
                break
