"""LangGraph Adapter — bridges LangGraph's graph-based agent workflows."""

from __future__ import annotations
from typing import Any
from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


class LangGraphAdapter(BaseAdapter):
    """Adapter for LangGraph agents.
    
    LangGraph uses graph nodes with stateful transitions. Key mappings:
    
      LangGraph Node      -> TetherManifest
      LangGraph State     -> Tether envelope
      LangGraph Edge      -> Tether task transfer
    """
    
    protocol = Protocol.LANGGRAPH
    
    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"text": data.get("output", str(data)), "state": data.get("state", {})}
    
    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"node_id": data.get("task_type", ""), "state": data.get("input", {})}
    
    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed", "output": f"LangGraph node '{task_type}' executed (placeholder)"}
