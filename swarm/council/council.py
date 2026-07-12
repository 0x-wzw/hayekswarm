"""
Council — The 10-D agent population manager for HayekSwarm.

The Council manages the 10-dimensional agent population, runs first-price
auctions for task allocation, handles economic selection (good-birth mutation
and bad-birth replacement), and coordinates multi-agent deliberation.

Each dimension (D1-D10) is represented by a HayekMAS-compatible agent that
bids in auctions and acts using its assigned model dimension.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from .agents import (
    AGENT_CLASSES,
    BaseAgent,
    AgentStatus,
    create_agent_for_dimension,
    create_all_council_agents,
)
from .dimension_map import (
    DIMENSION_MAP,
    DIMENSION_FALLBACK,
    DIMENSION_ORDER,
    get_dimensions_for_stakes,
    get_model_for_dimension,
)

logger = logging.getLogger(__name__)


# ── CouncilAgent — Wrapper for an agent in the council ──────────────────────


@dataclass
class CouncilAgent:
    """
    A council-registered agent with dimension metadata.

    Wraps a BaseAgent with council-specific tracking: bid history,
    win/loss record, and dimension assignment.
    """

    agent: BaseAgent
    dimension: str
    wins: int = 0
    losses: int = 0
    total_bids: int = 0
    last_bid_amount: float = 0.0

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def model(self) -> str:
        return self.agent.model

    @property
    def wealth(self) -> float:
        return self.agent.wealth

    @property
    def status(self) -> AgentStatus:
        return self.agent.status

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.0

    def __repr__(self) -> str:
        return (
            f"CouncilAgent(dim={self.dimension}, name={self.name!r}, "
            f"wealth={self.wealth:.2f}, wins={self.wins}, losses={self.losses})"
        )


# ── Auction Result ──────────────────────────────────────────────────────────


@dataclass
class AuctionResult:
    """Result of a council auction."""

    task: dict[str, Any]
    winner: CouncilAgent | None
    all_bids: list[tuple[CouncilAgent, float]]
    winning_bid: float
    total_participants: int
    dimension_used: str | None


# ── Council ─────────────────────────────────────────────────────────────────


class Council:
    """
    The 10-D Council — manages the agent population and runs auctions.

    The Council maintains one agent per dimension (D1-D10), runs first-price
    auctions to allocate tasks, and supports economic selection through
    good-birth (clone richest) and bad-birth (replace poorest) operations.
    """

    def __init__(
        self,
        initial_wealth: float = 100.0,
        base_bid: float = 1.0,
        bid_scheme: str = "fixed",
    ):
        """
        Initialize the Council with 10 dimension agents.

        Args:
            initial_wealth: Starting wealth for each agent.
            base_bid: Base bid amount for auctions.
            bid_scheme: Bidding strategy ("fixed", "fixed_with_eps", "holland").
        """
        self._agents: dict[str, CouncilAgent] = {}
        self._base_bid = base_bid
        self._bid_scheme = bid_scheme
        self._initial_wealth = initial_wealth
        self._auction_history: list[AuctionResult] = []

        # Create one agent per dimension
        for dim in DIMENSION_ORDER:
            agent = create_agent_for_dimension(dim, wealth=initial_wealth)
            self._agents[dim] = CouncilAgent(agent=agent, dimension=dim)

        logger.info(
            "Council initialized with %d agents (base_bid=%.2f, scheme=%s)",
            len(self._agents),
            base_bid,
            bid_scheme,
        )

    # ── Agent accessors ──────────────────────────────────────────────────────

    def get_agent_by_dimension(self, dimension: str) -> CouncilAgent | None:
        """Get the council agent for a given dimension key."""
        return self._agents.get(dimension)

    def get_agent_by_name(self, name: str) -> CouncilAgent | None:
        """Find a council agent by name."""
        for ca in self._agents.values():
            if ca.name == name:
                return ca
        return None

    def get_richest_agent(self) -> CouncilAgent | None:
        """
        Get the agent with the highest wealth.

        Used for good-birth mutation (clone the richest).
        """
        if not self._agents:
            return None
        return max(self._agents.values(), key=lambda ca: ca.agent.wealth)

    def get_poorest_agent(self) -> CouncilAgent | None:
        """
        Get the agent with the lowest wealth (excluding bankrupt).

        Used for bad-birth replacement (replace the poorest).
        """
        active = [ca for ca in self._agents.values() if not ca.agent.is_bankrupt()]
        if not active:
            return None
        return min(active, key=lambda ca: ca.agent.wealth)

    def get_all_agents(self) -> list[CouncilAgent]:
        """Get all council agents."""
        return list(self._agents.values())

    def get_active_agents(self) -> list[CouncilAgent]:
        """Get agents that are not bankrupt."""
        return [ca for ca in self._agents.values() if not ca.agent.is_bankrupt()]

    def get_bankrupt_agents(self) -> list[CouncilAgent]:
        """Get agents that are bankrupt."""
        return [ca for ca in self._agents.values() if ca.agent.is_bankrupt()]

    def agent_count(self) -> int:
        return len(self._agents)

    def active_count(self) -> int:
        return len(self.get_active_agents())

    # ── Auction / deliberation ──────────────────────────────────────────────

    def deliberate(self, task: dict[str, Any]) -> AuctionResult:
        """
        Run a first-price auction among eligible agents for the given task.

        The deliberation process:
        1. Determine which dimensions are eligible for the task
        2. Collect bids from eligible agents
        3. Select the winner (highest bidder)
        4. Execute the action via the winning agent
        5. Process payment (winner pays their bid)

        Args:
            task: Task dict with at least "content" (the prompt).
                  Optional: "stakes", "dimensions", "capabilities".

        Returns:
            An AuctionResult with the winner, all bids, and outcome.
        """
        # 1. Find eligible agents
        eligible = self._find_eligible_agents(task)

        if not eligible:
            logger.warning("No eligible agents for task: %s", task.get("content", "")[:80])
            return AuctionResult(
                task=task,
                winner=None,
                all_bids=[],
                winning_bid=0.0,
                total_participants=0,
                dimension_used=None,
            )

        # 2. Collect bids
        bids: list[tuple[CouncilAgent, float]] = []
        for ca in eligible:
            bid_amount = self._compute_bid(ca)
            ca.last_bid_amount = bid_amount
            ca.total_bids += 1
            bids.append((ca, bid_amount))

        # 3. Select winner (first-price: highest bidder wins, pays their bid)
        bids.sort(key=lambda x: x[1], reverse=True)
        winner_ca, winning_bid = bids[0]

        # 4. Execute the action
        result = winner_ca.agent.act(task)

        # 5. Process payment
        winner_ca.agent.apply_payment(winning_bid)
        winner_ca.wins += 1
        for ca, _ in bids[1:]:
            ca.losses += 1

        # Record auction
        auction_result = AuctionResult(
            task=task,
            winner=winner_ca,
            all_bids=bids,
            winning_bid=winning_bid,
            total_participants=len(eligible),
            dimension_used=winner_ca.dimension,
        )
        self._auction_history.append(auction_result)

        logger.info(
            "Auction won by %s (%s) with bid %.2f (dim=%s, participants=%d)",
            winner_ca.name,
            winner_ca.dimension,
            winning_bid,
            winner_ca.dimension,
            len(eligible),
        )

        return auction_result

    def _find_eligible_agents(self, task: dict[str, Any]) -> list[CouncilAgent]:
        """
        Find agents eligible to bid on a task.

        Uses match_wakeup_condition on each agent, filtered by stakes
        routing if available.
        """
        # Start with all non-bankrupt agents
        candidates = self.get_active_agents()

        # Filter by stakes routing if provided
        stakes = task.get("stakes")
        if stakes:
            allowed_dims = get_dimensions_for_stakes(stakes)
            candidates = [ca for ca in candidates if ca.dimension in allowed_dims]

        # Filter by explicit dimensions if provided
        explicit_dims = task.get("dimensions", [])
        if explicit_dims:
            candidates = [ca for ca in candidates if ca.dimension in explicit_dims]

        # Apply wake-up condition
        eligible = [ca for ca in candidates if ca.agent.match_wakeup_condition(task)]

        return eligible

    def _compute_bid(self, ca: CouncilAgent) -> float:
        """Compute an agent's bid based on the configured scheme."""
        agent = ca.agent

        if self._bid_scheme == "fixed":
            return agent.compute_bid(self._base_bid)

        elif self._bid_scheme == "fixed_with_eps":
            if agent.status == AgentStatus.NOVICE:
                # Novice bids max(veteran_bids) + epsilon
                veteran_bids = [
                    c.last_bid_amount
                    for c in self._agents.values()
                    if c.agent.status == AgentStatus.VETERAN and c.last_bid_amount > 0
                ]
                max_vet = max(veteran_bids) if veteran_bids else self._base_bid
                return max_vet + 0.01
            return self._base_bid

        elif self._bid_scheme == "holland":
            if agent.status == AgentStatus.NOVICE:
                tycoon_bids = [
                    c.last_bid_amount
                    for c in self._agents.values()
                    if c.agent.status == AgentStatus.TYCOON and c.last_bid_amount > 0
                ]
                max_tyc = max(tycoon_bids) if tycoon_bids else self._base_bid
                return max_tyc + 0.01
            elif agent.status == AgentStatus.TYCOON:
                return 0.1 * agent.wealth
            return self._base_bid

        else:
            return agent.compute_bid(self._base_bid)

    # ── Economic selection ──────────────────────────────────────────────────

    def good_birth(self) -> CouncilAgent | None:
        """
        Good-birth mutation: clone the richest agent.

        The richest agent is cloned with a mutated system prompt for
        exploration. Returns the new agent or None if no agent exists.
        """
        richest = self.get_richest_agent()
        if richest is None:
            return None

        # Clone: create a new agent of the same dimension
        dim = richest.dimension
        new_agent = create_agent_for_dimension(
            dim,
            name=f"{richest.name}-clone-{random.randint(1000, 9999)}",
            wealth=self._initial_wealth,
        )

        # Mutate: append a mutation marker to the system prompt
        new_agent.frozen_system_prompt += (
            "\n\n[GOOD-BIRTH MUTATION] You are an exploratory variant. "
            "Try different approaches and strategies than your parent."
        )

        # Register in council
        ca = CouncilAgent(agent=new_agent, dimension=dim)
        ca.agent.lineage = richest.agent.lineage + [richest.name]
        self._agents[dim] = ca

        logger.info(
            "Good birth: cloned %s -> %s (dim=%s)",
            richest.name,
            new_agent.name,
            dim,
        )
        return ca

    def bad_birth(self) -> CouncilAgent | None:
        """
        Bad-birth replacement: replace the poorest agent with a fresh one.

        The poorest (non-bankrupt) agent is replaced by a new agent of the
        same dimension with fresh wealth. Returns the new agent or None.
        """
        poorest = self.get_poorest_agent()
        if poorest is None:
            return None

        dim = poorest.dimension
        old_name = poorest.name

        # Create replacement
        new_agent = create_agent_for_dimension(
            dim,
            name=f"{dim.replace('_', '-')}-reborn-{random.randint(1000, 9999)}",
            wealth=self._initial_wealth,
        )

        # Register in council
        ca = CouncilAgent(agent=new_agent, dimension=dim)
        self._agents[dim] = ca

        logger.info(
            "Bad birth: replaced %s -> %s (dim=%s)",
            old_name,
            new_agent.name,
            dim,
        )
        return ca

    def apply_reward(self, dimension: str, amount: float):
        """
        Apply a reward to the agent of the given dimension.

        Args:
            dimension: The dimension key (e.g. "D3_code").
            amount: Reward amount to add to wealth.
        """
        ca = self._agents.get(dimension)
        if ca is not None:
            ca.agent.apply_reward(amount)
            logger.debug("Reward %.2f applied to %s (%s)", amount, ca.name, dimension)

    def apply_reward_to_winner(self, amount: float):
        """
        Apply a reward to the most recent auction winner.

        Args:
            amount: Reward amount to add to the winner's wealth.
        """
        if self._auction_history:
            last = self._auction_history[-1]
            if last.winner is not None:
                last.winner.agent.apply_reward(amount)

    # ── State management ────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Capture the state of all agents for rollback."""
        return {
            dim: ca.agent.snapshot()
            for dim, ca in self._agents.items()
        }

    def restore(self, state: dict[str, dict[str, Any]]):
        """Restore all agents from a snapshot."""
        for dim, agent_state in state.items():
            ca = self._agents.get(dim)
            if ca is not None:
                ca.agent.restore(agent_state)

    def get_stats(self) -> dict[str, Any]:
        """Get council statistics."""
        return {
            "total_agents": len(self._agents),
            "active_agents": self.active_count(),
            "bankrupt_agents": len(self.get_bankrupt_agents()),
            "total_auctions": len(self._auction_history),
            "total_wealth": sum(ca.agent.wealth for ca in self._agents.values()),
            "richest_agent": str(self.get_richest_agent()),
            "poorest_agent": str(self.get_poorest_agent()),
            "bid_scheme": self._bid_scheme,
            "base_bid": self._base_bid,
            "agents": {
                dim: {
                    "name": ca.name,
                    "wealth": ca.agent.wealth,
                    "status": ca.agent.status.value,
                    "wins": ca.wins,
                    "losses": ca.losses,
                    "total_tasks": ca.agent.total_tasks,
                    "total_reward": ca.agent.total_reward,
                }
                for dim, ca in self._agents.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"Council(agents={len(self._agents)}, "
            f"active={self.active_count()}, "
            f"auctions={len(self._auction_history)})"
        )
