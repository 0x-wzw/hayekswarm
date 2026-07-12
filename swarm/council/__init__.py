"""
HayekSwarm 10-D Council — Agent population for economic deliberation.

The Council manages 10 HayekMAS-compatible agents (D1-D10), each assigned
a specific model dimension. Agents bid in first-price auctions for tasks,
accumulate wealth from rewards, and undergo economic selection (good-birth
mutation and bad-birth replacement).

Exports:
    Council         — The 10-D council manager (auctions, selection, stats)
    CouncilAgent    — Wrapper for a council-registered agent
    DIMENSION_MAP   — Dimension-to-model mapping
    DIMENSION_ORDER — Ordered list of all 10 dimension keys
    BaseAgent       — HayekMAS-compatible base agent class
    AgentStatus     — NOVICE / VETERAN / TYCOON / BANKRUPT
    create_agent_for_dimension  — Factory function
    create_all_council_agents  — Create all 10 agents at once
"""

from .agents import (
    AGENT_CLASSES,
    AgentStatus,
    BaseAgent,
    SynthesisAgent,
    DeepReasonAgent,
    CodeAgent,
    VisionAgent,
    StrategyAgent,
    AnalysisAgent,
    GeneralAgent,
    VerificationAgent,
    ResearchAgent,
    ThinkAgent,
    create_agent_for_dimension,
    create_all_council_agents,
)
from .council import Council, CouncilAgent, AuctionResult
from .dimension_map import (
    DIMENSION_MAP,
    DIMENSION_FALLBACK,
    DIMENSION_LABELS,
    DIMENSION_ORDER,
    TIER_MAP,
    CAPABILITY_MAP,
    STAKES_ROUTING,
    get_model_for_dimension,
    get_fallbacks_for_dimension,
    get_tier_for_dimension,
    get_capabilities_for_dimension,
    get_dimensions_for_stakes,
    resolve_model,
)

__all__ = [
    # Council
    "Council",
    "CouncilAgent",
    "AuctionResult",
    # Agent classes
    "BaseAgent",
    "AgentStatus",
    "SynthesisAgent",
    "DeepReasonAgent",
    "CodeAgent",
    "VisionAgent",
    "StrategyAgent",
    "AnalysisAgent",
    "GeneralAgent",
    "VerificationAgent",
    "ResearchAgent",
    "ThinkAgent",
    "AGENT_CLASSES",
    # Factory
    "create_agent_for_dimension",
    "create_all_council_agents",
    # Dimension map
    "DIMENSION_MAP",
    "DIMENSION_FALLBACK",
    "DIMENSION_LABELS",
    "DIMENSION_ORDER",
    "TIER_MAP",
    "CAPABILITY_MAP",
    "STAKES_ROUTING",
    "get_model_for_dimension",
    "get_fallbacks_for_dimension",
    "get_tier_for_dimension",
    "get_capabilities_for_dimension",
    "get_dimensions_for_stakes",
    "resolve_model",
]
