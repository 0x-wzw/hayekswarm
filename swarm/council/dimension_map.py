"""
Dimension Map — D1-D10 configuration for the 10-D Council.

Each dimension maps to a specific Ollama Cloud model, with fallback chains,
tier classification, capability tags, and stakes-based routing preferences.

Model names sourced from the NecroSwarm cost_router (33 validated models)
and verified against Ollama Cloud availability.
"""

# ── Primary dimension-to-model mapping ──────────────────────────────────────
# Each dimension is assigned the best-fit model for its cognitive specialty.
DIMENSION_MAP = {
    "D1_synthesis": "kimi-k2.6:cloud",
    "D2_deep_reason": "deepseek-v4-flash:cloud",
    "D3_code": "qwen3-coder:480b:cloud",
    "D4_vision": "qwen3-vl:235b:cloud",
    "D5_strategy": "deepseek-v4-pro:cloud",
    "D6_analysis": "mistral-large-3:675b:cloud",
    "D7_general": "glm-5.1:cloud",
    "D8_verification": "nemotron-3-super:cloud",
    "D9_research": "minimax-m2.5:cloud",
    "D10_think": "kimi-k2.6:cloud",
}

# ── Fallback chains ─────────────────────────────────────────────────────────
# Ordered lists of fallback models for each dimension, tried in sequence
# when the primary model is unavailable, rate-limited, or times out.
DIMENSION_FALLBACK = {
    "D1_synthesis": [
        "deepseek-v4-flash:cloud",
        "glm-5.1:cloud",
        "minimax-m2.5:cloud",
    ],
    "D2_deep_reason": [
        "deepseek-v4-pro:cloud",
        "kimi-k2.6:cloud",
        "mistral-large-3:675b:cloud",
    ],
    "D3_code": [
        "qwen3-coder-next:cloud",
        "deepseek-v4-flash:cloud",
        "kimi-k2.6:cloud",
    ],
    "D4_vision": [
        "gemma3:27b:cloud",
        "kimi-k2.6:cloud",
        "deepseek-v4-flash:cloud",
    ],
    "D5_strategy": [
        "kimi-k2.6:cloud",
        "deepseek-v4-flash:cloud",
        "mistral-large-3:675b:cloud",
    ],
    "D6_analysis": [
        "deepseek-v4-flash:cloud",
        "kimi-k2.6:cloud",
        "glm-5.1:cloud",
    ],
    "D7_general": [
        "deepseek-v4-flash:cloud",
        "kimi-k2.6:cloud",
        "minimax-m2.5:cloud",
    ],
    "D8_verification": [
        "nemotron-3-nano:30b:cloud",
        "deepseek-v4-flash:cloud",
        "ministral-3:14b:cloud",
    ],
    "D9_research": [
        "deepseek-v4-flash:cloud",
        "kimi-k2.6:cloud",
        "qwen3.5:397b:cloud",
    ],
    "D10_think": [
        "deepseek-v4-flash:cloud",
        "glm-5.1:cloud",
        "minimax-m2.5:cloud",
    ],
}

# ── Tier classification ──────────────────────────────────────────────────────
# T1 = Flagship (largest, most capable)
# T2 = Workhorse (strong general-purpose)
# T3 = Lightweight (fast, cheap, good for simple tasks)
# Think = Reasoning-heavy (chain-of-thought, deep analysis)
TIER_MAP = {
    "D1_synthesis": "T1",
    "D2_deep_reason": "T1",
    "D3_code": "T1",
    "D4_vision": "T1",
    "D5_strategy": "T1",
    "D6_analysis": "T2",
    "D7_general": "T2",
    "D8_verification": "T3",
    "D9_research": "T2",
    "D10_think": "Think",
}

