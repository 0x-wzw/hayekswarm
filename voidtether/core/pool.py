"""Tether Pool — connection pooling, retry logic, and health checks."""

from __future__ import annotations
import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum

from .manifest import Protocol, TetherManifest


# ── Health Status ────────────────────────────────────────────────────

class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Health check result for an endpoint."""
    tether_id: str
    protocol: Protocol
    status: HealthStatus = HealthStatus.UNKNOWN
    latency_ms: float = 0.0
    last_check: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNKNOWN)

    def mark_success(self, latency_ms: float) -> None:
        self.status = HealthStatus.HEALTHY
        self.latency_ms = latency_ms
        self.last_check = time.monotonic()
        self.consecutive_failures = 0
        self.consecutive_successes += 1

    def mark_failure(self) -> None:
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_check = time.monotonic()
        if self.consecutive_failures >= 3:
            self.status = HealthStatus.UNHEALTHY
        else:
            self.status = HealthStatus.DEGRADED

    def mark_timeout(self) -> None:
        self.latency_ms = -1
        self.mark_failure()


# ── Retry Policy ─────────────────────────────────────────────────────

@dataclass
class RetryPolicy:
    """Exponential backoff retry configuration."""
    max_retries: int = 3
    base_delay: float = 1.0      # seconds
    max_delay: float = 30.0      # seconds
    backoff_factor: float = 2.0
    retryable_errors: tuple[str, ...] = ("TimeoutError", "ConnectionError", "ConnectionRefusedError")

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay with exponential backoff + jitter."""
        delay = min(self.base_delay * (self.backoff_factor ** attempt), self.max_delay)
        # Add up to 20% random jitter to avoid thundering herd
        jitter = delay * 0.2
        return delay + random.uniform(0, jitter)


# ── Connection Pool ──────────────────────────────────────────────────

@dataclass
class PooledConnection:
    """A connection in the pool with lifecycle tracking."""
    connection_id: str
    protocol: Protocol
    endpoint_url: str
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    in_use: bool = False
    error_count: int = 0

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at


class ConnectionPool:
    """Protocol-aware connection pool with health tracking.
    
    Manages reusable connections per endpoint with:
    - Max pool size per endpoint
    - Idle timeout / max age eviction
    - Health-aware routing (prefer healthy connections)
    """

    def __init__(
        self,
        max_per_endpoint: int = 10,
        idle_timeout: float = 300.0,    # 5 min
        max_age: float = 3600.0,         # 1 hour
    ):
        self.max_per_endpoint = max_per_endpoint
        self.idle_timeout = idle_timeout
        self.max_age = max_age
        self._pools: dict[str, list[PooledConnection]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, endpoint_url: str, protocol: Protocol) -> PooledConnection:
        """Acquire a connection from the pool (or create one)."""
        async with self._lock:
            pool = self._pools.setdefault(endpoint_url, [])
            # Evict stale connections first
            pool = [c for c in pool if c.age_seconds < self.max_age and c.idle_seconds < self.idle_timeout]
            self._pools[endpoint_url] = pool

            # Find an idle connection
            for conn in pool:
                if not conn.in_use:
                    conn.in_use = True
                    conn.last_used = time.monotonic()
                    return conn

            # Create new if under limit
            if len(pool) < self.max_per_endpoint:
                conn = PooledConnection(
                    connection_id=f"{protocol.value}-{len(pool)}",
                    protocol=protocol,
                    endpoint_url=endpoint_url,
                )
                conn.in_use = True
                pool.append(conn)
                return conn

            # Pool exhausted — force-evict the oldest idle
            for conn in sorted(pool, key=lambda c: c.last_used):
                conn.in_use = True
                conn.last_used = time.monotonic()
                return conn

            # Should never reach here
            raise RuntimeError(f"Connection pool exhausted for {endpoint_url}")

    async def release(self, conn: PooledConnection, error: bool = False) -> None:
        """Release a connection back to the pool."""
        async with self._lock:
            conn.in_use = False
            conn.last_used = time.monotonic()
            if error:
                conn.error_count += 1

    async def cleanup(self) -> int:
        """Remove stale/errored connections. Returns count of evicted."""
        async with self._lock:
            evicted = 0
            for url in list(self._pools.keys()):
                pool = self._pools[url]
                before = len(pool)
                pool = [
                    c for c in pool
                    if c.age_seconds < self.max_age
                    and c.idle_seconds < self.idle_timeout
                    and c.error_count < 5
                ]
                self._pools[url] = pool
                evicted += before - len(pool)
            return evicted

    def stats(self) -> dict[str, Any]:
        """Pool utilization stats."""
        total = sum(len(p) for p in self._pools.values())
        in_use = sum(1 for p in self._pools.values() for c in p if c.in_use)
        return {
            "total_connections": total,
            "in_use": in_use,
            "idle": total - in_use,
            "endpoints": len(self._pools),
        }


