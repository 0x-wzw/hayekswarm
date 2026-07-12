"""EconomicEngine — the main EoM economic lifecycle engine.

Runs the economic lifecycle: auction -> action -> reward -> bankruptcy -> births.
Simplified HayekMAS engine adapted for the VoidTether mesh.
"""

from __future__ import annotations

import random
import threading
from typing import Callable, Dict, List, Optional, Tuple

from voidtether.core.manifest import TetherManifest

from .agent import EconomicAgent, AgentStatus, set_agent_id_counter
from .auction import Auctioneer
from .config import EconomyConfig, EngineConfig, RewardConfig, EvolutionConfig
from .population import EconomicPopulation


class EconomicEngine:
    """Runs the economic lifecycle for the EoM economy.

    Manages agent registration, auctions, payments, rewards, bankruptcy
    detection, and evolutionary births.

    Args:
        config: Economy configuration.
    """

    def __init__(self, config: EconomyConfig):
        self.config = config
        self.population = EconomicPopulation()
        self.auctioneer = Auctioneer()

        # Engine state
        self.episode_count = 0
        self.total_rewards = 0.0
        self.bankruptcy_count = 0

        # Factories for creating new agents during evolution.
        # These should be set by the adapter using set_agent_factory().
        self._birth_good_agent_factory: Optional[Callable[[EconomicAgent], EconomicAgent]] = None
        self._birth_bad_agent_factory: Optional[Callable[..., EconomicAgent]] = None

        # Initial agents kept as templates for replenishment via mutation
        self._initial_agents: List[EconomicAgent] = []

        # Bucket-brigade credit assignment: the winner of the previous auction
        # is the recipient of the current winner's payment. Reset between episodes
        # via reset_payment_chain().
        self._prev_winner: Optional[EconomicAgent] = None

        # Bankrupt agents removed by the most recent check_bankruptcies() call,
        # kept so spawn_replacements() can build bad-birth children from them
        # (they are already gone from the population by then).
        self._recent_bankrupts: Dict[str, EconomicAgent] = {}

        # Thread safety
        self._lock = threading.Lock()

    # ── Agent factory registration ─────────────────────────────────────

    def set_agent_factory(
        self,
        birth_good_agent: Callable[[EconomicAgent], EconomicAgent],
        birth_bad_agent: Callable[..., EconomicAgent],
    ) -> None:
        """Set the agent factories for evolution/spawning.

        Args:
            birth_good_agent: Factory for good births (clone richest + mutate).
            birth_bad_agent: Factory for bad births (repair from failure trace).
        """
        self._birth_good_agent_factory = birth_good_agent
        self._birth_bad_agent_factory = birth_bad_agent

    # ── Agent registration ─────────────────────────────────────────────

    def register_agent(self, manifest: TetherManifest) -> EconomicAgent:
        """Register an agent into the economy.

        Creates an EconomicAgent wrapper around the manifest and adds it
        to the population.

        Args:
            manifest: The TetherManifest describing the agent.

        Returns:
            The newly created EconomicAgent.
        """
        agent = EconomicAgent(
            manifest=manifest,
            initial_wealth=self.config.engine.initial_wealth,
        )
        with self._lock:
            self.population.add_agent(agent)
            self._initial_agents.append(agent)
        return agent

    def unregister_agent(self, tether_id: str) -> None:
        """Remove an agent from the economy by tether_id.

        Args:
            tether_id: The tether_id of the agent to remove.
        """
        with self._lock:
            for agent in list(self.population.get_all()):
                if agent.manifest.tether_id == tether_id:
                    self.population.remove_agent(agent)
                    break

    # ── Auction lifecycle ──────────────────────────────────────────────

    def run_auction(
        self,
        task_type: str,
        candidates: List[TetherManifest],
    ) -> Tuple[Optional[str], float]:
        """Run an auction among candidate agents for a task.

        1. Filter candidates to those in the population.
        2. Initialize bids.
        3. Select winner.
        4. Process payment.

        Args:
            task_type: The type of task being auctioned (for logging).
            candidates: List of TetherManifests of candidate agents.

        Returns:
            Tuple of (winning_tether_id, payment_amount).
            winning_tether_id is None if no candidates are available.
        """
        with self._lock:
            # Build a lookup of tether_id -> EconomicAgent
            agent_by_tether: Dict[str, EconomicAgent] = {}
            for agent in self.population.get_all():
                agent_by_tether[agent.manifest.tether_id] = agent

            # Filter candidates to those in the population
            active_agents: List[EconomicAgent] = []
            for manifest in candidates:
                econ_agent = agent_by_tether.get(manifest.tether_id)
                if econ_agent is not None:
                    active_agents.append(econ_agent)

            if not active_agents:
                return None, 0.0

            # Run the auction
            winner, payment = self.auctioneer.run_auction(
                active_agents=active_agents,
                bid_scheme=self.config.engine.bid_scheme,
                engine_config=self.config.engine,
                training=True,
            )

            # Bucket-brigade: the winner pays its bid to the previous auction's
            # winner (decentralized credit assignment). The first winner in a
            # chain pays to the void; call reset_payment_chain() at episode
            # boundaries to start a new chain.
            self.auctioneer.process_payment(
                winner, payment, prev_winner=self._prev_winner
            )
            self._prev_winner = winner

            return winner.manifest.tether_id, payment

    def reset_payment_chain(self) -> None:
        """Clear the bucket-brigade chain (call at the start of each episode)."""
        with self._lock:
            self._prev_winner = None

    # ── Reward application ────────────────────────────────────────────

    def apply_reward(self, tether_id: str, reward: float) -> None:
        """Apply reward to an agent after task completion.

        Args:
            tether_id: The tether_id of the agent to reward.
            reward: The reward amount.
        """
        with self._lock:
            for agent in self.population.get_all():
                if agent.manifest.tether_id == tether_id:
                    agent.gain_money(reward)
                    agent.gain_capability(reward)
                    self.total_rewards += reward
                    break

    # ── Bankruptcy handling ───────────────────────────────────────────

    def check_bankruptcies(self) -> List[str]:
        """Check for and remove bankrupt agents.

        An agent is bankrupt when wealth < 0.

        Returns:
            List of tether_ids of removed bankrupt agents.
        """
        with self._lock:
            bankrupt_agents = [
                a for a in self.population.get_all() if a.check_bankruptcy()
            ]
            removed_ids: List[str] = []
            # Reset and repopulate the recent-bankrupts cache so spawn_replacements()
            # can still reach these agent objects after they leave the population.
            self._recent_bankrupts = {}
            for agent in bankrupt_agents:
                agent.bankruptcy_episode = self.episode_count
                tid = agent.manifest.tether_id
                removed_ids.append(tid)
                self._recent_bankrupts[tid] = agent
                self.population.remove_agent(agent)
                self.bankruptcy_count += 1
            return removed_ids

    def spawn_replacements(self, bankrupt_tether_ids: List[str]) -> None:
        """Spawn replacement agents via good/bad births.

        For each bankrupt agent, draws from the evolution probabilities:
        - p_a: good birth (clone richest agent with mutated prompt)
        - p_b: bad birth (create from bankrupt's failure trace)
        - else: no birth

        Args:
            bankrupt_tether_ids: List of tether_ids of bankrupt agents.
        """
        if not bankrupt_tether_ids:
            return

        evo = self.config.evolution
        if not (0.0 <= evo.p_a <= 1.0 and 0.0 <= evo.p_b <= 1.0 and evo.p_a + evo.p_b <= 1.0):
            raise ValueError(
                f"evolution.p_a + evolution.p_b must be in [0, 1], "
                f"got {evo.p_a} + {evo.p_b} = {evo.p_a + evo.p_b}"
            )

        with self._lock:
            # Bankrupt agents are already removed from the population by
            # check_bankruptcies(), so look them up in the recent-bankrupts cache
            # rather than the (now-empty-of-them) population.
            bankrupt_by_tether: Dict[str, EconomicAgent] = {
                tid: self._recent_bankrupts[tid]
                for tid in bankrupt_tether_ids
                if tid in self._recent_bankrupts
            }

            for tid in bankrupt_tether_ids:
                draw = random.random()
                if draw < evo.p_a:
                    # Good birth: clone richest agent
                    parent = self.population.get_richest_agent()
                    if parent is not None:
                        self._add_born_agent(self._birth_good_agent(parent))
                elif draw < evo.p_a + evo.p_b:
                    # Bad birth: create from bankrupt's failure trace
                    source = bankrupt_by_tether.get(tid)
                    if source is not None:
                        self._add_born_agent(self._birth_bad_agent(source))
                # else: no birth

    # ── Wealth queries ─────────────────────────────────────────────────

    def get_agent_wealth(self, tether_id: str) -> float:
        """Get current wealth of an agent.

        Args:
            tether_id: The tether_id of the agent.

        Returns:
            The agent's current wealth, or 0.0 if not found.
        """
        with self._lock:
            for agent in self.population.get_all():
                if agent.manifest.tether_id == tether_id:
                    return agent.wealth
            return 0.0

    def get_wealth_distribution(self) -> Dict[str, float]:
        """Get wealth of all agents.

        Returns:
            Dict mapping tether_id -> wealth.
        """
        with self._lock:
            return {
                agent.manifest.tether_id: agent.wealth
                for agent in self.population.get_all()
            }

    # ── Internal helpers ──────────────────────────────────────────────

    def _birth_good_agent(self, parent: EconomicAgent) -> Optional[EconomicAgent]:
        """Create a more exploratory child from a strong surviving agent.

        Args:
            parent: The parent agent to clone and mutate.

        Returns:
            The new agent, or None if factory is not set.
        """
        if self._birth_good_agent_factory is None:
            return None
        try:
            new_agent = self._birth_good_agent_factory(parent)
            new_agent.root_ancestor_class = getattr(
                parent, "root_ancestor_class", parent.manifest.origin_protocol.value
            )
            new_agent.parent_agent_id = parent.id
            new_agent.spawn_method = "good_birth"
            new_agent.tasks_lived = 0
            new_agent.bankruptcy_episode = None
            return new_agent
        except Exception:
            return None

    def _birth_bad_agent(self, source_agent: EconomicAgent) -> Optional[EconomicAgent]:
        """Create a repaired child from a failed or bankrupt source agent.

        Args:
            source_agent: The bankrupt source agent.

        Returns:
            The new agent, or None if factory is not set.
        """
        if self._birth_bad_agent_factory is None:
            return None
        try:
            new_agent = self._birth_bad_agent_factory(
                source_agent,
                task_description=source_agent.recent_failure_task,
                correct_answer=source_agent.recent_failure_answer,
                failure_trace=(
                    source_agent.recent_failure_trace
                    or source_agent.get_trace_recorded_at_death()
                ),
            )
            new_agent.root_ancestor_class = getattr(
                source_agent,
                "root_ancestor_class",
                source_agent.manifest.origin_protocol.value,
            )
            new_agent.parent_agent_id = source_agent.id
            new_agent.spawn_method = "bad_birth"
            new_agent.tasks_lived = 0
            new_agent.bankruptcy_episode = None
            return new_agent
        except Exception:
            return None

    def _add_born_agent(self, agent: Optional[EconomicAgent]) -> bool:
        """Add a newborn agent when it exists and the population cap allows it.

        Args:
            agent: The newborn agent, or None.

        Returns:
            True if the agent was added.
        """
        if agent is None:
            return False
        max_agents = self.config.engine.max_num_agents
        if max_agents > 0 and len(self.population) >= max_agents:
            return False
        agent.initialize(initial_wealth=self.config.engine.initial_wealth)
        self.population.add_agent(agent)
        return True

    def _can_add_agent(self) -> bool:
        """Return whether another agent can be added under the population cap."""
        max_agents = self.config.engine.max_num_agents
        return max_agents <= 0 or len(self.population) < max_agents

    # ── Serialization ─────────────────────────────────────────────────

    def serialize_settings(self) -> dict:
        """Serialize engine settings to a dictionary.

        Returns:
            Dict with config, stats, and max_agent_id.
        """
        max_id = max(self.population.get_agent_ids(), default=0)
        return {
            "version": "1.0",
            "config": {
                "engine": {
                    "max_steps_per_episode": self.config.engine.max_steps_per_episode,
                    "max_trials_per_episode": self.config.engine.max_trials_per_episode,
                    "birth_interval": self.config.engine.birth_interval,
                    "num_births_per_interval": self.config.engine.num_births_per_interval,
                    "min_num_agents": self.config.engine.min_num_agents,
                    "max_num_agents": self.config.engine.max_num_agents,
                    "bid_scheme": self.config.engine.bid_scheme,
                    "base_bid": self.config.engine.base_bid,
                    "novice_bid_epsilon": self.config.engine.novice_bid_epsilon,
                    "initial_wealth": self.config.engine.initial_wealth,
                    "rent": self.config.engine.rent,
                    "rent_interval": self.config.engine.rent_interval,
                    "holland_alpha": self.config.engine.holland_alpha,
                    "tycoon_wealth_threshold": self.config.engine.tycoon_wealth_threshold,
                },
                "reward": {
                    "reward_scheme": self.config.reward.reward_scheme,
                    "path_reward_scale": self.config.reward.path_reward_scale,
                    "env_reward_scale": self.config.reward.env_reward_scale,
                    "center_env_reward": self.config.reward.center_env_reward,
                    "path_reward_per_unique_author": self.config.reward.path_reward_per_unique_author,
                    "step_reward_split_chain": self.config.reward.step_reward_split_chain,
                    "step_reward_chain_window": self.config.reward.step_reward_chain_window,
                },
                "evolution": {
                    "p_a": self.config.evolution.p_a,
                    "p_b": self.config.evolution.p_b,
                    "periodical_good_p": self.config.evolution.periodical_good_p,
                },
            },
            "stats": {
                "episodes": self.episode_count,
                "total_rewards": self.total_rewards,
                "bankruptcies": self.bankruptcy_count,
            },
            "max_agent_id": max_id,
        }

    @classmethod
    def deserialize_settings(cls, data: dict) -> "EconomicEngine":
        """Deserialize engine settings from a dictionary.

        Args:
            data: Serialized settings dict.

        Returns:
            A new EconomicEngine with restored settings.
        """
        config_raw = data.get("config", {})

        # Build EconomyConfig from serialized data
        engine_raw = config_raw.get("engine", {})
        reward_raw = config_raw.get("reward", {})
        evolution_raw = config_raw.get("evolution", {})

        engine_cfg = EngineConfig(
            max_steps_per_episode=engine_raw.get("max_steps_per_episode", 10),
            max_trials_per_episode=engine_raw.get("max_trials_per_episode", 4),
            birth_interval=engine_raw.get("birth_interval", 5),
            num_births_per_interval=engine_raw.get("num_births_per_interval", 2),
            min_num_agents=engine_raw.get("min_num_agents", 0),
            max_num_agents=engine_raw.get("max_num_agents", 0),
            bid_scheme=engine_raw.get("bid_scheme", "fixed"),
            base_bid=engine_raw.get("base_bid", 0.1),
            novice_bid_epsilon=engine_raw.get("novice_bid_epsilon", 0.01),
            initial_wealth=engine_raw.get("initial_wealth", 0.5),
            rent=engine_raw.get("rent", 0.0),
            rent_interval=engine_raw.get("rent_interval", 5),
            holland_alpha=engine_raw.get("holland_alpha", 0.1),
            tycoon_wealth_threshold=engine_raw.get("tycoon_wealth_threshold", 5.0),
        )
        reward_cfg = RewardConfig(
            reward_scheme=reward_raw.get("reward_scheme", "path_reward_only"),
            path_reward_scale=reward_raw.get("path_reward_scale", 1.0),
            env_reward_scale=reward_raw.get("env_reward_scale", 1.0),
            center_env_reward=reward_raw.get("center_env_reward", True),
            path_reward_per_unique_author=reward_raw.get(
                "path_reward_per_unique_author", False
            ),
            step_reward_split_chain=reward_raw.get("step_reward_split_chain", False),
            step_reward_chain_window=reward_raw.get("step_reward_chain_window", 3),
        )
        evolution_cfg = EvolutionConfig(
            p_a=evolution_raw.get("p_a", 0.0),
            p_b=evolution_raw.get("p_b", 1.0),
            periodical_good_p=evolution_raw.get("periodical_good_p", 0.5),
        )

        config = EconomyConfig(
            engine=engine_cfg,
            reward=reward_cfg,
            evolution=evolution_cfg,
        )

        engine = cls(config=config)

        stats = data.get("stats", {})
        engine.episode_count = stats.get("episodes", 0)
        engine.total_rewards = stats.get("total_rewards", 0.0)
        engine.bankruptcy_count = stats.get("bankruptcies", 0)

        max_id = data.get("max_agent_id", 0)
        set_agent_id_counter(max_id + 1)

        return engine
