"""Engine-level configuration objects for the EoM economic engine.

Mirrors the HayekMAS config structure from the EoM paper
(arxiv.org/abs/2606.02859).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EngineConfig:
    """Core engine parameters for episode execution, population, and bidding.

    Attributes:
        max_steps_per_episode: Maximum steps per episode.
        max_trials_per_episode: Maximum replay trials per episode.
        birth_interval: Episodes between periodic births (0 = disabled).
        num_births_per_interval: Number of births per birth interval.
        min_num_agents: Minimum population size (replenished if below).
        max_num_agents: Maximum population cap (0 = unlimited).
        bid_scheme: Bidding strategy — "fixed", "fixed_with_eps", or "holland".
        base_bid: Base bid amount for VETERAN agents.
        novice_bid_epsilon: Premium added to novice's first bid.
        initial_wealth: Starting wealth for new agents.
        rent: Flat rent charged periodically (0 = disabled).
        rent_interval: Episodes between rent charges.
        holland_alpha: Wealth-proportional bid coefficient for TYCOONs.
        tycoon_wealth_threshold: Wealth threshold for VETERAN -> TYCOON promotion.
    """
    max_steps_per_episode: int = 10
    max_trials_per_episode: int = 4
    birth_interval: int = 5
    num_births_per_interval: int = 2
    min_num_agents: int = 0
    max_num_agents: int = 0
    bid_scheme: str = "fixed"
    base_bid: float = 0.1
    novice_bid_epsilon: float = 0.01
    initial_wealth: float = 0.5
    rent: float = 0.0
    rent_interval: int = 5
    holland_alpha: float = 0.1
    tycoon_wealth_threshold: float = 5.0


@dataclass
class RewardConfig:
    """Reward settings used by the engine.

    Attributes:
        reward_scheme: "path_reward_only" or "path_reward_and_stepwise_reward".
        path_reward_scale: Scale factor for path (episode-end) rewards.
        env_reward_scale: Scale factor for per-step environment rewards.
        center_env_reward: Whether to center env rewards around zero.
        path_reward_per_unique_author: Split path reward across unique authors.
        step_reward_split_chain: Split step reward across recent winners.
        step_reward_chain_window: Window size for chain splitting.
    """
    reward_scheme: str = "path_reward_only"
    path_reward_scale: float = 1.0
    env_reward_scale: float = 1.0
    center_env_reward: bool = True
    path_reward_per_unique_author: bool = False
    step_reward_split_chain: bool = False
    step_reward_chain_window: int = 3

    def centered_score(self, score: float) -> float:
        """Center a [0, 1] score to [-1, 1]."""
        return 2.0 * score - 1.0

    def reward_signal(self, score: float) -> float:
        """Shaped terminal score for env rewards."""
        base = self.centered_score(score) if self.center_env_reward else score
        return self.env_reward_scale * base

    def path_reward_per_agent(self, score: float, path_length: int) -> float:
        """Per-agent share of path reward."""
        if path_length <= 0:
            return 0.0
        return self.path_reward_scale * self.reward_signal(score) / path_length


@dataclass
class EvolutionConfig:
    """Evolution settings for good/bad births.

    Attributes:
        p_a: Probability of good birth (clone richest agent with mutation).
        p_b: Probability of bad birth (create from bankrupt's failure trace).
        periodical_good_p: Probability of good birth during periodic births.
    """
    p_a: float = 0.0
    p_b: float = 1.0
    periodical_good_p: float = 0.5


@dataclass
class EconomyConfig:
    """Top-level configuration container for the EoM economic engine.

    Attributes:
        engine: Core engine parameters.
        reward: Reward configuration.
        evolution: Evolution/birth configuration.
    """
    engine: EngineConfig = field(default_factory=EngineConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
