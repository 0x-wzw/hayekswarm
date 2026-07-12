"""A2A Protocol Adapter — bridges Google Agent2Agent protocol."""

from __future__ import annotations
from typing import Any
from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


class A2AAdapter(BaseAdapter):
    """Adapter for Google A2A (Agent2Agent) protocol.
    
    Translates between A2A's JSON-RPC task lifecycle and VoidTether's
    normalized representation. Key A2A concepts mapped:
    
      A2A Agent Card  -> TetherManifest
      A2A Task        -> TetherTask
      A2A JSON-RPC    -> TetherEnvelope
      A2A Skills      -> Tether capabilities.tasks
    """
    
    protocol = Protocol.A2A
    
    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert A2A JSON-RPC response to VoidTether format."""
        # A2A uses JSON-RPC with artifact-based responses
        if "result" in data:
            result = data["result"]
            # Extract artifacts from A2A task result
            artifacts = result.get("artifacts", [])
            normalized = {
                "status": result.get("status", {}).get("state", "unknown"),
                "artifacts": artifacts,
                "metadata": result.get("metadata", {}),
            }
            # Flatten text artifacts
            for art in artifacts:
                if art.get("type") == "text":
                    normalized["text"] = art.get("content", "")
                    break
            return normalized
        return data
    
    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert VoidTether format to A2A JSON-RPC request."""
        # Build A2A task params
        message = {
            "role": "user",
            "parts": []
        }
        
        # Convert payload to A2A message parts
        if "text" in data:
            message["parts"].append({"type": "text", "text": data["text"]})
        if "structured" in data:
            message["parts"].append({"type": "data", "data": data["structured"]})
        if not message["parts"]:
            message["parts"].append({"type": "text", "text": str(data)})
        
        return {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "params": {
                "message": message,
            }
        }
    
    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a task via A2A protocol.
        
        In production, this would make HTTP requests to the A2A agent's
        endpoint. For now, returns the translated input as a placeholder.
        """
        # Find A2A endpoint from manifest
        a2a_endpoint = None
        for p in manifest.protocols:
            if p.protocol == Protocol.A2A:
                a2a_endpoint = p.endpoint_url or p.agent_card_url
                break
        
        if not a2a_endpoint:
            return {"error": "No A2A endpoint found in manifest"}
        
        # TODO: Implement actual A2A HTTP client
        # For v0.1.0, this is a protocol-compliant placeholder
        return {
            "status": "completed",
            "artifacts": [],
            "metadata": {"note": "A2A adapter placeholder — implement HTTP client"}
        }


def a2a_card_to_manifest(card: dict[str, Any]) -> TetherManifest:
    """Convert an A2A Agent Card to a TetherManifest."""
    skills = card.get("skills", [])
    tasks = [s.get("id", s.get("name", "")) for s in skills]
    
    return TetherManifest(
        tether_id=f"vt-{card.get('name', 'unknown').lower().replace(' ', '-')}",
        name=card.get("name", "Unknown A2A Agent"),
        origin_protocol=Protocol.A2A,
        capabilities={
            "tasks": tasks,
            "modalities": card.get("capabilities", {}).get("modalities", ["text"]),
            "streaming": card.get("capabilities", {}).get("streaming", False),
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.A2A,
            agent_card_url=card.get("url"),
            endpoint_url=card.get("url"),
        )],
    )
