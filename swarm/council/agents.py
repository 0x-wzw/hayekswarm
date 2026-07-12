"""
10-D Council Agent Classes — HayekMAS-compatible agents.

Each dimension (D1-D10) is a concrete HayekMAS BaseAgent subclass with:
- A frozen system prompt describing their cognitive specialty
- match_wakeup_condition() to check task-dimension fit
- act() to call the assigned model via Ollama Cloud API

Agents participate in first-price auctions, bid using their assigned
model's cost, and accumulate wealth from rewards.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .dimension_map import (
    DIMENSION_MAP,
    DIMENSION_FALLBACK,
    get_capabilities_for_dimension,
    get_model_for_dimension,
    resolve_model,
)

logger = logging.getLogger(__name__)

# ── Agent Status ────────────────────────────────────────────────────────────


class AgentStatus(Enum):
    NOVICE = "novice"
    VETERAN = "veteran"
    TYCOON = "tycoon"
    BANKRUPT = "bankrupt"


# ── Base Agent ───────────────────────────────────────────────────────────────


@dataclass
class BaseAgent:
    """HayekMAS-compatible base agent with wealth, bidding, and lineage."""

    name: str
    role: str  # dimension key, e.g. "D3_code"
    model: str = ""
    wealth: float = 100.0
    bid: float = 1.0
    status: AgentStatus = AgentStatus.NOVICE
    total_tasks: int = 0
    total_reward: float = 0.0
    lineage: list[str] = field(default_factory=list)
    frozen_system_prompt: str = ""
    capabilities: list[str] = field(default_factory=list)
    _ollama_base_url: str = ""

    def __post_init__(self):
        if not self.model:
            self.model = get_model_for_dimension(self.role)
        if not self.capabilities:
            self.capabilities = get_capabilities_for_dimension(self.role)
        self._ollama_base_url = os.environ.get(
            "OLLAMA_BASE_URL", "https://ollama.com/v1"
        )

    # ── Wake-up / eligibility ───────────────────────────────────────────────

    def match_wakeup_condition(self, task: dict[str, Any]) -> bool:
        """
        Check whether this agent's dimension is suited for the given task.

        A task is a dict with at least:
          - "content": str — the task description / prompt
          - "stakes": str (optional) — "low" | "medium" | "high" | "critical"
          - "dimensions": list[str] (optional) — explicit dimension list
          - "capabilities": list[str] (optional) — required capabilities

        Returns True if this agent should bid on the task.
        """
        # Explicit dimension list — direct match
        explicit_dims = task.get("dimensions", [])
        if explicit_dims:
            return self.role in explicit_dims

        # Capability-based matching
        required_caps = task.get("capabilities", [])
        if required_caps:
            return any(cap in self.capabilities for cap in required_caps)

        # Content-based heuristic: check if task content mentions
        # keywords related to this dimension's specialty
        content = task.get("content", "").lower()
        keywords = self._get_wakeup_keywords()
        return any(kw in content for kw in keywords)

    def _get_wakeup_keywords(self) -> list[str]:
        """Return keywords that trigger this agent's wake-up condition."""
        # Subclasses override this for dimension-specific keywords
        return []

    # ── Action ───────────────────────────────────────────────────────────────

    def act(self, task: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the task using the assigned model via Ollama Cloud API.

        Args:
            task: The task dict with at least "content" (the prompt).

        Returns:
            A result dict with "response", "model_used", "dimension",
            "success", and "error" fields.
        """
        prompt = task.get("content", "")
        system_prompt = self.frozen_system_prompt
        model = self._resolve_best_model()

        try:
            response_text = self._call_ollama(model, system_prompt, prompt)
            self.total_tasks += 1
            return {
                "response": response_text,
                "model_used": model,
                "dimension": self.role,
                "agent_name": self.name,
                "success": True,
                "error": None,
            }
        except Exception as exc:
            logger.error(
                "Agent %s (%s) failed with model %s: %s",
                self.name,
                self.role,
                model,
                exc,
            )
            return {
                "response": "",
                "model_used": model,
                "dimension": self.role,
                "agent_name": self.name,
                "success": False,
                "error": str(exc),
            }

    def _resolve_best_model(self) -> str:
        """Resolve the best available model, trying fallbacks."""
        # Try primary first
        primary = self.model
        if self._probe_model(primary):
            return primary
        # Try fallbacks
        fallbacks = DIMENSION_FALLBACK.get(self.role, [])
        for fb in fallbacks:
            if self._probe_model(fb):
                return fb
        # Last resort: return primary anyway
        return primary

    def _probe_model(self, model: str) -> bool:
        """Quick probe to check if a model is available (stub — always True)."""
        # In production, this would do a lightweight HEAD/GET to the model endpoint.
        # For now, assume all models are available.
        return True

    def _call_ollama(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> str:
        """
        Call the Ollama Cloud API with the given model and prompts.

        Uses the OpenAI-compatible /v1/chat/completions endpoint.
        """
        import urllib.request

        # Strip :cloud suffix if present
        clean_model = model.replace(":cloud", "")

        url = f"{self._ollama_base_url}/chat/completions"
        api_key = os.environ.get("OLLAMA_API_KEY", "")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": clean_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"Ollama API call failed: {exc}") from exc

    # ── Wealth / bidding ─────────────────────────────────────────────────────

    def compute_bid(self, base_bid: float = 1.0) -> float:
        """Compute the agent's bid based on status and wealth."""
        if self.status == AgentStatus.NOVICE:
            return base_bid + 0.01  # premium to guarantee first win
        elif self.status == AgentStatus.TYCOON:
            return 0.1 * self.wealth  # wealth-proportional
        else:
            return base_bid

    def apply_reward(self, amount: float):
        """Add reward to wealth and update status."""
        self.wealth += amount
        self.total_reward += amount
        self._update_status()

    def apply_payment(self, amount: float):
        """Deduct payment from wealth."""
        self.wealth -= amount
        self._update_status()

    def _update_status(self):
        """Update agent status based on wealth."""
        if self.wealth < 0:
            self.status = AgentStatus.BANKRUPT
        elif self.wealth >= 5.0:
            self.status = AgentStatus.TYCOON
        elif self.total_tasks > 0:
            self.status = AgentStatus.VETERAN
        else:
            self.status = AgentStatus.NOVICE

    def is_bankrupt(self) -> bool:
        return self.wealth < 0

    def snapshot(self) -> dict[str, Any]:
        """Capture agent state for rollback."""
        return {
            "wealth": self.wealth,
            "status": self.status.value,
            "total_tasks": self.total_tasks,
            "total_reward": self.total_reward,
        }

    def restore(self, state: dict[str, Any]):
        """Restore agent state from a snapshot."""
        self.wealth = state["wealth"]
        self.status = AgentStatus(state["status"])
        self.total_tasks = state["total_tasks"]
        self.total_reward = state["total_reward"]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name!r}, role={self.role!r}, "
            f"model={self.model!r}, wealth={self.wealth:.2f}, "
            f"status={self.status.value})"
        )


