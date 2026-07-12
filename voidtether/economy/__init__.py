"""VoidTether Economy of Minds (EoM) — core economic engine.

The EoM module implements a multi-agent economy where agents compete
via auctions for the right to act, exchange payments peer-to-peer,
and evolve through economic selection (bankruptcy -> birth).
"""

from .config import (
    EngineConfig,
    RewardConfig,
    EvolutionConfig,
    EconomyConfig,
)
from .agent import AgentStatus, EconomicAgent
from .population import EconomicPopulation
from .auction import Auctioneer
from .engine import EconomicEngine
from .router import EconomicRouter

__all__ = [
    "EngineConfig",
    "RewardConfig",
    "EvolutionConfig",
    "EconomyConfig",
    "AgentStatus",
    "EconomicAgent",
    "EconomicPopulation",
    "Auctioneer",
    "EconomicEngine",
    "EconomicRouter",
]
