"""Taste Skill Adapter — Anti-slop frontend design skill for AI agents.

Bridges the Taste-Skill design system (https://github.com/leonxlnx/taste-skill)
into the VoidTether mesh. Provides structured design rules, the Three Dials
system (DESIGN_VARIANCE, MOTION_INTENSITY, VISUAL_DENSITY), and design read
inference for every UI task.

Key mappings:
  Taste Design Read  -> Tether capability (task type + design inference)
  Three Dials        -> Structured input parameters
  Skill Presets      -> Pre-configured dial configurations per use case
  Design Audit       -> Quality gate for anti-slop enforcement
"""

from __future__ import annotations
import json
from typing import Any
from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


# ── The Three Dials (defaults and ranges) ─────────────────────────────

DIAL_DEFAULTS = {
    "design_variance": 8,      # 1 = Perfect Symmetry, 10 = Artsy Chaos
    "motion_intensity": 6,     # 1 = Static, 10 = Cinematic / Physics
    "visual_density": 4,       # 1 = Art Gallery / Airy, 10 = Cockpit / Packed Data
}

DIAL_RANGES = {
    "design_variance": (1, 10),
    "motion_intensity": (1, 10),
    "visual_density": (1, 10),
}

# ── Use-Case Presets ──────────────────────────────────────────────────

USE_CASE_PRESETS = {
    "landing_saas":        {"design_variance": 7, "motion_intensity": 6, "visual_density": 4, "vibe": "mainstream SaaS, clean conversions"},
    "landing_agency":      {"design_variance": 9, "motion_intensity": 8, "visual_density": 3, "vibe": "creative studio, artsy, experimental"},
    "landing_premium":     {"design_variance": 7, "motion_intensity": 6, "visual_density": 3, "vibe": "premium consumer, Apple-y, luxury"},
    "portfolio_designer":  {"design_variance": 8, "motion_intensity": 7, "visual_density": 3, "vibe": "designer studio, editorial, kinetic"},
    "portfolio_dev":       {"design_variance": 6, "motion_intensity": 5, "visual_density": 4, "vibe": "developer portfolio, clean, technical"},
    "editorial_blog":      {"design_variance": 6, "motion_intensity": 4, "visual_density": 3, "vibe": "editorial, typography-forward, calm"},
    "public_sector":       {"design_variance": 3, "motion_intensity": 2, "visual_density": 5, "vibe": "trust-first, accessible, regulated"},
    "redesign_preserve":   {"design_variance": 0, "motion_intensity": 1, "visual_density": 0, "vibe": "preserve existing, gentle refresh"},
    "redesign_overhaul":   {"design_variance": 2, "motion_intensity": 2, "visual_density": 0, "vibe": "full visual overhaul, modernize"},
}

# ── Vibe Signal Mapping ───────────────────────────────────────────────

VIBE_SIGNALS = {
    "minimalist":    {"design_variance": 5, "motion_intensity": 3, "visual_density": 2},
    "calm":          {"design_variance": 5, "motion_intensity": 3, "visual_density": 3},
    "apple":         {"design_variance": 7, "motion_intensity": 6, "visual_density": 3},
    "premium":       {"design_variance": 7, "motion_intensity": 6, "visual_density": 3},
    "playful":       {"design_variance": 9, "motion_intensity": 8, "visual_density": 4},
    "experimental":  {"design_variance": 10, "motion_intensity": 9, "visual_density": 3},
    "editorial":     {"design_variance": 6, "motion_intensity": 4, "visual_density": 3},
    "trust":         {"design_variance": 3, "motion_intensity": 2, "visual_density": 5},
    "linear":        {"design_variance": 5, "motion_intensity": 3, "visual_density": 2},
    "brutalist":     {"design_variance": 9, "motion_intensity": 5, "visual_density": 5},
    "glassy":        {"design_variance": 7, "motion_intensity": 6, "visual_density": 3},
}

# ── Anti-Slop Rules ───────────────────────────────────────────────────

ANTI_SLOP_RULES = [
    "No AI-purple gradients as default",
    "No centered hero over dark mesh pattern",
    "No three equal feature cards layout",
    "No generic glassmorphism on everything",
    "No infinite-loop micro-animations everywhere",
    "No Inter + slate-900 as default type/color",
    "No stock illustrations without purpose",
    "No generic gradient buttons",
    "No auto-playing carousels",
    "No placeholder lorem ipsum",
]


