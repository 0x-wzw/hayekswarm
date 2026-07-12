"""EconomicRouter — routes tasks using the EoM economic engine.

Extends TetherRouter with auction-based task allocation using the
EconomicEngine. Supports two modes:
- "economic" (default): uses auctions to select the best agent
- "capability" (legacy): uses the original TetherRouter capability matching
"""

from __future__ import annotations

from typing import Any, Optional

from voidtether.core.manifest import TetherManifest
from voidtether.core.router import TetherRouter, TetherTask
from .engine import EconomicEngine
from .agent import EconomicAgent
from .config import EconomyConfig, EngineConfig, RewardConfig, EvolutionConfig


class EconomicRouter(TetherRouter):
    """Extends TetherRouter with auction-based economic routing.

    Args:
        engine: An optional EconomicEngine instance. Creates a default one if
            not provided.
    """

    def __init__(self, engine: Optional[EconomicEngine] = None):
        super().__init__()
        if engine is None:
            engine = EconomicEngine(
                config=EconomyConfig(
                    engine=EngineConfig(initial_wealth=100.0, base_bid=1.0),
                    reward=RewardConfig(),
                    evolution=EvolutionConfig(),
                )
            )
        self._engine = engine
        self._mode: str = "economic"

    @property
    def engine(self) -> EconomicEngine:
        return self._engine

    @property
    def config(self) -> EconomyConfig:
        return self._engine.config

    @config.setter
    def config(self, cfg: EconomyConfig) -> None:
        self._engine.config = cfg

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in ("economic", "capability"):
            raise ValueError(f"Invalid mode: {value}. Must be 'economic' or 'capability'.")
        self._mode = value

    def register(self, manifest: TetherManifest) -> EconomicAgent:
        """Register an agent in both the router and the economy.

        Args:
            manifest: The TetherManifest describing the agent.

        Returns:
            The EconomicAgent created in the economy.
        """
        super().register(manifest)
        return self._engine.register_agent(manifest)

    def unregister(self, tether_id: str) -> None:
        """Unregister agent from both router and economy.

        Args:
            tether_id: The tether_id of the agent to remove.
        """
        super().unregister(tether_id)
        self._engine.unregister_agent(tether_id)

    def route(self, task: TetherTask) -> Optional[TetherManifest]:
        """Route a task using economic auction instead of capability matching.

        1. Discover candidates by capability (same as before).
        2. Run auction among candidates.
        3. Return winning TetherManifest.

        In "capability" mode, falls back to the original TetherRouter behavior.

        Args:
            task: The task to route.

        Returns:
            The winning TetherManifest, or None if no suitable agent found.
        """
        if self._mode == "capability":
            return super().route(task)

        # Discover candidates by capability
        candidates = self.discover(
            task.task_type, protocol=task.target_protocol
        )
        if not candidates:
            candidates = self.discover(task.task_type)
        if not candidates:
            return None

        # Run auction among candidates
        winner_id, _ = self._engine.run_auction(
            task.task_type, candidates
        )
        if winner_id is None:
            return None
        return self.get(winner_id)

    def apply_reward(self, tether_id: str, reward: Optional[float] = None) -> Optional[float]:
        """Apply reward after task completion.

        Args:
            tether_id: The agent that completed the task.
            reward: The reward amount to apply. Uses 10.0 if None.

        Returns:
            The reward amount applied, or None if agent not found.
        """
        actual_reward = reward if reward is not None else 10.0
        self._engine.apply_reward(tether_id, actual_reward)
        return actual_reward

    def get_wealth(self, tether_id: str) -> float:
        """Get agent wealth.

        Args:
            tether_id: The tether_id of the agent.

        Returns:
            The agent's current wealth.
        """
        return self._engine.get_agent_wealth(tether_id)

    def get_wealth_distribution(self) -> dict[str, float]:
        """Get all agent wealths.

        Returns:
            Dict mapping tether_id -> wealth.
        """
        return self._engine.get_wealth_distribution()

    def get_economic_agent(self, tether_id: str) -> Optional[EconomicAgent]:
        """Get the EconomicAgent for a tether_id.

        Args:
            tether_id: The tether_id of the agent.

        Returns:
            The EconomicAgent, or None if not found.
        """
        for agent in self._engine.population.get_all():
            if agent.manifest.tether_id == tether_id:
                return agent
        return None

    def get_stats(self) -> dict[str, Any]:
        """Get economic engine statistics.

        Returns:
            Dict with episode_count, total_rewards, bankruptcy_count.
        """
        return {
            "episode_count": self._engine.episode_count,
            "total_rewards": self._engine.total_rewards,
            "bankruptcy_count": self._engine.bankruptcy_count,
            "population_size": len(self._engine.population),
        }
