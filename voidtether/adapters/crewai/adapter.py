"""CrewAI Adapter — bridges CrewAI's role-based multi-agent framework."""

from __future__ import annotations
from typing import Any
from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


class CrewAIAdapter(BaseAdapter):
    """Adapter for CrewAI agents.
    
    CrewAI uses role-based agent definitions. Key mappings:
    
      CrewAI Role     -> Tether capability
      CrewAI Task     -> Tether task
      CrewAI Tool     -> Tether capability (tool use)
    """
    
    protocol = Protocol.CREWAI
    
    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"text": data.get("output", str(data)), "role": data.get("role", "")}
    
    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"role": data.get("task_type", ""), "goal": data.get("input", {})}
    
    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed", "output": f"CrewAI agent '{task_type}' executed (placeholder)"}