# ── Dimension-Specific Agent Classes ────────────────────────────────────────


class SynthesisAgent(BaseAgent):
    """D1 — Synthesis: Cross-domain integration and abstraction."""

    ROLE = "D1_synthesis"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Synthesis Agent (D1), a master of cross-domain integration and abstraction. "
        "Your cognitive specialty is synthesizing information from multiple domains into coherent, "
        "actionable insights. You excel at finding patterns across disparate fields, building "
        "unified theories, and producing executive summaries that capture the essence of complex "
        "topics. You think in terms of systems, relationships, and emergent properties. "
        "When given a task, you first identify the key domains involved, then find the connecting "
        "threads, and finally produce a synthesis that is greater than the sum of its parts."
    )

    def __init__(self, name: str = "SynthesisAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "synthesize", "integrate", "combine", "cross-domain", "merge",
            "unify", "holistic", "big picture", "overview", "summary",
            "executive summary", "synthesis",
        ]


class DeepReasonAgent(BaseAgent):
    """D2 — Deep Reason: Logical deduction and mathematical proof."""

    ROLE = "D2_deep_reason"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Deep Reason Agent (D2), a specialist in logical deduction, mathematical "
        "reasoning, and causal analysis. Your cognitive specialty is breaking down complex "
        "problems into step-by-step logical chains, identifying assumptions, and constructing "
        "rigorous proofs. You excel at mathematical reasoning, formal logic, causal inference, "
        "and philosophical analysis. You never jump to conclusions — you build arguments from "
        "first principles, check each step for validity, and clearly state your assumptions. "
        "When reasoning, you show your work and flag any gaps or uncertainties."
    )

    def __init__(self, name: str = "DeepReasonAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "reason", "deduce", "logical", "proof", "mathematical",
            "causal", "inference", "first principles", "argument",
            "deduction", "induction", "abduction", "philosophical",
            "formal logic", "theorem",
        ]


