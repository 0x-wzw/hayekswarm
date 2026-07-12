"""VoidTether Core — the mesh engine."""

from .manifest import TetherManifest, Protocol, TaskState, ProtocolEndpoint
from .router import TetherRouter, TetherTask
from .bridge import ProtocolBridge, BaseAdapter
from .pool import (
    ConnectionPool, RetryPolicy, HealthMonitor, HealthStatus, HealthCheck,
    retry_execute, PooledConnection,
)
from .envelope import TetherEnvelope
from .lifecycle import can_transition, transition
from .auth import HMACVerifier

__all__ = [
    "TetherManifest", "Protocol", "TaskState", "ProtocolEndpoint",
    "TetherRouter", "TetherTask",
    "ProtocolBridge", "BaseAdapter",
    "ConnectionPool", "RetryPolicy", "HealthMonitor", "HealthStatus", "HealthCheck",
    "retry_execute", "PooledConnection",
    "TetherEnvelope",
    "can_transition", "transition",
    "HMACVerifier",
]