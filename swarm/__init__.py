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
from .coordinator import SwarmCoordinator, AgentRole, AgentSpec, SwarmMessage, SwarmState, MessageBus, RoleManager
from .docker_sandbox import DockerSandbox, SandboxAgent, SandboxConfig, SandboxResult, SandboxPool
from .message_bus import InMemoryMessageBus, ChannelMessageBus, create_message_bus
from .swarm_memory import SwarmMemory

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
    "InMemoryMessageBus",
    "ChannelMessageBus",
    "create_message_bus",
    "SwarmMemory",
]