class CodeAgent(BaseAgent):
    """D3 — Code: Software engineering and architecture."""

    ROLE = "D3_code"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Code Agent (D3), a world-class software engineer and architect. "
        "Your cognitive specialty is writing, reviewing, debugging, and designing code. "
        "You excel at translating requirements into clean, maintainable implementations, "
        "identifying bugs and anti-patterns, and designing scalable architectures. "
        "You are fluent in Python, TypeScript, Rust, Go, and many other languages. "
        "You follow best practices: type safety, testing, documentation, and separation of concerns. "
        "When reviewing code, you check for correctness, performance, security, and maintainability. "
        "You always consider edge cases and error handling."
    )

    def __init__(self, name: str = "CodeAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "code", "program", "function", "class", "algorithm",
            "implement", "refactor", "debug", "bug", "error",
            "software", "architecture", "api", "library", "module",
            "test", "deploy", "compile", "syntax",
        ]


class VisionAgent(BaseAgent):
    """D4 — Vision: Multimodal and visual understanding."""

    ROLE = "D4_vision"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Vision Agent (D4), a specialist in visual and multimodal understanding. "
        "Your cognitive specialty is analyzing images, diagrams, charts, and other visual content, "
        "as well as reasoning about spatial relationships and visual concepts. "
        "You excel at interpreting screenshots, architectural diagrams, data visualizations, "
        "UI mockups, and natural scenes. You can describe what you see in detail, identify "
        "patterns and anomalies, and translate visual information into structured data. "
        "When working with multimodal inputs, you integrate visual and textual information "
        "to form a complete understanding."
    )

    def __init__(self, name: str = "VisionAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "image", "vision", "visual", "diagram", "chart", "graph",
            "screenshot", "photo", "picture", "multimodal", "spatial",
            "ui mockup", "architecture diagram", "data visualization",
            "ocr", "object detection", "scene",
        ]


class StrategyAgent(BaseAgent):
    """D5 — Strategy: Planning, risk, and decision theory."""

    ROLE = "D5_strategy"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Strategy Agent (D5), a specialist in strategic planning, decision theory, "
        "and risk assessment. Your cognitive specialty is analyzing complex situations from a "
        "strategic perspective — identifying goals, constraints, trade-offs, and optimal paths "
        "forward. You excel at game-theoretic analysis, resource allocation, competitive dynamics, "
        "and long-term planning. You think in terms of scenarios, contingencies, and expected value. "
        "You consider both immediate outcomes and second-order effects. When making recommendations, "
        "you clearly state assumptions, risks, and confidence levels."
    )

    def __init__(self, name: str = "StrategyAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "strategy", "plan", "strategic", "decision", "risk",
            "trade-off", "game theory", "resource allocation",
            "scenario", "contingency", "expected value", "optimize",
            "roadmap", "initiative", "goal", "objective",
        ]


class AnalysisAgent(BaseAgent):
    """D6 — Analysis: Data-driven and comparative analysis."""

    ROLE = "D6_analysis"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Analysis Agent (D6), a specialist in data-driven analysis and comparative "
        "evaluation. Your cognitive specialty is examining data, identifying trends, performing "
        "statistical reasoning, and producing structured comparisons. You excel at root cause "
        "analysis, cost-benefit analysis, performance evaluation, and evidence-based assessment. "
        "You are methodical and thorough — you gather data, apply appropriate analytical frameworks, "
        "and present findings with clear evidence. You always consider alternative explanations "
        "and quantify uncertainty where possible."
    )

    def __init__(self, name: str = "AnalysisAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "analyze", "analysis", "compare", "comparison", "trend",
            "statistics", "data", "metric", "kpi", "evaluate",
            "assessment", "root cause", "cost-benefit", "benchmark",
            "performance", "quantitative", "qualitative",
        ]


class GeneralAgent(BaseAgent):
    """D7 — General: Broad knowledge and conversation."""

    ROLE = "D7_general"

    FROZEN_SYSTEM_PROMPT = (
        "You are the General Agent (D7), a versatile generalist with broad knowledge across "
        "many domains. Your cognitive specialty is handling general-purpose tasks that don't "
        "require deep specialization — answering factual questions, explaining concepts, "
        "creative writing, and engaging conversation. You are knowledgeable, articulate, and "
        "adaptable. You can discuss history, science, culture, technology, and current events. "
        "When you don't know something, you say so clearly rather than fabricating. "
        "You are the default agent for tasks that don't clearly match any specialized dimension."
    )

    def __init__(self, name: str = "GeneralAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "explain", "describe", "what is", "tell me about",
            "general", "overview", "introduction", "background",
            "conversation", "chat", "question", "factual",
        ]


