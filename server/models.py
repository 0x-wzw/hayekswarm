"""HayekSwarm Marketplace — Pydantic models for the API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class TaskStatus(str, Enum):
    PENDING = "pending"
    AUCTIONING = "auctioning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentStatus(str, Enum):
    NOVICE = "novice"
    VETERAN = "veteran"
    TYCOON = "tycoon"
    BANKRUPT = "bankrupt"


# ── API Key ───────────────────────────────────────────────────────────────────


class APIKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)


class APIKeyResponse(BaseModel):
    id: int
    label: str
    key: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    is_active: bool


# ── Tasks ─────────────────────────────────────────────────────────────────────


class TaskSubmit(BaseModel):
    """Request to submit a task to the marketplace."""
    content: str = Field(..., min_length=1, max_length=100000, description="The task prompt")
    stakes: str = Field("medium", description="low | medium | high | critical")
    dimensions: list[str] = Field(default_factory=list, description="Explicit dimension list (optional)")
    capabilities: list[str] = Field(default_factory=list, description="Required capabilities (optional)")
    max_bid: float = Field(10.0, ge=0.1, description="Maximum bid you're willing to pay")
    callback_url: Optional[str] = Field(None, description="URL to POST result to when complete")


class TaskResponse(BaseModel):
    id: int
    status: TaskStatus
    content: str
    stakes: str
    dimensions: list[str]
    capabilities: list[str]
    max_bid: float
    callback_url: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    winner_dimension: Optional[str] = None
    winner_name: Optional[str] = None
    winning_bid: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None
    total_cost: Optional[float] = None


# ── Agents ────────────────────────────────────────────────────────────────────


class AgentResponse(BaseModel):
    dimension: str
    name: str
    model: str
    wealth: float
    status: AgentStatus
    wins: int
    losses: int
    total_tasks: int
    total_reward: float
    win_rate: float
    last_bid: float
    tier: str
    capabilities: list[str]


# ── Market ────────────────────────────────────────────────────────────────────


class MarketPrice(BaseModel):
    dimension: str
    model: str
    tier: str
    base_bid: float
    current_wealth: float
    suggested_bid: float
    win_rate: float
    status: AgentStatus


class MarketOverview(BaseModel):
    prices: list[MarketPrice]
    total_agents: int
    active_agents: int
    bankrupt_agents: int
    total_auctions: int
    total_wealth: float
    richest_agent: Optional[str] = None
    poorest_agent: Optional[str] = None


# ── Transactions ──────────────────────────────────────────────────────────────


class TransactionResponse(BaseModel):
    id: int
    task_id: int
    agent_dimension: str
    agent_name: str
    bid_amount: float
    reward_amount: float
    net_change: float
    created_at: datetime


# ── Stats ─────────────────────────────────────────────────────────────────────


class StatsResponse(BaseModel):
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    pending_tasks: int
    total_auctions: int
    total_transactions: int
    total_revenue: float
    agents: list[AgentResponse]
    market: MarketOverview
