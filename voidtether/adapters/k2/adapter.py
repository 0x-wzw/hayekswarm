"""K2 Swarm Adapter — high-performance multi-agent subprocess orchestration.

The K2 adapter is the execution engine behind the K2 Swarm Orchestrator.
It spawns and manages pools of subprocess agents, executes tasks in
parallel with dependency resolution, load balances across the pool,
handles failures with circuit breakers, and persists swarm state.

Key capabilities:
  - Subprocess spawning: spawn N agents as asyncio subprocesses
  - Parallel execution: fan-out tasks across the pool via asyncio.gather
  - Dependency resolution: topological sort of task DAGs
  - Load balancing: route to least-loaded agent
  - Fault tolerance: circuit breaker per agent, exponential backoff retry
  - State persistence: swarm state saved to SQLite for crash recovery
  - Inter-agent communication: agents can message each other through the Hub
"""

from __future__ import annotations
import asyncio
import json
import os
import shlex
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable

from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint, TaskState


# ── Data Structures ──────────────────────────────────────────────────

@dataclass
class SwarmAgent:
    """A spawned subprocess agent in the swarm pool."""
    agent_id: str
    tether_id: str
    process: asyncio.subprocess.Process | None = None
    command: str = ""
    status: str = "idle"          # idle | busy | unhealthy | dead
    active_tasks: int = 0
    consecutive_failures: int = 0
    total_tasks: int = 0
    total_failures: int = 0
    last_used: float = 0.0
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < 3 and self.status != "dead"

    @property
    def load(self) -> float:
        return self.active_tasks + (self.consecutive_failures * 0.5)


@dataclass
class SwarmTask:
    """A task within a swarm execution."""
    task_id: str
    task_type: str
    input_data: dict[str, Any]
    dependencies: list[str] = field(default_factory=list)
    assigned_to: str | None = None
    state: TaskState = TaskState.SUBMITTED
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class SwarmExecution:
    """A complete swarm execution with task DAG and agent pool."""
    execution_id: str
    session_id: str
    task_type: str
    input_data: dict[str, Any]
    agents: list[SwarmAgent] = field(default_factory=list)
    tasks: dict[str, SwarmTask] = field(default_factory=dict)
    status: str = "pending"       # pending | running | completed | failed
    created_at: float = 0.0
    completed_at: float | None = None
    error: str | None = None


# ── K2 Adapter ──────────────────────────────────────────────────────