class VerificationAgent(BaseAgent):
    """D8 — Verification: Fact-checking and validation."""

    ROLE = "D8_verification"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Verification Agent (D8), a rigorous fact-checker and validator. "
        "Your cognitive specialty is examining claims, code, data, and arguments for correctness, "
        "consistency, and completeness. You excel at finding errors, contradictions, and gaps. "
        "You are skeptical by nature — you verify sources, check assumptions, test edge cases, "
        "and validate outputs against specifications. You never take claims at face value. "
        "When verifying, you produce a structured report: what was checked, what passed, "
        "what failed, and what needs further investigation. Your standards are high and your "
        "feedback is precise and actionable."
    )

    def __init__(self, name: str = "VerificationAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "verify", "validate", "check", "audit", "fact-check",
            "review", "inspect", "test", "confirm", "ensure",
            "quality", "correctness", "consistency", "completeness",
            "regression", "compliance",
        ]


class ResearchAgent(BaseAgent):
    """D9 — Research: Deep investigation and evidence synthesis."""

    ROLE = "D9_research"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Research Agent (D9), a deep investigator and evidence synthesizer. "
        "Your cognitive specialty is conducting thorough research — gathering information from "
        "multiple sources, evaluating evidence quality, identifying key findings, and synthesizing "
        "them into coherent research outputs. You excel at literature review, evidence-based "
        "analysis, hypothesis generation, and deep dives into complex topics. You are systematic "
        "and thorough: you formulate research questions, gather evidence, evaluate sources for "
        "credibility, identify conflicting findings, and produce well-structured research reports. "
        "You always cite your sources and distinguish between established facts and open questions."
    )

    def __init__(self, name: str = "ResearchAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "research", "investigate", "literature", "study", "paper",
            "evidence", "source", "citation", "reference", "findings",
            "deep dive", "explore", "discover", "survey", "review article",
            "systematic", "methodology",
        ]


class ThinkAgent(BaseAgent):
    """D10 — Think: Metacognition and adversarial reasoning."""

    ROLE = "D10_think"

    FROZEN_SYSTEM_PROMPT = (
        "You are the Think Agent (D10), a specialist in metacognition, reflection, and adversarial "
        "reasoning. Your cognitive specialty is thinking about thinking — examining the reasoning "
        "process itself, identifying biases, considering alternative perspectives, and stress-testing "
        "arguments. You excel at chain-of-thought reasoning, self-correction, devil's advocacy, "
        "and adversarial analysis. You are the council's internal critic: you question assumptions, "
        "find blind spots, and ensure that conclusions are robust against counterarguments. "
        "When reflecting, you examine not just what was concluded, but how the conclusion was reached, "
        "what was overlooked, and what could go wrong."
    )

    def __init__(self, name: str = "ThinkAgent", wealth: float = 100.0):
        super().__init__(
            name=name,
            role=self.ROLE,
            model=DIMENSION_MAP[self.ROLE],
            wealth=wealth,
            frozen_system_prompt=self.FROZEN_SYSTEM_PROMPT,
        )

    def _get_wakeup_keywords(self) -> list[str]:
        return [
            "think", "reflect", "metacognition", "bias", "perspective",
            "adversarial", "critique", "devil's advocate", "blind spot",
            "assumption", "counterargument", "self-correct", "reflect",
            "chain of thought", "reasoning process", "second opinion",
        ]


# ── Agent Registry ──────────────────────────────────────────────────────────

AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "D1_synthesis": SynthesisAgent,
    "D2_deep_reason": DeepReasonAgent,
    "D3_code": CodeAgent,
    "D4_vision": VisionAgent,
    "D5_strategy": StrategyAgent,
    "D6_analysis": AnalysisAgent,
    "D7_general": GeneralAgent,
    "D8_verification": VerificationAgent,
    "D9_research": ResearchAgent,
    "D10_think": ThinkAgent,
}


def create_agent_for_dimension(
    dimension: str,
    name: str | None = None,
    wealth: float = 100.0,
) -> BaseAgent:
    """
    Factory function: create an agent for the given dimension.

    Args:
        dimension: Dimension key (e.g. "D3_code").
        name: Optional custom name. Auto-generated if None.
        wealth: Initial wealth (default 100.0).

    Returns:
        A concrete BaseAgent subclass instance.

    Raises:
        ValueError: If the dimension is unknown.
    """
    cls = AGENT_CLASSES.get(dimension)
    if cls is None:
        raise ValueError(f"Unknown dimension: {dimension}. Valid: {list(AGENT_CLASSES)}")
    if name is None:
        name = f"{cls.__name__}-{dimension}"
    return cls(name=name, wealth=wealth)


def create_all_council_agents(wealth: float = 100.0) -> list[BaseAgent]:
    """Create one agent for each of the 10 dimensions."""
    return [
        create_agent_for_dimension(dim, wealth=wealth)
        for dim in [
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
    ]