class TasteSkillAdapter(BaseAdapter):
    """Adapter for the Taste-Skill — anti-slop frontend design rules.

    This adapter translates design tasks into structured design reads
    with the Three Dials system. It can be invoked by any agent in the
    mesh to audit, review, or generate UI with taste.

    Key methods:
      - design_read(brief) → structured design direction
      - audit_ui(code_or_spec) → anti-slop audit report
      - dials_for_vibe(vibe_words) → dial recommendations
      - preset_for_case(use_case) → preset dial configuration
    """

    protocol = Protocol.TASTE  # Registers as "taste" protocol

    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert taste-skill output to VoidTether format."""
        return {
            "text": data.get("read", data.get("output", str(data))),
            "metadata": {
                "skill": "taste",
                "dials": data.get("dials", {}),
                "use_case": data.get("use_case", "custom"),
                "audit_issues": data.get("audit_issues", []),
            },
        }

    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Pass through — input data from delegation is already in the right format."""
        return data

    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a taste-skill task.

        Supported task types:
          - design_read: Analyze a brief and produce design direction
          - audit_ui: Review code/spec for anti-slop compliance
          - dials_from_vibe: Map vibe words to Three Dials
          - preset: Get preset dials for a use case
          - generate_ui: Generate UI code with taste rules applied
        """
        brief = input_data.get("brief", "")
        vibe = input_data.get("vibe", "")
        use_case = input_data.get("use_case", "landing_saas")
        code = input_data.get("code", "")

        if task_type == "design_read":
            return self._design_read(brief, vibe)
        elif task_type == "audit_ui":
            return self._audit_ui(code)
        elif task_type == "dials_from_vibe":
            return self._dials_from_vibe(vibe)
        elif task_type == "preset":
            return self._get_preset(use_case)
        elif task_type == "generate_ui":
            return self._generate_with_taste(brief, vibe, use_case)
        else:
            return {"text": f"Unknown taste task: '{task_type}'", "error": True}

    # ── Core Taste Methods ─────────────────────────────────────────────

    def _design_read(self, brief: str, vibe: str = "") -> dict[str, Any]:
        """Produce a structured design read from a brief.

        Returns the design direction with Three Dials set.
        """
        dials = self._dials_from_vibe(vibe) if vibe else dict(DIAL_DEFAULTS)

        # Infer page kind and audience from brief keywords
        brief_lower = brief.lower()
        page_kind = "landing"
        audience = "general"
        if "portfolio" in brief_lower or "folio" in brief_lower:
            page_kind = "portfolio"
            audience = "hiring managers"
        elif "blog" in brief_lower or "editorial" in brief_lower:
            page_kind = "editorial"
            audience = "readers"
        elif "saas" in brief_lower or "product" in brief_lower or "app" in brief_lower:
            page_kind = "SaaS"
            audience = "technical buyers"
        elif "agency" in brief_lower or "studio" in brief_lower:
            page_kind = "agency"
            audience = "clients"
        elif "public" in brief_lower or "gov" in brief_lower or "service" in brief_lower:
            page_kind = "public-sector"
            audience = "citizens"

        design_read = f"Reading this as: {page_kind} for {audience}"
        if vibe:
            design_read += f", with a {vibe} language"

        # Anti-slop defaults check
        defaults_triggered = []
        for rule in ANTI_SLOP_RULES:
            if any(word in brief_lower for word in rule.lower().split()[:3]):
                defaults_triggered.append(rule)

        return {
            "read": design_read,
            "dials": dials,
            "page_kind": page_kind,
            "audience": audience,
            "vibe": vibe or "inferred",
            "defaults_avoided": defaults_triggered,
            "status": "design_read_complete",
        }

    def _audit_ui(self, code: str) -> dict[str, Any]:
        """Audit UI code or spec for anti-slop compliance.

        Checks against the anti-slop rules and returns issues found.
        """
        issues = []
        code_lower = code.lower()

        # Scan for anti-patterns
        if "purple" in code_lower and "gradient" in code_lower:
            issues.append("AI-purple gradient detected — replace with intentional brand color")
        if "dark" in code_lower and "mesh" in code_lower:
            issues.append("Dark mesh background detected — overused LLM default")
        if "glass" in code_lower and any(w in code_lower for w in ["backdrop", "blur"]):
            issues.append("Glassmorphism detected — use sparingly, only if design read calls for it")
        if "inter" in code_lower and "slate" in code_lower:
            issues.append("Inter + slate detected — generic LLM default type/color pairing")
        if "animate-spin" in code_lower or "infinite" in code_lower:
            issues.append("Infinite animation detected — use purposeful motion only")
        if "lorem" in code_lower:
            issues.append("Lorem ipsum detected — use real or realistic content")

        return {
            "audit_issues": issues,
            "pass": len(issues) == 0,
            "total_checks": len(ANTI_SLOP_RULES),
            "issues_found": len(issues),
            "status": "audit_complete",
        }

    def _dials_from_vibe(self, vibe: str) -> dict[str, int]:
        """Map vibe words to Three Dials values.

        Handles compound vibes like "premium-minimalist" by averaging.
        """
        vibe_lower = vibe.lower().replace("-", " ").replace("_", " ")
        words = vibe_lower.split()

        # Check for exact matches first
        if vibe_lower in VIBE_SIGNALS:
            return dict(VIBE_SIGNALS[vibe_lower])

        # Check for compound vibes
        matched = []
        for word in words:
            if word in VIBE_SIGNALS:
                matched.append(VIBE_SIGNALS[word])

        if matched:
            return {
                "design_variance": sum(m["design_variance"] for m in matched) // len(matched),
                "motion_intensity": sum(m["motion_intensity"] for m in matched) // len(matched),
                "visual_density": sum(m["visual_density"] for m in matched) // len(matched),
            }

        return dict(DIAL_DEFAULTS)

    def _get_preset(self, use_case: str) -> dict[str, Any]:
        """Get preset dials for a use case."""
        preset = USE_CASE_PRESETS.get(use_case, USE_CASE_PRESETS["landing_saas"])
        return {
            "dials": {
                "design_variance": preset["design_variance"],
                "motion_intensity": preset["motion_intensity"],
                "visual_density": preset["visual_density"],
            },
            "vibe": preset["vibe"],
            "use_case": use_case,
            "status": "preset_loaded",
        }

    def _generate_with_taste(self, brief: str, vibe: str = "", use_case: str = "") -> dict[str, Any]:
        """Generate UI design direction with taste rules applied.

        Produces a structured design brief that an agent can implement,
        with Three Dials, anti-slop guardrails, and design read.
        """
        # Get design read first
        design = self._design_read(brief, vibe)

        # Get preset if use_case specified
        preset = self._get_preset(use_case) if use_case else None
        dials = preset["dials"] if preset else design["dials"]

        return {
            "read": design["read"],
            "dials": dials,
            "page_kind": design["page_kind"],
            "audience": design["audience"],
            "use_case": use_case or design["page_kind"],
            "anti_slop_guardrails": ANTI_SLOP_RULES[:5],  # Top 5 rules as quick reference
            "status": "taste_brief_ready",
        }


# ── Agent Manifest Factory ────────────────────────────────────────────

def taste_manifest_from_config(
    name: str = "Taste Designer",
    tether_id: str | None = None,
) -> TetherManifest:
    """Create a TetherManifest for a taste-skill design agent.

    The taste designer can audit, review, and guide UI generation
    using the anti-slop design rules from leonxlnx/taste-skill.
    """
    tid = tether_id or "taste-designer"
    return TetherManifest(
        tether_id=tid,
        name=name,
        origin_protocol=Protocol.CUSTOM,
        capabilities={
            "tasks": [
                "design_read",
                "audit_ui",
                "dials_from_vibe",
                "preset",
                "generate_ui",
                "taste_review",
                "anti_slop_check",
            ],
            "modalities": ["text", "structured_output", "design_spec"],
            "streaming": False,
            "design_system": "taste-skill v2",
            "three_dials": DIAL_DEFAULTS,
            "anti_slop_rules": len(ANTI_SLOP_RULES),
            "presets": list(USE_CASE_PRESETS.keys()),
            "source_repo": "https://github.com/leonxlnx/taste-skill",
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.CUSTOM,
            config={"framework": "taste-skill", "version": "2.0.0"},
        )],
        metadata={
            "framework": "taste-skill",
            "version": "2.0.0",
            "description": "Anti-slop frontend design skill — Three Dials system, design read inference, UI audit",
            "author": "Leonxlnx",
            "repo": "https://github.com/leonxlnx/taste-skill",
            "stars": "60k+",
        },
    )
