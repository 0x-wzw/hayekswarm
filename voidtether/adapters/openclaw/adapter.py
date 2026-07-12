"""OpenClaw Protocol Adapter — bridges the OpenClaw agent skill framework."""

from __future__ import annotations
from typing import Any
from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


class OpenClawAdapter(BaseAdapter):
    """Adapter for OpenClaw agents.
    
    OpenClaw uses a skill-based architecture designed for non-interactive
    agent pipelines. Key mappings:
    
      OpenClaw Skill   -> Tether capability (task)
      Composition      -> Tether flow (multi-step task pipeline)
      Agent Card       -> TetherManifest
    """
    
    protocol = Protocol.OPENCLAW
    
    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert OpenClaw skill output to VoidTether format."""
        return {
            "text": data.get("output", data.get("response", str(data))),
            "media": data.get("media", []),
            "metadata": data.get("metadata", {}),
        }
    
    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert VoidTether format to OpenClaw skill invocation."""
        return {
            "skill": data.get("skill", data.get("task_type", "")),
            "composition": data.get("composition"),
            "input": data.get("input", data),
            "non_interactive": True,
        }
    
    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a task via OpenClaw skill."""
        # TODO: Implement OpenClaw CLI npx hyperframes integration
        return {
            "status": "completed",
            "output": f"OpenClaw skill '{task_type}' executed (placeholder)",
            "media": [],
        }


def openclaw_skills_to_manifest(skills: list[str], name: str = "OpenClaw Agent", endpoint: str = "") -> TetherManifest:
    """Convert OpenClaw skill list to TetherManifest."""
    return TetherManifest(
        tether_id=f"vt-openclaw-{name.lower().replace(' ', '-')}",
        name=name,
        origin_protocol=Protocol.OPENCLAW,
        capabilities={
            "tasks": skills,
            "modalities": ["text", "video", "html"],
            "streaming": True,
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.OPENCLAW,
            endpoint_url=endpoint,
        )],
    )
