"""VoidTether — The cord that binds across the void.

A unified agent-to-agent interoperability mesh that bridges
disparate AI agent protocols.
"""

__version__ = "0.4.0"

from .core import (
    TetherManifest, Protocol, TaskState, ProtocolEndpoint,
    TetherRouter, TetherTask,
    ProtocolBridge, BaseAdapter,
)
from .mesh import Mesh

__all__ = [
    "Mesh",
    "TetherManifest", "Protocol", "TaskState", "ProtocolEndpoint",
    "TetherRouter", "TetherTask",
    "ProtocolBridge", "BaseAdapter",
]
