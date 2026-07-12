"""Hub lifecycle logger — records restarts, restored sessions, and lost state.

Writes to a rotating SQLite changelog so the mesh always knows what
happened during downtime, even if in-memory state was wiped.
"""

from __future__ import annotations
import os
import json
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger("voidtether.lifecycle")

CHANGE_LOG_PATH = os.environ.get("VOIDTETHER_CHANGE_LOG", "/tmp/voidtether_changelog.db")


class ChangeLog:
    """Persistent changelog of hub lifecycle events.
    
    Records every startup, shutdown, session-dropped, agent-dropped,
    and task-interrupted event so operators can audit what was lost
    during a restart.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or CHANGE_LOG_PATH
        self._db = None
        self._init_db()

    def _init_db(self):
        try:
            import sqlite3
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS changelog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS hub_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            self._db.commit()
        except Exception:
            self._db = None

    def record(self, event_type: str, data: dict) -> None:
        """Record a lifecycle event."""
        if not self._db:
            return
        try:
            self._db.execute(
                "INSERT INTO changelog (event_type, timestamp, data) VALUES (?, ?, ?)",
                (event_type, datetime.now(timezone.utc).isoformat(), json.dumps(data)),
            )
            self._db.commit()
        except Exception:
            pass

    # ── Audit logging for agent operations ────────────────────────────

    def record_audit(self, agent_id: str, action: str, source_ip: str, details: dict | None = None) -> None:
        """Record an audit event (register, deregister, create_session, delete_session).

        The 'action' should be one of: register_agent, unregister_agent,
        create_session, delete_session.
        """
        self.record(f"audit_{action}", {
            "agent_id": agent_id,
            "action": action,
            "source_ip": source_ip or "unknown",
            "details": details or {},
        })

    def get_audit_events(self, limit: int = 100, action: str | None = None) -> list[dict]:
        """Get recent audit events, optionally filtered by action type."""
        if not self._db:
            return []
        try:
            if action:
                cursor = self._db.execute(
                    "SELECT id, event_type, timestamp, data FROM changelog WHERE event_type = ? ORDER BY id DESC LIMIT ?",
                    (f"audit_{action}", limit),
                )
            else:
                cursor = self._db.execute(
                    "SELECT id, event_type, timestamp, data FROM changelog WHERE event_type LIKE 'audit_%' ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            return [
                {"id": r[0], "event_type": r[1], "timestamp": r[2], "data": json.loads(r[3])}
                for r in cursor.fetchall()
            ]
        except Exception:
            return []

    def record_startup(self, restored_sessions: int, restored_agents: int, dropped_sessions: list[str], dropped_agents: list[str]) -> None:
        """Record a hub startup event with restoration summary."""
        self.record("hub_startup", {
            "restored_sessions": restored_sessions,
            "restored_agents": restored_agents,
            "dropped_sessions": dropped_sessions,
            "dropped_agents": dropped_agents,
            "session_ids_restored": dropped_sessions,  # sessions that existed before restart
            "agent_ids_restored": dropped_agents,
        })

    def record_shutdown(self, active_sessions: int, active_agents: int) -> None:
        """Record a hub shutdown."""
        self.record("hub_shutdown", {
            "active_sessions": active_sessions,
            "active_agents": active_agents,
            "shutdown_time": datetime.now(timezone.utc).isoformat(),
        })

    def record_session_dropped(self, session_id: str, title: str, messages: int) -> None:
        """Record a session lost during restart."""
        self.record("session_dropped", {
            "session_id": session_id,
            "title": title,
            "messages": messages,
            "reason": "in_memory_only_not_persisted_to_sqlite",
        })

    def record_agent_dropped(self, agent_id: str, name: str, protocol: str) -> None:
        """Record an agent lost during restart."""
        self.record("agent_dropped", {
            "agent_id": agent_id,
            "name": name,
            "protocol": protocol,
            "reason": "in_memory_only_not_persisted_to_sqlite",
        })

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        """Get recent changelog events."""
        if not self._db:
            return []
        try:
            cursor = self._db.execute(
                "SELECT id, event_type, timestamp, data FROM changelog ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [
                {"id": r[0], "event_type": r[1], "timestamp": r[2], "data": json.loads(r[3])}
                for r in cursor.fetchall()
            ]
        except Exception:
            return []

    def save_pre_shutdown_state(self, sessions: list[dict], agents: list[dict]) -> None:
        """Save the pre-shutdown state so we know what was lost on next startup."""
        if not self._db:
            return
        try:
            data = json.dumps({
                "sessions": sessions,
                "agents": agents,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self._db.execute(
                "INSERT OR REPLACE INTO hub_state (key, value, updated_at) VALUES (?, ?, ?)",
                ("pre_shutdown_state", data, datetime.now(timezone.utc).isoformat()),
            )
            self._db.commit()
        except Exception:
            pass

    def get_pre_shutdown_state(self) -> dict | None:
        """Get the last saved pre-shutdown state."""
        if not self._db:
            return None
        try:
            cursor = self._db.execute("SELECT value FROM hub_state WHERE key = ?", ("pre_shutdown_state",))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception:
            pass
        return None

    def diff_shutdown_vs_startup(self, current_sessions: list[str], current_agents: list[str]) -> dict:
        """Compare what we had before shutdown vs what we have now."""
        pre = self.get_pre_shutdown_state()
        if not pre:
            return {"dropped_sessions": [], "dropped_agents": []}

        pre_sessions = {s.get("session_id") for s in pre.get("sessions", [])}
        pre_agents = {a.get("tether_id") for a in pre.get("agents", [])}
        current_session_set = set(current_sessions)
        current_agent_set = set(current_agents)

        return {
            "dropped_sessions": list(pre_sessions - current_session_set),
            "dropped_agents": list(pre_agents - current_agent_set),
            "session_details": [s for s in pre.get("sessions", []) if s.get("session_id") in pre_sessions - current_session_set],
            "agent_details": [a for a in pre.get("agents", []) if a.get("tether_id") in pre_agents - current_agent_set],
        }


# Global singleton
_changelog: ChangeLog | None = None


def get_changelog() -> ChangeLog:
    global _changelog
    if _changelog is None:
        _changelog = ChangeLog()
    return _changelog