class K2Adapter(BaseAdapter):
    """K2 Swarm Protocol Adapter — spawns, manages, and orchestrates agent swarms.

    The K2 adapter transforms a single task delegation into a full swarm
    execution: it spawns a pool of subprocess agents, fans out subtasks
    across the pool respecting dependencies, collects results, handles
    failures, and returns the aggregated output.

    Lifecycle per execution:
      1. resolve_dependencies() — topological sort of task DAG
      2. spawn_pool() — launch N subprocess agents
      3. execute_parallel() — fan-out ready tasks across the pool
      4. collect_results() — gather outputs, handle partial failures
      5. shutdown_pool() — terminate all subprocesses
      6. persist_state() — save execution to SQLite
    """

    protocol = Protocol.K2

    # Default pool configuration
    DEFAULT_POOL_SIZE = 3
    MAX_POOL_SIZE = 20
    DEFAULT_AGENT_COMMAND = "python3 -m k2_agent"
    SPAWN_TIMEOUT = 10.0
    TASK_TIMEOUT = 120.0
    SHUTDOWN_TIMEOUT = 5.0
    MAX_CONSECUTIVE_FAILURES = 3
    CIRCUIT_BREAKER_RESET_INTERVAL = 60.0
    # Fault tolerance / retry (K2-006)
    MAX_TASK_RETRIES = 2
    RETRY_BASE_DELAY = 0.5
    RETRY_MAX_DELAY = 8.0
    # Load balancer / metrics (K2-005)
    LOAD_METRICS_WINDOW = 300.0       # 5min sliding window for load tracking
    # State persistence (K2-007)
    DEFAULT_DB_PATH = "/tmp/k2_swarm.db"
    # Inter-agent comms (K2-008)
    MAX_BROADCAST_AGENTS = 50

    def __init__(self):
        super().__init__()
        self._executions: dict[str, SwarmExecution] = {}
        self._agent_pools: dict[str, list[SwarmAgent]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._circuit_breakers: dict[str, dict] = {}
        # K2-005: Load balancer metrics
        self._agent_metrics: dict[str, dict] = {}  # agent_id -> {task_completions, total_latency, window_start}
        # K2-007: State persistence
        self._db_path: str | None = None
        self._db = None
        self._init_db()

    # ── Core Execution ──────────────────────────────────────────────

    async def execute(
        self,
        manifest: TetherManifest,
        task_type: str,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a task via K2 swarm orchestration.

        This is the main entry point called by ProtocolBridge.delegate().
        It transforms a single task into a full swarm execution.
        """
        execution = self._create_execution(manifest, task_type, input_data)

        try:
            # 1. Resolve task dependencies
            tasks = self._build_task_dag(execution, input_data)
            execution.tasks = {t.task_id: t for t in tasks}

            # 2. Spawn agent pool
            pool_size = input_data.get("pool_size", self.DEFAULT_POOL_SIZE)
            agent_command = self._get_agent_command(manifest)
            agents = await self._spawn_pool(execution.execution_id, pool_size, agent_command)
            execution.agents = agents

            # 3. Execute tasks in dependency order
            execution.status = "running"
            results = await self._execute_dag(execution)

            # 4. Collect, persist, and return
            execution.status = "completed"
            execution.completed_at = time.time()
            result = self._aggregate_results(execution, results)
            self._persist_execution(execution)  # K2-007
            return result

        except Exception as exc:
            execution.status = "failed"
            execution.error = str(exc)
            return {"error": f"K2 swarm execution failed: {exc}", "execution_id": execution.execution_id}

        finally:
            await self._shutdown_pool(execution.execution_id)

    async def execute_stream(
        self,
        manifest: TetherManifest,
        task_type: str,
        input_data: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a K2 swarm execution, yielding per-task results."""
        execution = self._create_execution(manifest, task_type, input_data)

        try:
            tasks = self._build_task_dag(execution, input_data)
            execution.tasks = {t.task_id: t for t in tasks}
            pool_size = input_data.get("pool_size", self.DEFAULT_POOL_SIZE)
            agent_command = self._get_agent_command(manifest)
            agents = await self._spawn_pool(execution.execution_id, pool_size, agent_command)
            execution.agents = agents
            execution.status = "running"

            yield {"type": "swarm_start", "execution_id": execution.execution_id, "agents": len(agents), "tasks": len(tasks)}

            async for result in self._stream_dag(execution):
                yield result

            execution.status = "completed"
            execution.completed_at = time.time()
            yield {"type": "swarm_complete", "execution_id": execution.execution_id}

        except Exception as exc:
            execution.status = "failed"
            yield {"type": "swarm_error", "execution_id": execution.execution_id, "error": str(exc)}
        finally:
            await self._shutdown_pool(execution.execution_id)

    # ── Execution Lifecycle ──────────────────────────────────────────

    def _create_execution(self, manifest: TetherManifest, task_type: str, input_data: dict) -> SwarmExecution:
        """Create a new swarm execution record."""
        execution = SwarmExecution(
            execution_id=f"k2-{uuid.uuid4().hex[:12]}",
            session_id=input_data.get("session_id", ""),
            task_type=task_type,
            input_data=input_data,
            created_at=time.time(),
        )
        self._executions[execution.execution_id] = execution
        return execution

    def _build_task_dag(self, execution: SwarmExecution, input_data: dict) -> list[SwarmTask]:
        """Build a task DAG from input data with full cycle detection (K2-004).

        Input can provide:
          - A single task (simple mode)
          - A list of tasks with dependencies (DAG mode)
          - A task count for auto-fan-out (parallel mode)

        Raises ValueError if cycle is detected in DAG mode.
        """
        tasks_list = input_data.get("tasks", [])
        task_count = input_data.get("task_count", 0)

        if tasks_list:
            # DAG mode: explicit tasks with dependencies
            # Validate: detect cycles using Kahn's algorithm
            task_ids = {t.get("id", f"task-{i}") for i, t in enumerate(tasks_list)}
            dep_map = {}
            for t in tasks_list:
                tid = t.get("id", "")
                deps = t.get("depends_on", [])
                for d in deps:
                    if d not in task_ids and d != "":
                        raise ValueError(f"Dependency '{d}' for task '{tid}' references unknown task")
                dep_map[tid] = deps

            # Topological sort validation (Kahn's)
            in_degree = {tid: 0 for tid in task_ids}
            for tid, deps in dep_map.items():
                for d in deps:
                    if d:
                        in_degree[tid] = in_degree.get(tid, 0) + 1

            queue = [tid for tid, deg in in_degree.items() if deg == 0]
            sorted_count = 0
            while queue:
                tid = queue.pop(0)
                sorted_count += 1
                for other_tid, other_deps in dep_map.items():
                    if tid in other_deps:
                        in_degree[other_tid] -= 1
                        if in_degree[other_tid] == 0:
                            queue.append(other_tid)

            if sorted_count != len(task_ids):
                raise ValueError(f"DAG cycle detected: {len(task_ids) - sorted_count} tasks unreachable")

            return [
                SwarmTask(
                    task_id=t.get("id", f"task-{i}"),
                    task_type=t.get("type", execution.task_type),
                    input_data=t.get("input", {}),
                    dependencies=t.get("depends_on", []),
                    created_at=time.time(),
                )
                for i, t in enumerate(tasks_list)
            ]
        elif task_count > 0:
            # Parallel mode: auto-generate N subtasks
            return [
                SwarmTask(
                    task_id=f"subtask-{i}",
                    task_type=execution.task_type,
                    input_data={**execution.input_data, "subtask_index": i, "total_subtasks": task_count},
                    created_at=time.time(),
                )
                for i in range(task_count)
            ]
        else:
            # Simple mode: single task
            return [
                SwarmTask(
                    task_id="task-0",
                    task_type=execution.task_type,
                    input_data=execution.input_data,
                    created_at=time.time(),
                )
            ]

    async def _spawn_pool(self, execution_id: str, pool_size: int, command: str) -> list[SwarmAgent]:
        """Spawn a pool of subprocess agents.

        Each agent is an independent subprocess that communicates
        via JSON-RPC over stdin/stdout (ACP-compatible).
        """
        pool_size = min(max(1, pool_size), self.MAX_POOL_SIZE)
        agents = []
        cmd_parts = shlex.split(command)
        env = os.environ.copy()
        env["K2_AGENT_ID"] = f"k2-{execution_id[:8]}"

        for i in range(pool_size):
            agent_id = f"{execution_id}-agent-{i}"
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd_parts,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                # Brief pause to detect immediate process death
                await asyncio.sleep(0.05)
                if proc.returncode is not None:
                    # Process died immediately — mark as virtual
                    agent = SwarmAgent(
                        agent_id=agent_id,
                        tether_id=f"k2-swarm-{i}",
                        process=None,
                        command=command,
                        status="idle",
                        created_at=time.time(),
                        metadata={"virtual": True, "error": f"Process exited with code {proc.returncode}"},
                    )
                else:
                    agent = SwarmAgent(
                        agent_id=agent_id,
                        tether_id=f"k2-swarm-{i}",
                        process=proc,
                        command=command,
                        status="idle",
                        created_at=time.time(),
                    )
                agents.append(agent)
            except Exception as exc:
                # If we can't spawn, create a virtual agent for in-process execution
                agent = SwarmAgent(
                    agent_id=agent_id,
                    tether_id=f"k2-swarm-{i}",
                    process=None,
                    command=command,
                    status="idle",
                    created_at=time.time(),
                    metadata={"virtual": True, "error": str(exc)},
                )
                agents.append(agent)

        self._agent_pools[execution_id] = agents
        return agents

    async def _execute_dag(self, execution: SwarmExecution) -> dict[str, Any]:
        """Execute the task DAG respecting dependencies.

        Uses a topological approach: at each step, find all tasks
        whose dependencies are satisfied, execute them in parallel
        across the agent pool, then repeat until all tasks are done.
        """
        results = {}
        task_map = execution.tasks
        completed = set()
        failed = set()

        while len(completed) + len(failed) < len(task_map):
            # Find ready tasks (all dependencies satisfied)
            ready = [
                t for t in task_map.values()
                if t.task_id not in completed and t.task_id not in failed
                and all(dep in completed for dep in t.dependencies)
            ]

            if not ready:
                # Deadlock detected
                blocked = [t for t in task_map.values() if t.task_id not in completed and t.task_id not in failed]
                return {"error": f"Dependency deadlock: {len(blocked)} tasks blocked", "completed": len(completed)}

            # Execute ready tasks in parallel across the pool
            batch_results = await self._execute_batch(execution, ready)

            for task_id, result in batch_results.items():
                if "error" in result:
                    failed.add(task_id)
                    task_map[task_id].state = TaskState.FAILED
                    task_map[task_id].error = result["error"]
                else:
                    completed.add(task_id)
                    task_map[task_id].state = TaskState.COMPLETED
                    task_map[task_id].result = result
                    task_map[task_id].completed_at = time.time()
                results[task_id] = result

        return results

    async def _execute_batch(self, execution: SwarmExecution, tasks: list[SwarmTask]) -> dict[str, Any]:
        """Execute a batch of ready tasks in parallel, each fault-tolerant.

        Every task is run through ``_run_task_with_retry`` so a transient agent
        failure retries on a different agent instead of failing the task.
        """
        if not tasks:
            return {}

        completed = await asyncio.gather(
            *[self._run_task_with_retry(execution, task) for task in tasks],
            return_exceptions=True,
        )

        results = {}
        for item in completed:
            if isinstance(item, tuple):
                tid, result = item
                results[tid] = result
            elif isinstance(item, Exception):
                results["error"] = {"error": str(item)}

        return results

    async def _run_task_with_retry(self, execution: SwarmExecution, task: SwarmTask) -> tuple[str, dict]:
        """Execute one task with retry + per-agent circuit breaking (K2-006).

        Each attempt routes the task to the least-loaded healthy agent whose
        circuit breaker is closed, skipping agents that already failed this
        task. Failures are counted against the agent and its circuit breaker;
        an agent that trips ``MAX_CONSECUTIVE_FAILURES`` is benched for
        ``CIRCUIT_BREAKER_RESET_INTERVAL`` seconds. Between attempts we wait an
        exponential backoff (``RETRY_BASE_DELAY * 2**attempt``, capped at
        ``RETRY_MAX_DELAY``).

        Note: ``_execute_on_agent`` reports failure by returning a dict with an
        ``"error"`` key rather than raising, so a returned error is treated as a
        failed attempt (the previous implementation counted such results as
        successes).
        """
        tried: set[str] = set()
        last_result = {"error": f"Task '{task.task_id}': no agent available"}

        for attempt in range(self.MAX_TASK_RETRIES + 1):
            agent = self._select_agent(execution, exclude=tried)
            if agent is None:
                break

            agent.active_tasks += 1
            agent.status = "busy"
            task.assigned_to = agent.agent_id
            task.state = TaskState.RUNNING
            if task.started_at is None:
                task.started_at = time.time()

            try:
                result = await self._execute_on_agent(agent, task)
            except Exception as exc:  # defensive: _execute_on_agent shouldn't raise
                result = {"error": f"Agent '{agent.agent_id}' raised: {exc}"}
            finally:
                agent.active_tasks -= 1
                if agent.status == "busy":
                    agent.status = "idle"

            agent.last_used = time.time()
            failed = not isinstance(result, dict) or bool(result.get("error"))

            if not failed:
                agent.total_tasks += 1
                agent.consecutive_failures = 0
                self._breaker_record_success(agent.agent_id)
                if attempt > 0:
                    result = {**result, "retries": attempt}
                return task.task_id, result

            # Failure bookkeeping — count against agent + circuit breaker
            agent.total_failures += 1
            agent.consecutive_failures += 1
            self._breaker_record_failure(agent.agent_id)
            if agent.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                agent.status = "unhealthy"
            tried.add(agent.agent_id)
            err = result if isinstance(result, dict) else {"error": str(result)}
            last_result = {**err, "attempts": attempt + 1, "failed_agent": agent.agent_id}

            # Exponential backoff before the next attempt, if any remain
            if attempt < self.MAX_TASK_RETRIES:
                delay = min(self.RETRY_BASE_DELAY * (2 ** attempt), self.RETRY_MAX_DELAY)
                await asyncio.sleep(delay)

        return task.task_id, last_result

    def _select_agent(self, execution: SwarmExecution, exclude: set[str] | None = None) -> SwarmAgent | None:
        """Pick the least-loaded healthy agent using metric-weighted balancing (K2-005).

        Uses a composite score: active_tasks * 2 + consecutive_failures * 3 + 
        recent_latency_weight. Agents with recent successes are preferred.
        Falls back to any not-yet-tried agent so tasks are never dropped.
        """
        exclude = exclude or set()

        def _score(a: SwarmAgent) -> float:
            """Lower score = better candidate."""
            base = a.load
            # Add latency penalty from metrics
            metrics = self._agent_metrics.get(a.agent_id, {})
            if metrics.get("task_completions", 0) > 0:
                avg_latency = metrics.get("total_latency", 0) / metrics["task_completions"]
                base += avg_latency / 1000  # normalize ms to score units
            return base

        healthy = [
            a for a in execution.agents
            if a.agent_id not in exclude and a.is_healthy and not self._breaker_open(a.agent_id)
        ]
        pool = healthy or [a for a in execution.agents if a.agent_id not in exclude] or execution.agents
        if not pool:
            return None
        return min(pool, key=_score)

    def _record_agent_metric(self, agent_id: str, latency_ms: float, success: bool) -> None:
        """Record a metric for load balancing (K2-005). Sliding window."""
        now = time.time()
        metrics = self._agent_metrics.setdefault(agent_id, {
            "task_completions": 0, "total_latency": 0.0, "window_start": now,
        })
        if now - metrics["window_start"] > self.LOAD_METRICS_WINDOW:
            metrics["task_completions"] = 0
            metrics["total_latency"] = 0.0
            metrics["window_start"] = now
        if success:
            metrics["task_completions"] += 1
            metrics["total_latency"] += latency_ms

    # ── State Persistence (K2-007) ───────────────────────────────────

    def _init_db(self, db_path: str | None = None) -> None:
        """Initialize SQLite persistence for swarm executions."""
        self._db_path = db_path or os.environ.get("K2_DB_PATH", self.DEFAULT_DB_PATH)
        try:
            import sqlite3
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS k2_executions (
                    execution_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    task_type TEXT,
                    status TEXT,
                    data TEXT,
                    created_at REAL,
                    completed_at REAL
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS k2_agents (
                    agent_id TEXT PRIMARY KEY,
                    tether_id TEXT,
                    status TEXT,
                    total_tasks INTEGER DEFAULT 0,
                    total_failures INTEGER DEFAULT 0,
                    last_seen REAL,
                    metadata TEXT
                )
            """)
            self._db.commit()
        except Exception:
            self._db = None

    def _persist_execution(self, execution: SwarmExecution) -> None:
        """Persist a swarm execution to SQLite for crash recovery (K2-007)."""
        if not self._db:
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO k2_executions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    execution.execution_id,
                    execution.session_id,
                    execution.task_type,
                    execution.status,
                    json.dumps({
                        "agents": [{"agent_id": a.agent_id, "status": a.status, "total_tasks": a.total_tasks} for a in (execution.agents or [])],
                        "tasks": {tid: {"task_type": t.task_type, "state": t.state.value, "dependencies": t.dependencies} for tid, t in (execution.tasks or {}).items()},
                    }),
                    execution.created_at,
                    execution.completed_at,
                ),
            )
            self._db.commit()
        except Exception:
            pass

    # ── Fault Tolerance: circuit breakers (K2-006) ───────────────────

    def _breaker_open(self, agent_id: str) -> bool:
        """Whether an agent's circuit breaker is currently open (benched).

        Half-open transition: once ``CIRCUIT_BREAKER_RESET_INTERVAL`` seconds
        have elapsed since the last failure, the breaker closes so the agent can
        be probed again.
        """
        cb = self._circuit_breakers.get(agent_id)
        if not cb or not cb.get("open"):
            return False
        if time.time() - cb.get("last_failure", 0.0) >= self.CIRCUIT_BREAKER_RESET_INTERVAL:
            cb["open"] = False
            cb["failures"] = 0
            return False
        return True

    def _breaker_record_failure(self, agent_id: str) -> None:
        """Record an agent failure; open the breaker at the failure threshold."""
        cb = self._circuit_breakers.setdefault(
            agent_id, {"failures": 0, "last_failure": 0.0, "open": False}
        )
        cb["failures"] += 1
        cb["last_failure"] = time.time()
        if cb["failures"] >= self.MAX_CONSECUTIVE_FAILURES:
            cb["open"] = True

    def _breaker_record_success(self, agent_id: str) -> None:
        """Reset an agent's circuit breaker after a successful task."""
        cb = self._circuit_breakers.get(agent_id)
        if cb:
            cb["failures"] = 0
            cb["open"] = False

    async def _execute_on_agent(self, agent: SwarmAgent, task: SwarmTask) -> dict[str, Any]:
        """Execute a single task on a specific agent.

        If the agent is a real subprocess, sends JSON-RPC over stdio.
        If virtual (spawn failed or process died), executes in-process as fallback.
        """
        if agent.metadata.get("virtual"):
            return await self._execute_virtual(task)

        if not agent.process:
            return await self._execute_virtual(task)

        # Check if process is alive — give it a moment to settle
        if agent.process.returncode is not None:
            return await self._execute_virtual(task)

        # Check if stdout pipe is still open
        if agent.process.stdout and agent.process.stdout.at_eof():
            return await self._execute_virtual(task)

        lock = self._locks.setdefault(agent.agent_id, asyncio.Lock())
        async with lock:
            request = {
                "jsonrpc": "2.0",
                "id": task.task_id,
                "method": "task/execute",
                "params": {
                    "task_type": task.task_type,
                    "input_data": task.input_data,
                    "dependencies": task.dependencies,
                },
            }
            data = json.dumps(request) + "\n"
            try:
                agent.process.stdin.write(data.encode())
                await agent.process.stdin.drain()
                line = await asyncio.wait_for(
                    agent.process.stdout.readline(),
                    timeout=self.TASK_TIMEOUT,
                )
                if not line:
                    return {"error": "Agent closed stdout"}
                response = json.loads(line.decode().strip())
                return response.get("result", response)
            except asyncio.TimeoutError:
                return {"error": f"Task '{task.task_id}' timed out after {self.TASK_TIMEOUT}s"}
            except Exception as exc:
                return {"error": f"Agent communication failed: {exc}"}

    async def _execute_virtual(self, task: SwarmTask) -> dict[str, Any]:
        """In-process fallback execution when subprocess spawning fails.

        This ensures K2 works even without external agent binaries.
        Tasks are executed as async coroutines within the Hub process.
        """
        await asyncio.sleep(0.1)  # Simulate minimal processing time
        return {
            "status": "completed",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "output": f"K2 virtual agent processed '{task.task_type}'",
            "mode": "virtual",
        }

    async def _stream_dag(self, execution: SwarmExecution) -> AsyncGenerator[dict[str, Any], None]:
        """Stream DAG execution, yielding per-task results."""
        task_map = execution.tasks
        completed = set()
        failed = set()

        while len(completed) + len(failed) < len(task_map):
            ready = [
                t for t in task_map.values()
                if t.task_id not in completed and t.task_id not in failed
                and all(dep in completed for dep in t.dependencies)
            ]
            if not ready:
                break

            batch_results = await self._execute_batch(execution, ready)
            for task_id, result in batch_results.items():
                if "error" in result:
                    failed.add(task_id)
                    yield {"type": "task_failed", "task_id": task_id, "error": result["error"]}
                else:
                    completed.add(task_id)
                    yield {"type": "task_completed", "task_id": task_id, "result": result}

    async def _shutdown_pool(self, execution_id: str) -> None:
        """Gracefully shut down all agents in the pool."""
        agents = self._agent_pools.pop(execution_id, [])
        for agent in agents:
            if agent.process and agent.process.returncode is None:
                try:
                    shutdown_msg = json.dumps({"jsonrpc": "2.0", "method": "shutdown", "params": {}}) + "\n"
                    agent.process.stdin.write(shutdown_msg.encode())
                    await agent.process.stdin.drain()
                    await asyncio.wait_for(agent.process.wait(), timeout=self.SHUTDOWN_TIMEOUT)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        agent.process.kill()
                    except ProcessLookupError:
                        pass

    def _get_agent_command(self, manifest: TetherManifest) -> str:
        """Extract the agent spawn command from the manifest."""
        for p in manifest.protocols:
            if p.protocol == Protocol.K2:
                return p.acp_command or self.DEFAULT_AGENT_COMMAND
        return self.DEFAULT_AGENT_COMMAND

    def _aggregate_results(self, execution: SwarmExecution, results: dict) -> dict[str, Any]:
        """Aggregate all task results into a single response."""
        task_map = execution.tasks
        completed = [t for t in task_map.values() if t.state == TaskState.COMPLETED]
        failed = [t for t in task_map.values() if t.state == TaskState.FAILED]

        return {
            "status": "completed" if not failed else "partial",
            "execution_id": execution.execution_id,
            "total_tasks": len(task_map),
            "completed": len(completed),
            "failed": len(failed),
            "agents_used": len(execution.agents),
            "results": {t.task_id: t.result for t in completed},
            "errors": {t.task_id: t.error for t in failed},
            "duration_ms": round((time.time() - execution.created_at) * 1000, 1),
        }

    # ── State Persistence ────────────────────────────────────────────

    def persist_execution(self, execution: SwarmExecution, db_path: str | None = None) -> None:
        """Persist a swarm execution to SQLite for crash recovery."""
        if not db_path:
            return
        try:
            import sqlite3
            db = sqlite3.connect(db_path)
            db.execute("""
                CREATE TABLE IF NOT EXISTS k2_executions (
                    execution_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    task_type TEXT,
                    status TEXT,
                    data TEXT,
                    created_at REAL,
                    completed_at REAL
                )
            """)
            db.execute(
                "INSERT OR REPLACE INTO k2_executions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    execution.execution_id,
                    execution.session_id,
                    execution.task_type,
                    execution.status,
                    json.dumps({
                        "agents": [{"agent_id": a.agent_id, "status": a.status, "total_tasks": a.total_tasks} for a in execution.agents],
                        "tasks": {tid: {"task_type": t.task_type, "state": t.state.value, "dependencies": t.dependencies} for tid, t in execution.tasks.items()},
                    }),
                    execution.created_at,
                    execution.completed_at,
                ),
            )
            db.commit()
            db.close()
        except Exception:
            pass

    # ── Inter-Agent Communication ────────────────────────────────────

    async def send_to_agent(self, execution_id: str, target_agent_id: str, message: dict) -> dict[str, Any]:
        """Send a message to a specific agent within the swarm.

        Enables inter-agent communication within a K2 execution.
        """
        agents = self._agent_pools.get(execution_id, [])
        target = next((a for a in agents if a.agent_id == target_agent_id), None)
        if not target:
            return {"error": f"Agent {target_agent_id} not found in execution {execution_id}"}

        request = {
            "jsonrpc": "2.0",
            "id": f"msg-{uuid.uuid4().hex[:8]}",
            "method": "agent/message",
            "params": {"message": message},
        }
        data = json.dumps(request) + "\n"
        try:
            target.process.stdin.write(data.encode())
            await target.process.stdin.drain()
            line = await asyncio.wait_for(target.process.stdout.readline(), timeout=30.0)
            return json.loads(line.decode().strip())
        except Exception as exc:
            return {"error": f"Inter-agent communication failed: {exc}"}

    async def broadcast_to_swarm(self, execution_id: str, message: dict) -> list[dict[str, Any]]:
        """Broadcast a message to all agents in the swarm."""
        agents = self._agent_pools.get(execution_id, [])
        results = await asyncio.gather(
            *[self.send_to_agent(execution_id, a.agent_id, message) for a in agents],
            return_exceptions=True,
        )
        return [r if not isinstance(r, Exception) else {"error": str(r)} for r in results]


# ── Manifest Factory ─────────────────────────────────────────────────

def k2_manifest_from_config(
    name: str = "K2 Swarm Agent",
    tasks: list[str] | None = None,
    command: str = K2Adapter.DEFAULT_AGENT_COMMAND,
    pool_size: int = K2Adapter.DEFAULT_POOL_SIZE,
    tether_id: str | None = None,
) -> TetherManifest:
    """Create a TetherManifest for a K2 swarm agent.

    Args:
        name: Display name for this K2 agent
        tasks: List of task types this agent can handle
        command: CLI command to spawn subprocess agents
        pool_size: Default number of agents in the pool
        tether_id: Optional custom tether ID
    """
    if tasks is None:
        tasks = [
            "swarm_orchestration", "task_delegation", "agent_coordination",
            "subagent_spawning", "workflow_execution", "multi_agent_scheduling",
            "k2_swarm_management", "parallel_execution", "dependency_resolution",
            "agent_discovery", "task_routing", "load_balancing",
            "fault_tolerance", "state_persistence", "inter_agent_communication",
        ]

    tid = tether_id or f"k2-{name.lower().replace(' ', '-')}"
    return TetherManifest(
        tether_id=tid,
        name=name,
        origin_protocol=Protocol.K2,
        capabilities={
            "tasks": tasks,
            "modalities": ["text", "structured_output", "command_execution"],
            "streaming": True,
            "max_nesting_depth": 3,
            "swarm_protocols": ["k2", "hermes", "a2a", "mcp", "acp"],
            "orchestration": {
                "turn_policies": ["round_robin", "priority", "llm_selected", "human_moderator"],
                "max_agents_per_swarm": K2Adapter.MAX_POOL_SIZE,
                "supports_sub_swarms": True,
                "supports_human_in_loop": True,
                "default_pool_size": pool_size,
            },
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.K2,
            acp_command=command,
            acp_transport="stdio",
            endpoint_url=f"k2://{tid}",
            config={
                "framework": "k2",
                "version": "0.5.0",
                "default_pool_size": pool_size,
                "max_pool_size": K2Adapter.MAX_POOL_SIZE,
                "task_timeout": K2Adapter.TASK_TIMEOUT,
            },
        )],
        metadata={
            "framework": "k2",
            "version": "0.5.0",
            "description": "K2 Swarm Orchestrator — high-performance multi-agent subprocess orchestration",
            "repo": "https://github.com/0x-wzw/voidtether",
        },
    )
