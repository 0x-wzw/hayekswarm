"""Tether Router — capability-matched task routing across protocols."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .manifest import TetherManifest, Protocol, TaskState


@dataclass
class TetherTask:
    """A task being routed through the mesh."""
    task_id: str
    task_type: str
    input_data: dict[str, Any]
    source_agent: str                          # tether_id of the requesting agent
    source_protocol: Protocol
    target_protocol: Protocol | None = None    # None = any protocol
    state: TaskState = TaskState.SUBMITTED
    assigned_to: str | None = None             # tether_id of the assigned agent
    output_data: dict[str, Any] | None = None


class TetherRouter:
    """Routes tasks to the best available agent based on capability matching.
    
    The router maintains a registry of TetherManifests and performs
    capability-based matching: given a task type, find the agent(s)
    that can handle it, preferring agents that speak the same protocol
    as the requester (to minimize translation overhead).
    """
    
    def __init__(self):
        self._registry: dict[str, TetherManifest] = {}
    
    def register(self, manifest: TetherManifest) -> None:
        """Register an agent manifest with the router."""
        self._registry[manifest.tether_id] = manifest
    
    def unregister(self, tether_id: str) -> None:
        """Remove an agent from the mesh."""
        self._registry.pop(tether_id, None)
    
    def get(self, tether_id: str) -> TetherManifest | None:
        """Look up a specific agent."""
        return self._registry.get(tether_id)
    
    def list_agents(self) -> list[TetherManifest]:
        """List all registered agents."""
        return list(self._registry.values())
    
    def discover(self, task_type: str, protocol: Protocol | None = None) -> list[TetherManifest]:
        """Find agents that can handle a given task type.
        
        Args:
            task_type: The capability to search for.
            protocol: Optional protocol filter. If None, returns agents from any protocol.
        
        Returns:
            List of agents sorted by preference (same-protocol first, then by capability count).
        """
        candidates = []
        for manifest in self._registry.values():
            if not manifest.supports_task(task_type):
                continue
            if protocol and manifest.origin_protocol != protocol:
                candidates.append((manifest, 1))  # cross-protocol: lower priority
            else:
                candidates.append((manifest, 0))  # same-protocol: higher priority
        
        # Sort: same-protocol first, then by number of capabilities (more specialized first)
        candidates.sort(key=lambda x: (x[1], -len(x[0].capabilities.get("tasks", []))))
        return [c[0] for c in candidates]
    
    def route(self, task: TetherTask) -> TetherManifest | None:
        """Route a task to the best available agent.
        
        If the task specifies a target_protocol, only agents speaking that
        protocol are considered. Otherwise, same-protocol agents are preferred.
        """
        candidates = self.discover(task.task_type, protocol=task.target_protocol)
        if not candidates:
            # Fall back to any protocol
            candidates = self.discover(task.task_type)
        return candidates[0] if candidates else None
