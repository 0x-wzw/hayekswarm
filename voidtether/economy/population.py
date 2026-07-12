"""EconomicPopulation — manages the set of agents in the EoM economy.

Provides role-indexed lookups, wealth-based selection, and iteration
over the agent population.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, Iterator, List, Optional, Set, Any

from .agent import EconomicAgent


class EconomicPopulation:
    """Runtime population store for agents in the EoM economy.

    Maintains a fast lookup by agent ID and a secondary index by role
    for efficient role-based queries and parent selection.

    Thread-safe: uses a per-instance lock for all mutations.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Role -> set of agent IDs
        self.by_role: Dict[str, Set[int]] = {}

        # id -> agent instance
        self._agents: Dict[int, EconomicAgent] = {}

    # ── Mutation ──────────────────────────────────────────────────────

    def add_agent(self, agent: EconomicAgent) -> None:
        """Add an agent to the population and index it by role.

        Args:
            agent: The agent to add.
        """
        with self._lock:
            self._agents[agent.id] = agent
            role = agent.role
            if role not in self.by_role:
                self.by_role[role] = set()
            self.by_role[role].add(agent.id)

    def remove_agent(self, agent: EconomicAgent) -> None:
        """Remove an agent from the population and from its role set.

        Args:
            agent: The agent to remove.
        """
        with self._lock:
            self._agents.pop(agent.id, None)
            role = agent.role
            if role in self.by_role:
                self.by_role[role].discard(agent.id)
                if not self.by_role[role]:
                    del self.by_role[role]

    # ── Queries ────────────────────────────────────────────────────────

    def get_all(self) -> List[EconomicAgent]:
        """Return all agents as a list."""
        with self._lock:
            return list(self._agents.values())

    def get_by_role(self, role: str) -> List[EconomicAgent]:
        """Return all agents in the given role.

        Args:
            role: The role name to filter by.

        Returns:
            List of agents with the matching role.
        """
        with self._lock:
            ids = self.by_role.get(role, set())
            return [self._agents[aid] for aid in ids if aid in self._agents]

    def get_richest_agent(self) -> Optional[EconomicAgent]:
        """Return the currently richest living agent.

        Returns:
            The agent with the highest wealth, or None if population is empty.
        """
        with self._lock:
            agents = list(self._agents.values())
            if not agents:
                return None
            return max(agents, key=lambda a: a.wealth)

    def get_poorest_agent(self) -> Optional[EconomicAgent]:
        """Return the currently poorest living agent.

        Returns:
            The agent with the lowest wealth, or None if population is empty.
        """
        with self._lock:
            agents = list(self._agents.values())
            if not agents:
                return None
            return min(agents, key=lambda a: a.wealth)

    def get_best_agents(
        self,
        n: Optional[int] = None,
        *,
        key: Optional[Callable[[EconomicAgent], Any]] = None,
        role: Optional[str] = None,
    ) -> List[EconomicAgent]:
        """Return the best agents, optionally limited to a role and/or top n.

        Default sort key is wealth (highest first).

        Args:
            n: Maximum number of agents to return (None = all).
            key: Sort key function (default: wealth, descending).
            role: Optional role filter.

        Returns:
            Sorted list of agents (best first).
        """
        if key is None:
            key = lambda a: a.wealth
        with self._lock:
            if role is not None:
                # Inline the role filter — calling get_by_role() here would
                # re-acquire the non-reentrant lock and deadlock.
                ids = self.by_role.get(role, set())
                agents = [self._agents[aid] for aid in ids if aid in self._agents]
            else:
                agents = list(self._agents.values())
        sorted_agents = sorted(agents, key=key, reverse=True)
        if n is not None:
            sorted_agents = sorted_agents[:n]
        return sorted_agents

    def get_agent_ids(self) -> Set[int]:
        """Return the set of all agent IDs."""
        with self._lock:
            return set(self._agents.keys())

    def get_by_id(self, agent_id: int) -> Optional[EconomicAgent]:
        """Return an agent by its ID.

        Args:
            agent_id: The agent's unique identifier.

        Returns:
            The agent, or None if not found.
        """
        with self._lock:
            return self._agents.get(agent_id)

    # ── Container protocol ─────────────────────────────────────────────

    def __len__(self) -> int:
        """Return the current number of agents in the population."""
        with self._lock:
            return len(self._agents)

    def __iter__(self) -> Iterator[EconomicAgent]:
        """Iterate over all agents (order undefined)."""
        return iter(self.get_all())

    def __contains__(self, agent_id: int) -> bool:
        """Check if an agent ID is in the population."""
        with self._lock:
            return agent_id in self._agents
