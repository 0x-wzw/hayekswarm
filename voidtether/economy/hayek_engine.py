"""HayekEngine — Full HayekSwarm economic engine for the VoidTether mesh.

Replaces VoidTether's thin EconomicEngine with HayekSwarm's complete
HayekMAS engine: auctions, bucket-brigade payments, population evolution,
pricing oracle, 10-D council, and consensus voting.

This is the bridge between VoidTether's protocol-agnostic mesh and
HayekSwarm's economic coordination layer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from voidtether.core.manifest import TetherManifest
from voidtether.core.router import TetherRouter, TetherTask

# HayekSwarm imports
from hayekmas.base.config import HayekConfig, EngineConfig, RewardConfig, EvolutionConfig
from hayekmas.base.mas import HayekMAS
from hayekmas.base.population import Population
from swarm.council.council import Council, CouncilAgent
from swarm.council.agents import create_agent_for_dimension
from swarm.council.dimension_map import (
    DIMENSION_MAP, DIMENSION_ORDER, get_dimensions_for_stakes,
    get_model_for_dimension, get_tier_for_dimension,
)
from swarm.cost_router import PricingOracle, TaskProfile, TaskComplexity
from swarm.consensus import ConsensusEngine

logger = logging.getLogger(__name__)


class HayekEngine:
    """Full HayekSwarm economic engine for the VoidTether mesh.

    Integrates:
    - HayekMAS: auction loop, bucket-brigade payments, population evolution
    - 10-D Council: dimension-specialized agents with model assignments
    - PricingOracle: 33 models, 4 tiers, cost-per-token bid estimation
    - ConsensusEngine: weighted majority, Borda, Delphi for tie-breaking

    Usage:
        engine = HayekEngine()
        engine.register_agent(manifest)
        winner_id, payment = engine.run_auction(task_type, candidates)
        engine.apply_reward(winner_id, reward)
        engine.check_bankruptcies()
    """

    def __init__(
        self,
        initial_wealth: float = 100.0,
        base_bid: float = 1.0,
        bid_scheme: str = "holland",
        max_agents: int = 20,
    ):
        # HayekMAS configuration
        self.hayek_config = HayekConfig()
        self.hayek_config.engine.initial_wealth = initial_wealth
        self.hayek_config.engine.base_bid = base_bid
        self.hayek_config.engine.bid_scheme = bid_scheme
        self.hayek_config.engine.max_num_agents = max_agents
        self.hayek_config.evolution.p_a = 0.3
        self.hayek_config.evolution.p_b = 0.7

        # Core engines
        self.mas = HayekMAS(config=self.hayek_config)
        self.council = Council(
            initial_wealth=initial_wealth,
            base_bid=base_bid,
            bid_scheme=bid_scheme,
        )
        self.pricing_oracle = PricingOracle()
        self.consensus = ConsensusEngine()

        # Track tether_id -> dimension mapping
        self._tether_to_dim: dict[str, str] = {}

        # Track auction history for bucket-brigade payments
        self._last_winner_tether: Optional[str] = None
        self._last_winner_dim: Optional[str] = None
        self._last_payment: float = 0.0

        # Stats
        self.episode_count = 0
        self.total_rewards = 0.0
        self.bankruptcy_count = 0

    # ── Agent registration ─────────────────────────────────────────────

    def register_agent(self, manifest: TetherManifest) -> str:
        """Register a VoidTether agent into the HayekSwarm economy.

        Maps the manifest's capabilities to the closest council dimension
        and creates an agent with initial wealth.

        Args:
            manifest: The TetherManifest describing the agent.

        Returns:
            The assigned dimension key (e.g. "D7_general").
        """
        # Find best dimension match
        tasks = manifest.capabilities.get("tasks", [])
        skills = manifest.capabilities.get("skills", [])
        all_caps = tasks + skills

        from swarm.council.dimension_map import CAPABILITY_MAP
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
            wealth=self.hayek_config.engine.initial_wealth,
        )
        agent._tether_id = manifest.tether_id

        # Register in council
        ca = CouncilAgent(agent=agent, dimension=best_dim)
        self.council._agents[best_dim] = ca

        # Track mapping
        self._tether_to_dim[manifest.tether_id] = best_dim

        logger.info("Registered agent %s -> dimension %s", manifest.name, best_dim)
        return best_dim

    def unregister_agent(self, tether_id: str) -> None:
        """Remove an agent from the economy."""
        dim = self._tether_to_dim.pop(tether_id, None)
        if dim and dim in self.council._agents:
            del self.council._agents[dim]
            logger.info("Unregistered agent %s (dim=%s)", tether_id, dim)

    # ── Auction lifecycle ──────────────────────────────────────────────

    def run_auction(
        self,
        task_type: str,
        candidates: list[TetherManifest],
        stakes: str = "medium",
    ) -> tuple[Optional[str], float]:
        """Run a first-price auction among candidate agents.

        1. Filter candidates to those registered in the economy.
        2. Build task dict with stakes and capabilities.
        3. Run Council auction.
        4. Process bucket-brigade payment.
        5. Return (winning_tether_id, payment_amount).

        Args:
            task_type: The type of task (e.g. "research", "code").
            candidates: List of TetherManifests of candidate agents.
            stakes: Task stakes level (low/medium/high/critical).

        Returns:
            Tuple of (winning_tether_id, payment_amount).
            winning_tether_id is None if no eligible agents.
        """
        # Filter to registered agents
        registered = [m for m in candidates if m.tether_id in self._tether_to_dim]
        if not registered:
            return None, 0.0

        # Build task dict
        task_dict = {
            "content": task_type,
            "stakes": stakes,
            "dimensions": [self._tether_to_dim[m.tether_id] for m in registered],
            "capabilities": [],
        }

        # Run council auction
        result = self.council.deliberate(task_dict)
        if result.winner is None:
            return None, 0.0

        # Find the winning tether_id
        winner_tether = None
        for tid, dim in self._tether_to_dim.items():
            if dim == result.winner.dimension:
                winner_tether = tid
                break

        # Bucket-brigade payment. NOTE: council.deliberate() has ALREADY debited
        # the winner's winning_bid (Council.deliberate -> agent.apply_payment), so
        # we must NOT debit again here — doing so charged the winner twice. We only
        # credit the previous winner; the first winner's bid stays debited (it goes
        # to the "void" / treasury).
        if self._last_winner_dim:
            prev_ca = self.council.get_agent_by_dimension(self._last_winner_dim)
            if prev_ca:
                prev_ca.agent.apply_reward(result.winning_bid)

        # Track for next bucket-brigade
        self._last_winner_tether = winner_tether
        self._last_winner_dim = result.winner.dimension
        self._last_payment = result.winning_bid

        self.episode_count += 1
        return winner_tether, result.winning_bid

    # ── Reward application ────────────────────────────────────────────

    def apply_reward(self, tether_id: str, reward: float) -> None:
        """Apply reward to an agent after task completion.

        The reward is added to the agent's wealth. If the agent was the
        last auction winner, the reward is also shared with the bucket-brigade
        chain (previous winners who contributed to the task).

        Args:
            tether_id: The agent that completed the task.
            reward: The reward amount.
        """
        dim = self._tether_to_dim.get(tether_id)
        if dim:
            self.council.apply_reward(dim, reward)
            self.total_rewards += reward

    # ── Bankruptcy handling ────────────────────────────────────────────

    def check_bankruptcies(self) -> list[str]:
        """Check for and remove bankrupt agents.

        An agent is bankrupt when wealth < 0.
        Bankrupt agents are removed and replaced via good/bad births.

        Returns:
            List of tether_ids of removed bankrupt agents.
        """
        bankrupt = self.council.get_bankrupt_agents()
        removed = []
        for ca in bankrupt:
            tid = getattr(ca.agent, "_tether_id", None)
            if tid:
                removed.append(tid)
                self._tether_to_dim.pop(tid, None)
            self.bankruptcy_count += 1

        # Spawn replacements
        if bankrupt:
            self.council.good_birth()
            self.council.bad_birth()

        return removed

    # ── Pricing oracle ─────────────────────────────────────────────────

    def estimate_bid(self, task_description: str, estimated_tokens: int = 1000) -> float:
        """Estimate a bid price for a task using the pricing oracle.

        Args:
            task_description: Description of the task.
            estimated_tokens: Estimated token count.

        Returns:
            Suggested bid price.
        """
        profile = TaskProfile(
            task_id=f"estimate-{self.episode_count}",
            description=task_description,
            estimated_tokens=estimated_tokens,
            requires_reasoning="reason" in task_description.lower(),
            requires_code="code" in task_description.lower() or "implement" in task_description.lower(),
            requires_creativity=False,
        )
        decision = self.pricing_oracle.route(profile)
        return decision.suggested_bid

    # ── Wealth queries ────────────────────────────────────────────────

    def get_agent_wealth(self, tether_id: str) -> float:
        """Get current wealth of an agent."""
        dim = self._tether_to_dim.get(tether_id)
        if dim:
            ca = self.council.get_agent_by_dimension(dim)
            if ca:
                return ca.agent.wealth
        return 0.0

    def get_wealth_distribution(self) -> dict[str, float]:
        """Get wealth of all agents mapped by tether_id."""
        dist = {}
        for tid, dim in self._tether_to_dim.items():
            ca = self.council.get_agent_by_dimension(dim)
            if ca:
                dist[tid] = ca.agent.wealth
        return dist

    def get_agent_dimension(self, tether_id: str) -> Optional[str]:
        """Get the council dimension for a tether_id."""
        return self._tether_to_dim.get(tether_id)

    # ── Stats ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get economic engine statistics."""
        return {
            "episode_count": self.episode_count,
            "total_rewards": self.total_rewards,
            "bankruptcy_count": self.bankruptcy_count,
            "population_size": len(self.council.get_all_agents()),
            "active_agents": self.council.active_count(),
            "bankrupt_agents": len(self.council.get_bankrupt_agents()),
            "total_wealth": sum(ca.agent.wealth for ca in self.council.get_all_agents()),
            "total_auctions": len(self.council._auction_history),
            "pricing_oracle_models": len(self.pricing_oracle.MODELS),
        }
