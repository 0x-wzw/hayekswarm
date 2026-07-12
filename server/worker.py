"""HayekSwarm Marketplace — Background worker that runs the Hayek economy."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Optional

from server.database import Database
from swarm.council.council import Council
from swarm.council.dimension_map import DIMENSION_MAP, DIMENSION_ORDER, get_tier_for_dimension

logger = logging.getLogger(__name__)


class MarketWorker:
    """Background worker that processes tasks through the Hayek economy.

    Polls the database for pending tasks, runs them through the Council
    auction, and records results.
    """

    def __init__(
        self,
        db: Database,
        poll_interval: float = 1.0,
        max_concurrent: int = 3,
    ):
        self.db = db
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._council: Optional[Council] = None
        self._active_tasks: set[int] = set()

    def start(self):
        """Start the worker thread."""
        if self._running:
            return
        self._running = True
        self._init_council()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="market-worker")
        self._thread.start()
        logger.info("Market worker started (poll_interval=%.1fs, max_concurrent=%d)", self.poll_interval, self.max_concurrent)

    def stop(self):
        """Stop the worker thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Market worker stopped")

    def _init_council(self):
        """Initialize the 10-D Council from the database or defaults."""
        self._council = Council(initial_wealth=100.0, base_bid=1.0, bid_scheme="holland")

        # Restore agent state from database if it exists
        db_agents = self.db.list_agents()
        if db_agents:
            for agent_data in db_agents:
                ca = self._council.get_agent_by_dimension(agent_data["dimension"])
                if ca:
                    ca.agent.wealth = agent_data["wealth"]
                    ca.agent.status = type(ca.agent.status)(agent_data["status"])
                    ca.agent.total_tasks = agent_data["total_tasks"]
                    ca.agent.total_reward = agent_data["total_reward"]
                    ca.wins = agent_data["wins"]
                    ca.losses = agent_data["losses"]
                    ca.last_bid_amount = agent_data["last_bid"]
            logger.info("Council restored from database (%d agents)", len(db_agents))
        else:
            # First run: persist initial agent state
            self._sync_council_to_db()
            logger.info("Council initialized with default agents")

    def _sync_council_to_db(self):
        """Persist current council agent state to the database."""
        if not self._council:
            return
        for ca in self._council.get_all_agents():
            self.db.upsert_agent(
                dimension=ca.dimension,
                name=ca.name,
                model=ca.model,
                wealth=ca.agent.wealth,
                status=ca.agent.status.value,
                wins=ca.wins,
                losses=ca.losses,
                total_tasks=ca.agent.total_tasks,
                total_reward=ca.agent.total_reward,
                last_bid=ca.last_bid_amount,
                tier=get_tier_for_dimension(ca.dimension),
                capabilities=json.dumps(ca.agent.capabilities),
                lineage=json.dumps(ca.agent.lineage),
            )

    def _run_loop(self):
        """Main worker loop: poll for tasks, process them."""
        while self._running:
            try:
                self._process_pending_tasks()
            except Exception as e:
                logger.error("Worker loop error: %s", e)
            time.sleep(self.poll_interval)

    def _process_pending_tasks(self):
        """Fetch and process pending tasks up to max_concurrent."""
        available = self.max_concurrent - len(self._active_tasks)
        if available <= 0:
            return

        tasks = self.db.get_pending_tasks(limit=available)
        for task in tasks:
            task_id = task["id"]
            if task_id in self._active_tasks:
                continue
            self._active_tasks.add(task_id)
            threading.Thread(
                target=self._process_task,
                args=(task,),
                daemon=True,
                name=f"task-{task_id}",
            ).start()

    def _process_task(self, task: dict):
        """Process a single task through the Council auction."""
        task_id = task["id"]
        logger.info("Processing task %d: %s...", task_id, task["content"][:80])

        try:
            # Mark as auctioning
            self.db.update_task(task_id, status="auctioning")

            # Build task dict for council
            task_dict = {
                "content": task["content"],
                "stakes": task.get("stakes", "medium"),
                "dimensions": task.get("dimensions", []),
                "capabilities": task.get("capabilities", []),
            }

            # Run the auction
            result = self._council.deliberate(task_dict)

            if result.winner is None:
                self.db.update_task(
                    task_id,
                    status="failed",
                    completed_at=datetime.utcnow().isoformat(),
                    error="No eligible agents found for task",
                )
                logger.warning("Task %d: no eligible agents", task_id)
                return

            # Record the transaction
            self.db.create_transaction(
                task_id=task_id,
                agent_dimension=result.winner.dimension,
                agent_name=result.winner.name,
                bid_amount=result.winning_bid,
                reward_amount=0.0,  # Will be updated when task completes
            )

            # Mark as running
            self.db.update_task(
                task_id,
                status="running",
                winner_dimension=result.winner.dimension,
                winner_name=result.winner.name,
                winning_bid=result.winning_bid,
            )

            # The agent's act() already ran during deliberate()
            # Extract the response from the result
            response_text = result.winner.agent._last_response if hasattr(result.winner.agent, "_last_response") else ""
            if not response_text:
                # Try to get it from the auction result's task
                response_text = result.task.get("_response", "")

            # Calculate cost (simplified: bid * 2 for profit margin)
            total_cost = result.winning_bid * 2

            # Mark as completed
            self.db.update_task(
                task_id,
                status="completed",
                completed_at=datetime.utcnow().isoformat(),
                result=response_text,
                total_cost=total_cost,
            )

            # Sync agent state to DB
            self._sync_council_to_db()

            logger.info(
                "Task %d completed: won by %s (%s) for $%.2f",
                task_id,
                result.winner.name,
                result.winner.dimension,
                result.winning_bid,
            )

        except Exception as e:
            logger.error("Task %d failed: %s", task_id, e)
            self.db.update_task(
                task_id,
                status="failed",
                completed_at=datetime.utcnow().isoformat(),
                error=f"{type(e).__name__}: {e}",
            )
        finally:
            self._active_tasks.discard(task_id)

    @property
    def council(self) -> Optional[Council]:
        return self._council

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "active_tasks": len(self._active_tasks),
            "council_agents": len(self._council.get_all_agents()) if self._council else 0,
            "council_active": self._council.active_count() if self._council else 0,
        }
