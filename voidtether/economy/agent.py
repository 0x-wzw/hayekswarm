"""EconomicAgent — wraps a TetherManifest with economic state for the EoM engine.

Every agent in the economy is represented by an EconomicAgent that tracks
wealth, capability, bids, status, and lineage. The agent wraps a
TetherManifest for capability description and protocol routing.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Optional

from voidtether.core.manifest import TetherManifest


# Module-level counter for auto-incrementing agent IDs
_agent_id_counter = 0
_id_counter_lock = threading.Lock()


def _next_agent_id() -> int:
    """Thread-safe auto-incrementing agent ID."""
    global _agent_id_counter
    with _id_counter_lock:
        _agent_id_counter += 1
        return _agent_id_counter


def set_agent_id_counter(value: int) -> None:
    """Set the global agent ID counter to a specific value (for replay)."""
    global _agent_id_counter
    with _id_counter_lock:
        _agent_id_counter = value


class AgentStatus(Enum):
    """Lifecycle status for an agent in the EoM economy."""
    NOVICE = "novice"
    VETERAN = "veteran"
    TYCOON = "tycoon"


class EconomicAgent:
    """An agent in the EoM economy, wrapping a TetherManifest.

    Each agent carries economic state (wealth, capability, bid, status),
    lineage tracking (parent, spawn method), and a reference to its
    TetherManifest for capability description.

    Thread-safe: uses a per-instance lock for mutable state.

    Args:
        manifest: The TetherManifest describing this agent's capabilities.
        initial_wealth: Starting wealth for the agent.
        name: Optional override name (defaults to manifest.name).
    """

    def __init__(
        self,
        manifest: TetherManifest,
        initial_wealth: float = 0.5,
        name: str = "",
    ):
        self._lock = threading.Lock()

        self.id: int = _next_agent_id()
        self.name: str = name or manifest.name
        self.manifest: TetherManifest = manifest

        # Derive role from manifest name prefix or capabilities
        self.role: str = self._derive_role()

        # Economic state
        self.wealth: float = initial_wealth
        self.capability_score: float = 0.0
        self._bid: Optional[float] = None
        self._status: AgentStatus = AgentStatus.NOVICE

        # Agent tags from manifest metadata
        self.agent_tags: tuple[str, ...] = tuple(
            manifest.metadata.get("tags", [])
        )

        # Lineage tracking
        self.root_ancestor_class: str = manifest.origin_protocol.value
        self.parent_agent_id: Optional[int] = None
        self.spawn_method: str = "initial"
        self.tasks_lived: int = 0
        self.bankruptcy_episode: Optional[int] = None

        # Failure trace (recorded at bankruptcy)
        self._death_trace: str = ""
        self.recent_failure_trace: str = ""
        self.recent_failure_task: str = ""
        self.recent_failure_answer: str = ""

    def _derive_role(self) -> str:
        """Derive a role string from the manifest name or capabilities."""
        # Try to get role from manifest metadata
        role = self.manifest.metadata.get("role", "")
        if role:
            return role
        # Fall back to name prefix before first '-'
        name = self.manifest.name
        if "-" in name:
            return name.split("-")[0].lower()
        return name.lower()

    # ── Money management ──────────────────────────────────────────────

    def gain_money(self, amount: float) -> None:
        """Increase the agent's wealth.

        Args:
            amount: Wealth increment to add.
        """
        with self._lock:
            self.wealth += amount

    def lose_money(self, amount: float) -> None:
        """Decrease the agent's wealth.

        Args:
            amount: Wealth decrement to subtract.
        """
        with self._lock:
            self.wealth -= amount

    def gain_capability(self, amount: float) -> None:
        """Increase the agent's capability score.

        Args:
            amount: Capability increment to add.
        """
        with self._lock:
            self.capability_score += amount

    # ── Bid management ────────────────────────────────────────────────

    def get_bid(self) -> Optional[float]:
        """Return the agent's current bid value."""
        with self._lock:
            return self._bid

    def set_bid(self, value: Optional[float]) -> None:
        """Set the agent's bid value.

        Args:
            value: New bid value, or None if not yet assigned.
        """
        with self._lock:
            self._bid = value

    # ── Status management ─────────────────────────────────────────────

    def get_status(self) -> AgentStatus:
        """Return the agent's current lifecycle status."""
        with self._lock:
            return self._status

    def set_status(self, value: AgentStatus) -> None:
        """Set the agent's lifecycle status.

        Args:
            value: New status (NOVICE, VETERAN, or TYCOON).
        """
        with self._lock:
            self._status = value

    # ── Bankruptcy ────────────────────────────────────────────────────

    def check_bankruptcy(self) -> bool:
        """Return whether the agent is bankrupt (wealth < 0)."""
        with self._lock:
            return self.wealth < 0

    def record_death_trace(self, action_history: dict) -> None:
        """Record the episode trajectory at bankruptcy time.

        Builds a trace from the full action history with this agent's
        turns highlighted using >>> markers.

        Args:
            action_history: Dict mapping step numbers to action data dicts
                with 'author' and 'text' keys.
        """
        parts = []
        for step, action_data in sorted(action_history.items()):
            author = action_data.get("author", "")
            text = (action_data.get("text") or "").strip()
            if not text:
                continue
            if author == self.name:
                parts.append(f">>> [Step {step}] [{author}] {text}")
            else:
                parts.append(f"    [Step {step}] [{author}] {text}")
        self._death_trace = "\n\n".join(parts)

    def get_trace_recorded_at_death(self) -> str:
        """Return the trajectory recorded at bankruptcy time."""
        return self._death_trace

    def record_recent_failure(
        self,
        *,
        trace: str = "",
        task_description: str = "",
        correct_answer: str = "",
    ) -> None:
        """Store the latest failed-task context for bad-agent births."""
        self.recent_failure_trace = trace
        self.recent_failure_task = task_description
        self.recent_failure_answer = correct_answer

    # ── Initialization and snapshot ────────────────────────────────────

    def initialize(self, initial_wealth: float = 0.0) -> None:
        """Reset the agent to its initial state for entering the economy.

        Args:
            initial_wealth: Starting wealth to assign.
        """
        with self._lock:
            self.wealth = initial_wealth
            self.capability_score = 0.0
            self._status = AgentStatus.NOVICE
            self._bid = 0.0

    def snapshot(self) -> dict:
        """Capture mutable auction state for later restoration.

        Returns:
            A dictionary containing the mutable auction fields.
        """
        with self._lock:
            return {
                "wealth": self.wealth,
                "capability_score": self.capability_score,
                "bid": self._bid,
                "status": self._status,
            }

    def restore(self, snapshot: dict) -> None:
        """Restore mutable auction state from a saved snapshot.

        Args:
            snapshot: A dictionary previously returned by snapshot().
        """
        with self._lock:
            self.wealth = snapshot["wealth"]
            self.capability_score = snapshot["capability_score"]
            self._bid = snapshot["bid"]
            self._status = snapshot["status"]

    # ── Tag matching ─────────────────────────────────────────────────

    def has_any_tag(self, tags: set[str]) -> bool:
        """Return whether the agent has any tag in `tags`.

        Args:
            tags: Candidate tags to test.

        Returns:
            True when any tag overlaps with the agent's tags.
        """
        return bool(tags.intersection(self.agent_tags))

    # ── System prompt ─────────────────────────────────────────────────

    def get_system_prompt(self) -> str:
        """Return the combined system prompt for this agent.

        Combines the frozen prompt (from manifest metadata) with the
        trainable prompt (from manifest capabilities).

        Returns:
            Combined system prompt string.
        """
        frozen = self.manifest.metadata.get("frozen_system_prompt", "")
        trainable = self.manifest.metadata.get("trainable_system_prompt", "")
        if frozen:
            return frozen + "\n\n" + trainable
        return trainable

    # ── Representation ────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"EconomicAgent(id={self.id}, name={self.name!r}, "
            f"wealth={self.wealth:.2f}, status={self._status.value})"
        )