# ── Capability tags ─────────────────────────────────────────────────────────
# Each dimension lists the cognitive capabilities it can handle.
CAPABILITY_MAP = {
    "D1_synthesis": [
        "synthesis",
        "summarization",
        "integration",
        "cross-domain",
        "abstraction",
    ],
    "D2_deep_reason": [
        "deep_reasoning",
        "logical_deduction",
        "mathematical_proof",
        "causal_analysis",
        "philosophical_reasoning",
    ],
    "D3_code": [
        "code_generation",
        "code_review",
        "refactoring",
        "debugging",
        "architecture_design",
    ],
    "D4_vision": [
        "visual_understanding",
        "image_analysis",
        "diagram_interpretation",
        "multimodal_reasoning",
    ],
    "D5_strategy": [
        "strategic_planning",
        "decision_making",
        "risk_assessment",
        "resource_allocation",
        "game_theory",
    ],
    "D6_analysis": [
        "data_analysis",
        "statistical_reasoning",
        "trend_identification",
        "comparative_analysis",
        "root_cause_analysis",
    ],
    "D7_general": [
        "general_knowledge",
        "conversation",
        "explanation",
        "creative_writing",
        "factual_qa",
    ],
    "D8_verification": [
        "fact_checking",
        "validation",
        "testing",
        "audit",
        "consistency_checking",
    ],
    "D9_research": [
        "literature_review",
        "information_gathering",
        "evidence_synthesis",
        "hypothesis_generation",
        "deep_research",
    ],
    "D10_think": [
        "metacognition",
        "reflection",
        "self_correction",
        "chain_of_thought",
        "adversarial_reasoning",
    ],
}

# ── Stakes-based routing ────────────────────────────────────────────────────
# Maps task stakes levels to the dimensions best suited for each.
# Higher-stakes tasks engage more rigorous dimensions.
STAKES_ROUTING = {
    "low": [
        "D7_general",
        "D6_analysis",
    ],
    "medium": [
        "D7_general",
        "D6_analysis",
        "D3_code",
        "D9_research",
    ],
    "high": [
        "D1_synthesis",
        "D2_deep_reason",
        "D3_code",
        "D5_strategy",
        "D6_analysis",
        "D8_verification",
        "D9_research",
        "D10_think",
    ],
    "critical": [
        "D1_synthesis",
        "D2_deep_reason",
        "D3_code",
        "D4_vision",
        "D5_strategy",
        "D6_analysis",
        "D8_verification",
        "D9_research",
        "D10_think",
    ],
}

# ── Dimension metadata ──────────────────────────────────────────────────────
DIMENSION_LABELS = {
    "D1_synthesis": "Synthesis — Cross-domain integration and abstraction",
    "D2_deep_reason": "Deep Reason — Logical deduction and mathematical proof",
    "D3_code": "Code — Software engineering and architecture",
    "D4_vision": "Vision — Multimodal and visual understanding",
    "D5_strategy": "Strategy — Planning, risk, and decision theory",
    "D6_analysis": "Analysis — Data-driven and comparative analysis",
    "D7_general": "General — Broad knowledge and conversation",
    "D8_verification": "Verification — Fact-checking and validation",
    "D9_research": "Research — Deep investigation and evidence synthesis",
    "D10_think": "Think — Metacognition and adversarial reasoning",
}

DIMENSION_ORDER = [
    "D1_synthesis",
    "D2_deep_reason",
    "D3_code",
    "D4_vision",
    "D5_strategy",
    "D6_analysis",
    "D7_general",
    "D8_verification",
    "D9_research",
    "D10_think",
]


def get_model_for_dimension(dimension: str) -> str:
    """Return the primary model for a dimension key."""
    return DIMENSION_MAP.get(dimension, "deepseek-v4-flash:cloud")


def get_fallbacks_for_dimension(dimension: str) -> list[str]:
    """Return the fallback chain for a dimension key."""
    return DIMENSION_FALLBACK.get(dimension, ["deepseek-v4-flash:cloud"])


def get_tier_for_dimension(dimension: str) -> str:
    """Return the tier classification for a dimension."""
    return TIER_MAP.get(dimension, "T3")


def get_capabilities_for_dimension(dimension: str) -> list[str]:
    """Return the capability tags for a dimension."""
    return CAPABILITY_MAP.get(dimension, [])


def get_dimensions_for_stakes(stakes: str) -> list[str]:
    """Return the dimensions suited for a given stakes level."""
    return STAKES_ROUTING.get(stakes, STAKES_ROUTING["medium"])


def resolve_model(dimension: str, fallback_index: int = 0) -> str:
    """
    Resolve a model for a dimension, with fallback support.

    Args:
        dimension: The dimension key (e.g. "D3_code").
        fallback_index: 0 = primary, 1+ = fallback chain position.

    Returns:
        A model string (e.g. "qwen3-coder:480b:cloud").
    """
    if fallback_index == 0:
        return get_model_for_dimension(dimension)
    fallbacks = get_fallbacks_for_dimension(dimension)
    idx = min(fallback_index - 1, len(fallbacks) - 1)
    return fallbacks[idx]
