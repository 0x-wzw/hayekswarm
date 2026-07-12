"""
HayekSwarm — Swarm Intelligence Core for the Hayek Economy

This module provides swarm-native coordination capabilities including:
- PricingOracle: Cost-optimized model routing and bid estimation
- ConsensusEngine: Voting mechanisms for auction resolution
- Raft/Gossip/Quorum protocols: Distributed consensus
- Coordinator: Central orchestration of swarm agents
- Message Bus: Inter-agent communication layer
- Role Manager: Agent specialization
- Docker Sandbox: Ephemeral agent execution
- Swarm Memory: Cross-simulation persistent knowledge base
"""

from .cost_router import PricingOracle, EarlyTerminationEngine, TaskProfile, RoutingDecision, ModelSpec, TaskComplexity, CostTier
from .consensus import ConsensusEngine, ConsensusMethod
from .message_bus import InMemoryMessageBus, ChannelMessageBus, create_message_bus
from .swarm_memory import SwarmMemory

# Docker-dependent modules — lazy import to avoid hard dependency
try:
    from .coordinator import SwarmCoordinator, AgentRole, AgentSpec, SwarmMessage, SwarmState, MessageBus, RoleManager
    _HAS_COORDINATOR = True
except ImportError:
    SwarmCoordinator = None  # type: ignore
    AgentRole = None
    AgentSpec = None
    SwarmMessage = None
    SwarmState = None
    MessageBus = None
    RoleManager = None
    _HAS_COORDINATOR = False

try:
    from .docker_sandbox import DockerSandbox, SandboxAgent, SandboxConfig, SandboxResult, SandboxPool
    _HAS_DOCKER = True
except ImportError:
    DockerSandbox = None  # type: ignore
    SandboxAgent = None
    SandboxConfig = None
    SandboxResult = None
    SandboxPool = None
    _HAS_DOCKER = False

__all__ = [
    "PricingOracle",
    "EarlyTerminationEngine",
    "TaskProfile",
    "RoutingDecision",
    "ModelSpec",
    "TaskComplexity",
    "CostTier",
    "ConsensusEngine",
    "ConsensusMethod",
    "InMemoryMessageBus",
    "ChannelMessageBus",
    "create_message_bus",
    "SwarmMemory",
    "SwarmCoordinator",
    "AgentRole",
    "AgentSpec",
    "SwarmMessage",
    "SwarmState",
    "MessageBus",
    "RoleManager",
    "DockerSandbox",
    "SandboxAgent",
    "SandboxConfig",
    "SandboxResult",
    "SandboxPool",
    "_HAS_COORDINATOR",
    "_HAS_DOCKER",
]
