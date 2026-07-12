"""HayekRouter — Routes tasks using the full HayekSwarm economic engine.

Extends TetherRouter with auction-based task allocation using the
HayekEngine (which wraps HayekMAS + 10-D Council + PricingOracle + Consensus).

Supports two modes:
- "economic" (default): uses HayekSwarm auctions to select the best agent
- "capability" (legacy): uses the original TetherRouter capability matching
"""

from __future__ import annotations

from typing import Any, Optional

from voidtether.core.manifest import TetherManifest
from voidtether.core.router import TetherRouter, TetherTask
from .hayek_engine import HayekEngine


class HayekRouter(TetherRouter):
    """Extends TetherRouter with HayekSwarm economic routing.

    Args:
        engine: An optional HayekEngine instance. Creates a default one if
            not provided.
    """

    def __init__(self, engine: Optional[HayekEngine] = None):
        super().__init__()
        self._engine = engine or HayekEngine()
        self._mode: str = "economic"

    @property
    def engine(self) -> HayekEngine:
        return self._engine

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in ("economic", "capability"):
            raise ValueError(f"Invalid mode: {value}. Must be 'economic' or 'capability'.")
        self._mode = value

    def register(self, manifest: TetherManifest) -> str:
        """Register an agent in both the router and the Hayek economy.

        Args:
            manifest: The TetherManifest describing the agent.

        Returns:
            The assigned dimension key.
        """
        super().register(manifest)
        return self._engine.register_agent(manifest)

    def unregister(self, tether_id: str) -> None:
        """Unregister agent from both router and economy."""
        super().unregister(tether_id)
        self._engine.unregister_agent(tether_id)

    def route(self, task: TetherTask) -> Optional[TetherManifest]:
        """Route a task using HayekSwarm economic auction.

        In "capability" mode, falls back to the original TetherRouter behavior.
        """
        if self._mode == "capability":
            return super().route(task)

        # Discover candidates by capability
        candidates = self.discover(task.task_type, protocol=task.target_protocol)
        if not candidates:
            candidates = self.discover(task.task_type)
        if not candidates:
            return None

        # Run HayekSwarm auction
        winner_id, _ = self._engine.run_auction(task.task_type, candidates)
        if winner_id is None:
            return None
        return self.get(winner_id)

    def apply_reward(self, tether_id: str, reward: Optional[float] = None) -> Optional[float]:
        """Apply reward after task completion."""
        actual_reward = reward if reward is not None else 10.0
        self._engine.apply_reward(tether_id, actual_reward)
        return actual_reward

    def get_wealth(self, tether_id: str) -> float:
        """Get agent wealth."""
        return self._engine.get_agent_wealth(tether_id)

    def get_wealth_distribution(self) -> dict[str, float]:
        """Get all agent wealths."""
        return self._engine.get_wealth_distribution()

    def get_stats(self) -> dict[str, Any]:
        """Get HayekSwarm economic engine statistics."""
        return self._engine.get_stats()
