"""Tether Envelope — inter-agent message wrapper."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


@dataclass
class TetherEnvelope:
    """A message envelope for inter-agent communication.
    
    Every message in the VoidTether mesh is wrapped in a TetherEnvelope,
    providing routing metadata, authentication context, and tracing.
    """
    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""                        # tether_id of sender
    target: str = ""                        # tether_id of recipient (or "broadcast")
    task_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id: str = ""                      # Distributed tracing
    auth_token: str = ""                    # Bearer token for zero-trust
    protocol_hint: str = ""                 # Source protocol for routing
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "source": self.source,
            "target": self.target,
            "task_type": self.task_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "auth_token": "***" if self.auth_token else "",
            "protocol_hint": self.protocol_hint,
        }
