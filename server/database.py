"""HayekSwarm Marketplace — SQLite persistence layer."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class Database:
    """SQLite-backed persistence for the HayekSwarm marketplace."""

    def __init__(self, db_path: str | Path = "hayekswarm.db"):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS api_keys (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    label       TEXT NOT NULL,
                    key         TEXT NOT NULL UNIQUE,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    last_used_at TEXT,
                    is_active   INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_key_id      INTEGER REFERENCES api_keys(id),
                    status          TEXT NOT NULL DEFAULT 'pending',
                    content         TEXT NOT NULL,
                    stakes          TEXT NOT NULL DEFAULT 'medium',
                    dimensions      TEXT NOT NULL DEFAULT '[]',
                    capabilities    TEXT NOT NULL DEFAULT '[]',
                    max_bid         REAL NOT NULL DEFAULT 10.0,
                    callback_url    TEXT,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    completed_at    TEXT,
                    winner_dimension TEXT,
                    winner_name     TEXT,
                    winning_bid     REAL,
                    result          TEXT,
                    error           TEXT,
                    total_cost      REAL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    dimension   TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    model       TEXT NOT NULL,
                    wealth      REAL NOT NULL DEFAULT 100.0,
                    status      TEXT NOT NULL DEFAULT 'novice',
                    wins        INTEGER NOT NULL DEFAULT 0,
                    losses      INTEGER NOT NULL DEFAULT 0,
                    total_tasks INTEGER NOT NULL DEFAULT 0,
                    total_reward REAL NOT NULL DEFAULT 0.0,
                    last_bid    REAL NOT NULL DEFAULT 1.0,
                    tier        TEXT NOT NULL DEFAULT 'T2',
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    lineage     TEXT NOT NULL DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id         INTEGER REFERENCES tasks(id),
                    agent_dimension TEXT NOT NULL,
                    agent_name      TEXT NOT NULL,
                    bid_amount      REAL NOT NULL,
                    reward_amount   REAL NOT NULL DEFAULT 0.0,
                    net_change      REAL NOT NULL,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_api_key ON tasks(api_key_id);
                CREATE INDEX IF NOT EXISTS idx_transactions_task ON transactions(task_id);
                CREATE INDEX IF NOT EXISTS idx_transactions_agent ON transactions(agent_dimension);
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── API Keys ──────────────────────────────────────────────────────────────

    def create_api_key(self, label: str, key: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO api_keys (label, key) VALUES (?, ?)", (label, key)
            )
            return cur.lastrowid

    def get_api_key(self, key: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key = ? AND is_active = 1", (key,)
            ).fetchone()
            return dict(row) if row else None

    def touch_api_key(self, key_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?",
                (key_id,),
            )

    def list_api_keys(self) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, label, key, created_at, last_used_at, is_active FROM api_keys ORDER BY created_at DESC"
            ).fetchall()]

    def deactivate_api_key(self, key_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def create_task(
        self,
        content: str,
        stakes: str = "medium",
        dimensions: list[str] | None = None,
        capabilities: list[str] | None = None,
        max_bid: float = 10.0,
        callback_url: str | None = None,
        api_key_id: int | None = None,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO tasks (api_key_id, content, stakes, dimensions, capabilities, max_bid, callback_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    api_key_id,
                    content,
                    stakes,
                    json.dumps(dimensions or []),
                    json.dumps(capabilities or []),
                    max_bid,
                    callback_url,
                ),
            )
            return cur.lastrowid

    def get_task(self, task_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None

    def update_task(self, task_id: int, **kwargs):
        allowed = {
            "status", "completed_at", "winner_dimension", "winner_name",
            "winning_bid", "result", "error", "total_cost",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)

    def list_tasks(
        self,
        status: str | None = None,
        api_key_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        where = []
        params = []
        if status:
            where.append("status = ?")
            params.append(status)
        if api_key_id is not None:
            where.append("api_key_id = ?")
            params.append(api_key_id)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            return [self._row_to_task(r) for r in rows]

    def get_pending_tasks(self, limit: int = 5) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_task(r) for r in rows]

    def _row_to_task(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["dimensions"] = json.loads(d.get("dimensions", "[]"))
        d["capabilities"] = json.loads(d.get("capabilities", "[]"))
        return d

    # ── Agents ────────────────────────────────────────────────────────────────

    def upsert_agent(self, dimension: str, **kwargs):
        allowed = {
            "name", "model", "wealth", "status", "wins", "losses",
            "total_tasks", "total_reward", "last_bid", "tier", "capabilities", "lineage",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [dimension]
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO agents (dimension, {', '.join(updates.keys())}) "
                f"VALUES (?, {', '.join('?' for _ in updates)}) "
                f"ON CONFLICT(dimension) DO UPDATE SET {set_clause}",
                [dimension] + list(updates.values()),
            )

    def get_agent(self, dimension: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM agents WHERE dimension = ?", (dimension,)).fetchone()
            return self._row_to_agent(row) if row else None

    def list_agents(self) -> list[dict]:
        with self._conn() as conn:
            return [
                self._row_to_agent(r)
                for r in conn.execute("SELECT * FROM agents ORDER BY wealth DESC").fetchall()
            ]

    def _row_to_agent(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["capabilities"] = json.loads(d.get("capabilities", "[]"))
        d["lineage"] = json.loads(d.get("lineage", "[]"))
        return d

    # ── Transactions ──────────────────────────────────────────────────────────

    def create_transaction(
        self,
        task_id: int,
        agent_dimension: str,
        agent_name: str,
        bid_amount: float,
        reward_amount: float = 0.0,
    ) -> int:
        net_change = reward_amount - bid_amount
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO transactions (task_id, agent_dimension, agent_name, bid_amount, reward_amount, net_change)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (task_id, agent_dimension, agent_name, bid_amount, reward_amount, net_change),
            )
            return cur.lastrowid

    def list_transactions(
        self, task_id: int | None = None, agent_dimension: str | None = None, limit: int = 50
    ) -> list[dict]:
        where = []
        params = []
        if task_id is not None:
            where.append("task_id = ?")
            params.append(task_id)
        if agent_dimension:
            where.append("agent_dimension = ?")
            params.append(agent_dimension)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM transactions {where_clause} ORDER BY created_at DESC LIMIT ?",
                    params + [limit],
                ).fetchall()
            ]

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._conn() as conn:
            tasks = dict(conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending
                   FROM tasks"""
            ).fetchone())
            tx = dict(conn.execute(
                "SELECT COUNT(*) as count, COALESCE(SUM(bid_amount), 0) as revenue FROM transactions"
            ).fetchone())
            return {
                "total_tasks": tasks["total"],
                "completed_tasks": tasks["completed"],
                "failed_tasks": tasks["failed"],
                "pending_tasks": tasks["pending"],
                "total_auctions": tasks["total"],
                "total_transactions": tx["count"],
                "total_revenue": round(tx["revenue"], 4),
            }
