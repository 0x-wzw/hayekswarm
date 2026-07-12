"""Tether Bridge — protocol translation between agent frameworks."""

from __future__ import annotations
import abc
import asyncio
import time
from typing import Any, AsyncGenerator
from .manifest import TetherManifest, Protocol, TaskState, ProtocolEndpoint
from .router import TetherRouter, TetherTask
from .pool import ConnectionPool, RetryPolicy, HealthMonitor, retry_execute


class ProtocolBridge:
    """Translates messages between different agent protocols.
    
    The bridge is the heart of VoidTether — it takes a task from one
    protocol, translates it into the target protocol's format, and
    streams the response back. Now with connection pooling, retry logic,
    health-aware routing, and execution timeout.
    """
    
    # Default timeout for adapter.execute() calls (seconds)
    DEFAULT_EXECUTE_TIMEOUT = 120.0
    
    def __init__(self, router: TetherRouter, *, 
                 retry_policy: RetryPolicy | None = None,
                 pool_size: int = 10,
                 execute_timeout: float | None = None):
        self.router = router
        self._adapters: dict[Protocol, "BaseAdapter"] = {}
        self.retry_policy = retry_policy or RetryPolicy()
        self.pool = ConnectionPool(max_per_endpoint=pool_size)
        self.health = HealthMonitor()
        self.execute_timeout = execute_timeout or self.DEFAULT_EXECUTE_TIMEOUT
    
    def register_adapter(self, protocol: Protocol, adapter: "BaseAdapter") -> None:
        """Register a protocol adapter."""
        self._adapters[protocol] = adapter
    
    async def delegate(self, task: TetherTask) -> dict[str, Any]:
        """Delegate a task across protocol boundaries.

        1. Route the task to the best available agent
        2. Translate the request from source protocol to target protocol
        3. Execute the task via the target protocol adapter (with retry + timeout)
        4. Translate the response back to the source protocol
        """
        target_manifest = self.router.route(task)
        if not target_manifest:
            return {"error": f"No agent found for task type: {task.task_type}"}
        return await self.delegate_with_manifest(task, target_manifest)

    async def delegate_with_manifest(self, task: TetherTask, target_manifest: TetherManifest) -> dict[str, Any]:
        """Delegate with a pre-resolved target manifest — skips redundant discovery.

        This is the core execution path shared by both delegate() and auto_delegate().
        """
        target_protocol = target_manifest.origin_protocol
        source_protocol = task.source_protocol
        
        # Get adapters
        source_adapter = self._adapters.get(source_protocol)
        target_adapter = self._adapters.get(target_protocol)
        
        if not target_adapter:
            return {"error": f"No adapter registered for protocol: {target_protocol}"}
        
        # Translate request — normalize_output is for responses, not inputs.
        # Input data from the API is already in normalized format.
        normalized_input = task.input_data
        
        # Translate to target protocol format
        target_input = target_adapter.denormalize_input(normalized_input)
        
        # Execute with retry + timeout
        task.state = TaskState.RUNNING
        task.assigned_to = target_manifest.tether_id
        
        async def _execute():
            return await asyncio.wait_for(
                target_adapter.execute(target_manifest, task.task_type, target_input),
                timeout=self.execute_timeout,
            )
        
        start = time.monotonic()
        try:
            result = await retry_execute(_execute, policy=self.retry_policy)
            latency = (time.monotonic() - start) * 1000
            self.health.mark_success(target_manifest.tether_id, target_protocol, latency)
            task.state = TaskState.COMPLETED
            task.output_data = result
            return result
        except asyncio.TimeoutError:
            self.health.mark_timeout(target_manifest.tether_id, target_protocol)
            task.state = TaskState.FAILED
            return {"error": f"Task execution timed out after {self.execute_timeout}s"}
        except Exception as exc:
            self.health.mark_failure(target_manifest.tether_id, target_protocol)
            task.state = TaskState.FAILED
            return {"error": f"Task execution failed after retries: {exc}"}
    
    async def delegate_stream(self, task: TetherTask) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a task's execution across protocol boundaries.
        
        Yields intermediate chunks as the target adapter produces them.
        Falls back to single-shot if adapter doesn't support streaming.
        """
        target_manifest = self.router.route(task)
        if not target_manifest:
            yield {"error": f"No agent found for task type: {task.task_type}"}
            return
        
        target_protocol = target_manifest.origin_protocol
        target_adapter = self._adapters.get(target_protocol)
        
        if not target_adapter:
            yield {"error": f"No adapter registered for protocol: {target_protocol}"}
            return
        
        source_adapter = self._adapters.get(task.source_protocol)
        if source_adapter and task.source_protocol != target_protocol:
            normalized_input = source_adapter.normalize_output(task.input_data)
        else:
            normalized_input = task.input_data
        
        target_input = target_adapter.denormalize_input(normalized_input)
        task.state = TaskState.STREAMING
        task.assigned_to = target_manifest.tether_id
        
        # Check if adapter supports streaming
        if hasattr(target_adapter, "execute_stream") and callable(target_adapter.execute_stream):
            try:
                async for chunk in target_adapter.execute_stream(target_manifest, task.task_type, target_input):
                    yield {"chunk": chunk, "state": "streaming"}
                task.state = TaskState.COMPLETED
                yield {"state": "completed"}
            except Exception as exc:
                task.state = TaskState.FAILED
                yield {"error": str(exc), "state": "failed"}
        else:
            # Fallback: single-shot delegate, yield once
            result = await self.delegate(task)
            yield result


class BaseAdapter(abc.ABC):
    """Base class for protocol adapters.
    
    Each adapter implements translation between a specific agent protocol
    and VoidTether's normalized intermediate representation.
    
    Subclasses MUST implement execute(). Override normalize_output and
    denormalize_input when the source/target protocol needs translation.
    Override execute_stream() to support streaming responses.
    """
    
    protocol: Protocol = Protocol.CUSTOM
    
    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert protocol-specific output to VoidTether normalized format."""
        return data
    
    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert VoidTether normalized format to protocol-specific input."""
        return data
    
    @abc.abstractmethod
    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a task on an agent using this protocol."""
        ...
    
    async def execute_stream(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a task's execution. Override for streaming support."""
        # Default: single-shot execute, yield once
        result = await self.execute(manifest, task_type, input_data)
        yield result