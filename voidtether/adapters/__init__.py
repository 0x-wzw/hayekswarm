"""VoidTether Protocol Adapters."""

from .a2a import A2AAdapter, a2a_card_to_manifest
from .mcp import MCPAdapter, mcp_tools_to_manifest
from .hermes import HermesAdapter, hermes_skills_to_manifest
from .openclaw import OpenClawAdapter, openclaw_skills_to_manifest
from .swarm import SwarmAdapter
from .crewai import CrewAIAdapter
from .langgraph import LangGraphAdapter
from .gbrain import GBrainAdapter, gbrain_skills_to_manifest
from .acp import ACPAdapter, acp_manifest_from_config
from .k2 import K2Adapter, k2_manifest_from_config
from .taste import TasteSkillAdapter, taste_manifest_from_config

ALL_ADAPTERS = {
    "a2a": A2AAdapter,
    "mcp": MCPAdapter,
    "hermes": HermesAdapter,
    "openclaw": OpenClawAdapter,
    "swarm": SwarmAdapter,
    "crewai": CrewAIAdapter,
    "langgraph": LangGraphAdapter,
    "gbrain": GBrainAdapter,
    "acp": ACPAdapter,
    "k2": K2Adapter,
    "taste": TasteSkillAdapter,
}