# ── Health Monitor ───────────────────────────────────────────────────

class HealthMonitor:
    """Periodic health checker for mesh agents."""

    def __init__(
        self,
        check_interval: float = 60.0,   # seconds between checks
        timeout: float = 10.0,           # per-check timeout
    ):
        self.check_interval = check_interval
        self.timeout = timeout
        self._health: dict[str, HealthCheck] = {}
        self._pool = ConnectionPool()
        self._policy = RetryPolicy(max_retries=1)
        self._running = False
        self._task: asyncio.Task | None = None

    def get_health(self, tether_id: str) -> HealthCheck:
        """Get the current health status of an agent."""
        return self._health.get(tether_id, HealthCheck(
            tether_id=tether_id, protocol=Protocol.CUSTOM
        ))

    def mark_success(self, tether_id: str, protocol: Protocol, latency_ms: float) -> None:
        """Record a successful interaction."""
        hc = self._health.setdefault(tether_id, HealthCheck(
            tether_id=tether_id, protocol=protocol
        ))
        hc.protocol = protocol
        hc.mark_success(latency_ms)

    def mark_failure(self, tether_id: str, protocol: Protocol) -> None:
        """Record a failed interaction."""
        hc = self._health.setdefault(tether_id, HealthCheck(
            tether_id=tether_id, protocol=protocol
        ))
        hc.protocol = protocol
        hc.mark_failure()

    async def check_agent(self, manifest: TetherManifest) -> HealthCheck:
        """Perform a health check on a single agent."""
        hc = self._health.setdefault(manifest.tether_id, HealthCheck(
            tether_id=manifest.tether_id, protocol=manifest.origin_protocol
        ))
        start = time.monotonic()
        try:
            # Attempt a lightweight ping via the first endpoint
            endpoint_url = None
            for p in manifest.protocols:
                if p.endpoint_url:
                    endpoint_url = p.endpoint_url
                    break
            if not endpoint_url:
                hc.mark_failure()
                hc.metadata["reason"] = "no endpoint URL"
                return hc

            # Use the connection pool for the check
            conn = await self._pool.acquire(endpoint_url, manifest.origin_protocol)
            try:
                # Simple HTTP health check (HEAD or GET /health)
                import httpx
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(f"{endpoint_url.rstrip('/')}/health")
                    latency = (time.monotonic() - start) * 1000
                    if resp.status_code < 500:
                        hc.mark_success(latency)
                        hc.metadata["http_status"] = resp.status_code
                    else:
                        hc.mark_failure()
                        hc.metadata["http_status"] = resp.status_code
            finally:
                await self._pool.release(conn)
        except Exception as exc:
            hc.mark_timeout()
            hc.metadata["error"] = str(exc)

        return hc

    async def start(self, get_manifests: Callable[[], list[TetherManifest]]) -> None:
        """Start periodic health checking."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(get_manifests))

    async def stop(self) -> None:
        """Stop health checking."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self, get_manifests: Callable[[], list[TetherManifest]]) -> None:
        """Background health check loop."""
        while self._running:
            try:
                manifests = get_manifests()
                for m in manifests:
                    if not self._running:
                        break
                    await self.check_agent(m)
                # Cleanup stale connections
                await self._pool.cleanup()
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Don't crash the loop
            await asyncio.sleep(self.check_interval)

    def all_health(self) -> list[dict[str, Any]]:
        """Get health status for all tracked agents."""
        return [hc.__dict__ | {"status": hc.status.value} for hc in self._health.values()]


# ── Retryable Execution ──────────────────────────────────────────────

async def retry_execute(
    fn: Callable,
    *args: Any,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[int, Exception], Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute a callable with exponential backoff retry.
    
    Args:
        fn: Async callable to execute
        policy: Retry configuration (default if None)
        on_retry: Optional callback(attempt, exception) on each retry
    """
    if policy is None:
        policy = RetryPolicy()

    last_exc: Exception | None = None
    for attempt in range(policy.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            err_name = type(exc).__name__
            if err_name not in policy.retryable_errors and attempt > 0:
                raise  # non-retryable error
            if attempt < policy.max_retries:
                delay = policy.delay_for_attempt(attempt)
                if on_retry:
                    on_retry(attempt, exc)
                await asyncio.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("retry_execute: unreachable")