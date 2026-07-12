"""Mesh — the high-level API for the VoidTether agent mesh."""

from __future__ import annotations
from typing import Any
from voidtether.core import (
    TetherManifest, Protocol, TaskState,
    TetherRouter, TetherTask,
    ProtocolBridge,
)
from voidtether.adapters import ALL_ADAPTERS
from voidtether.economy import EconomicRouter, EconomicEngine, EconomyConfig, EngineConfig, RewardConfig, EvolutionConfig


class Mesh:
    """The main VoidTether mesh interface.

    Uses EconomicRouter for auction-based task allocation with
    wealth tracking. Falls back to capability-based routing when
    mode is set to "capability".

    Usage:
        mesh = Mesh()
        mesh.register(my_manifest)
        agent = mesh.discover("code_review")
        result = mesh.delegate(agent, task="review", input={"code": "..."})
    """

    def __init__(self, mode: str = "economic"):
        self.engine = EconomicEngine(
            config=EconomyConfig(
                engine=EngineConfig(initial_wealth=100.0, base_bid=1.0),
                reward=RewardConfig(),
                evolution=EvolutionConfig(),
            )
        )
        self.router = EconomicRouter(self.engine)
        self.router.mode = mode
        self.bridge = ProtocolBridge(self.router)
        self._adapters = {}

        # Auto-register all built-in adapters
        for name, adapter_cls in ALL_ADAPTERS.items():
            adapter = adapter_cls()
            self._adapters[name] = adapter
            self.bridge.register_adapter(adapter.protocol, adapter)

    def register(self, manifest: TetherManifest) -> None:
        """Register an agent with the mesh (also registers in economy)."""
        self.router.register(manifest)

    def unregister(self, tether_id: str) -> None:
        """Remove an agent from the mesh."""
        self.router.unregister(tether_id)

    def discover(self, task_type: str, protocol: Protocol | None = None) -> TetherManifest | None:
        """Find an agent that can handle the given task type."""
        results = self.router.discover(task_type, protocol=protocol)
        return results[0] if results else None

    def discover_all(self, task_type: str, protocol: Protocol | None = None) -> list[TetherManifest]:
        """Find all agents that can handle the given task type."""
        return self.router.discover(task_type, protocol=protocol)

    def list_agents(self) -> list[TetherManifest]:
        """List all registered agents."""
        return self.router.list_agents()

    async def delegate(self, task_or_type, input_data: dict[str, Any] | None = None, *,
                       source: str = "mesh", source_protocol: Protocol = Protocol.CUSTOM) -> dict[str, Any]:
        """Delegate a task across protocol boundaries.

        Can be called with either:
          mesh.delegate(tether_task) — pass a TetherTask directly
          mesh.delegate("review", input_data={"code": "..."}) — convenience form

        After delegation, applies a default reward to the winning agent.
        """
        if isinstance(task_or_type, TetherTask):
            result = await self.bridge.delegate(task_or_type)
            # Apply reward after delegation
            if task_or_type.assigned_to and "error" not in result:
                self.router.apply_reward(task_or_type.assigned_to)
            return result
        # Convenience: build a TetherTask from parts
        tether_task = TetherTask(
            task_id=f"task-{task_or_type}-{id(input_data)}",
            task_type=task_or_type,
            input_data=input_data or {},
            source_agent=source,
            source_protocol=source_protocol,
        )
        result = await self.bridge.delegate(tether_task)
        # Apply reward after delegation
        if tether_task.assigned_to and "error" not in result:
            self.router.apply_reward(tether_task.assigned_to)
        return result

    async def auto_delegate(self, task: str, input_data: dict[str, Any],
                            source: str = "mesh", source_protocol: Protocol = Protocol.CUSTOM,
                            target_protocol: Protocol | None = None) -> dict[str, Any]:
        """Automatically find the best agent and delegate.

        Uses a single discovery scan and routes directly — eliminates the
        redundant double-scan where router.discover() is called here and
        then again inside bridge.delegate() → router.route().

        Resolves source_protocol from registered adapters when set to CUSTOM.
        Falls back to the first matching agent across any protocol.

        After delegation, applies a default reward to the winning agent.
        """
        resolved_source = source_protocol

        # Single discovery scan — reuse result for both routing and task creation
        candidates = self.router.discover(task, protocol=target_protocol)
        if not candidates:
            # Fallback: try any protocol
            candidates = self.router.discover(task)
        if not candidates:
            return {"error": f"No agent found for task: {task}"}

        target_manifest = candidates[0]

        tether_task = TetherTask(
            task_id=f"task-{task}-{id(input_data)}",
            task_type=task,
            input_data=input_data,
            source_agent=source,
            source_protocol=resolved_source,
            target_protocol=target_protocol,
        )
        # Delegate directly with the pre-resolved manifest to skip the
        # second discover() call inside bridge.delegate()
        result = await self.bridge.delegate_with_manifest(tether_task, target_manifest)
        # Apply reward after delegation
        if tether_task.assigned_to and "error" not in result:
            self.router.apply_reward(tether_task.assigned_to)
        return result

    # ── Economy-specific methods ──────────────────────────────────────

    def get_wealth(self, tether_id: str) -> float:
        """Get an agent's wealth."""
        return self.router.get_wealth(tether_id)

    def get_wealth_distribution(self) -> dict[str, float]:
        """Get wealth of all agents."""
        return self.router.get_wealth_distribution()

    def get_economic_agent(self, tether_id: str) -> Any:
        """Get the EconomicAgent for a tether_id."""
        return self.router.get_economic_agent(tether_id)

    def get_economy_stats(self) -> dict[str, Any]:
        """Get economic engine statistics."""
        return self.router.get_stats()

    def set_economy_mode(self, mode: str) -> None:
        """Set the routing mode: 'economic' or 'capability'."""
        self.router.mode = mode
