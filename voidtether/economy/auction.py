"""Auctioneer — runs auctions for task allocation in the EoM economy.

Implements the three bid schemes from the EoM paper:
- "fixed": NOVICE gets base_bid + epsilon, VETERAN gets base_bid
- "fixed_with_eps": NOVICE gets max(veteran_bids) + epsilon
- "holland": NOVICE gets max(tycoon_bids) + epsilon, TYCOONs bid alpha * wealth
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from .agent import EconomicAgent, AgentStatus
from .config import EngineConfig, RewardConfig


class Auctioneer:
    """Runs auctions for task allocation among economic agents.

    Handles bid initialization, winner selection (random among top bidders),
    payment processing (first-price, peer-to-peer), and reward distribution.
    """

    def run_auction(
        self,
        active_agents: List[EconomicAgent],
        bid_scheme: str,
        engine_config: EngineConfig,
        training: bool,
    ) -> Tuple[EconomicAgent, float]:
        """Run a single auction among active agents.

        Steps:
        1. Initialize bids based on the configured scheme (training only).
        2. Select winner = random choice among top bidders (highest bid).
        3. Payment = winner's bid (first-price).

        Args:
            active_agents: Agents eligible to bid in this auction.
            bid_scheme: One of "fixed", "fixed_with_eps", "holland".
            engine_config: Engine configuration with bid parameters.
            training: Whether the engine is in training mode.

        Returns:
            Tuple of (winner_agent, payment_amount).

        Raises:
            ValueError: If bid_scheme is unknown.
        """
        if training:
            self._initialize_bids(active_agents, bid_scheme, engine_config)

        # Winner selection: random among top bidders
        bids: List[float] = []
        for a in active_agents:
            b = a.get_bid()
            assert b is not None, f"Agent {a.name} has no bid"
            bids.append(b)
        max_bid = max(bids)
        top_bidders = [a for a in active_agents if a.get_bid() == max_bid]
        winner = random.choice(top_bidders)
        payment = max_bid

        return winner, payment

    def _initialize_bids(
        self,
        active_agents: List[EconomicAgent],
        bid_scheme: str,
        config: EngineConfig,
    ) -> None:
        """Initialize bids for all active agents based on the scheme.

        Args:
            active_agents: Agents to initialize bids for.
            bid_scheme: Bidding strategy name.
            config: Engine configuration.

        Raises:
            ValueError: If bid_scheme is unknown.
        """
        if bid_scheme == "fixed":
            self._init_bids_fixed(active_agents, config)
        elif bid_scheme == "fixed_with_eps":
            self._init_bids_fixed_with_eps(active_agents, config)
        elif bid_scheme == "holland":
            self._init_bids_holland(active_agents, config)
        else:
            raise ValueError(f"Unknown bid_scheme: {bid_scheme}")

    def _init_bids_fixed(
        self, active_agents: List[EconomicAgent], config: EngineConfig
    ) -> None:
        """Fixed scheme: NOVICE gets base_bid + epsilon, VETERAN gets base_bid.

        Novice agents are promoted to VETERAN after their first bid.
        """
        for agent in active_agents:
            status = agent.get_status()
            if status == AgentStatus.NOVICE:
                agent.set_bid(config.base_bid + config.novice_bid_epsilon)
                agent.set_status(AgentStatus.VETERAN)
            elif status == AgentStatus.VETERAN:
                agent.set_bid(config.base_bid)

    def _init_bids_fixed_with_eps(
        self, active_agents: List[EconomicAgent], config: EngineConfig
    ) -> None:
        """Fixed-with-eps scheme: NOVICE gets max(veteran_bids) + epsilon.

        Once set, the bid never changes (accumulated). Novices are promoted
        to VETERAN after their first bid.
        """
        veteran_bids: List[float] = []
        for a in active_agents:
            if a.get_status() == AgentStatus.VETERAN:
                b = a.get_bid()
                if b is not None:
                    veteran_bids.append(b)
        high_bid = max(veteran_bids) if veteran_bids else config.base_bid
        for agent in active_agents:
            if agent.get_status() == AgentStatus.NOVICE:
                agent.set_bid(high_bid + config.novice_bid_epsilon)
                agent.set_status(AgentStatus.VETERAN)

    def _init_bids_holland(
        self, active_agents: List[EconomicAgent], config: EngineConfig
    ) -> None:
        """Holland scheme: wealth-proportional bidding.

        - NOVICE: gets max(tycoon_bids) + epsilon, promoted to VETERAN.
        - VETERAN: promoted to TYCOON if wealth >= threshold, else base_bid.
        - TYCOON: bids holland_alpha * wealth.
        """
        tycoon_bids: List[float] = []
        for a in active_agents:
            if a.get_status() == AgentStatus.TYCOON:
                b = a.get_bid()
                if b is not None:
                    tycoon_bids.append(b)
        high_bid = max(tycoon_bids) if tycoon_bids else config.base_bid

        for agent in active_agents:
            status = agent.get_status()
            if status == AgentStatus.NOVICE:
                agent.set_bid(high_bid + config.novice_bid_epsilon)
                agent.set_status(AgentStatus.VETERAN)
            elif status == AgentStatus.VETERAN:
                if agent.wealth >= config.tycoon_wealth_threshold:
                    agent.set_status(AgentStatus.TYCOON)
                    agent.set_bid(config.holland_alpha * agent.wealth)
                else:
                    agent.set_bid(config.base_bid)
            elif status == AgentStatus.TYCOON:
                agent.set_bid(config.holland_alpha * agent.wealth)

    # ── Payment processing ─────────────────────────────────────────────

    def process_payment(
        self,
        winner: EconomicAgent,
        payment: float,
        prev_winner: Optional[EconomicAgent],
    ) -> None:
        """Process payment from winner to previous winner.

        First-price auction: winner pays their bid amount.
        Payment flows peer-to-peer to the previous auction winner.
        If there is no previous winner (first action), payment goes to void.

        Args:
            winner: The auction winner who must pay.
            payment: The payment amount (winner's bid).
            prev_winner: The previous auction winner (recipient), or None.
        """
        winner.lose_money(payment)
        if prev_winner is not None and prev_winner.id != winner.id:
            prev_winner.gain_money(payment)

    # ── Reward processing ───────────────────────────────────────────────

    def process_reward(
        self,
        winner: EconomicAgent,
        reward: float,
        chain_window: List[EconomicAgent],
        split_chain: bool,
        reward_config: RewardConfig,
    ) -> None:
        """Apply reward to winner (or split across chain window).

        When split_chain is True and reward is non-zero, the reward is
        distributed equally among unique members of the recent-winners
        chain window. Otherwise, the full reward goes to the winner.

        Args:
            winner: The agent that took the action.
            reward: The reward amount from the environment.
            chain_window: Rolling window of recent winners.
            split_chain: Whether to split reward across the chain window.
            reward_config: Reward configuration.
        """
        if split_chain and reward != 0:
            # Split step reward among unique members of the recent-winners window
            seen_ids = set()
            chain_uniq: List[EconomicAgent] = []
            for ag in chain_window:
                if ag.id in seen_ids:
                    continue
                seen_ids.add(ag.id)
                chain_uniq.append(ag)
            share = reward / len(chain_uniq)
            for ag in chain_uniq:
                ag.gain_money(share)
                ag.gain_capability(share)
        else:
            winner.gain_money(reward)
            winner.gain_capability(reward)
