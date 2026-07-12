"""Agent Persistence Manager — SQLite-backed agent registry that survives restarts.

Every agent that registers is persisted to SQLite immediately. On hub startup,
all persisted agents are reloaded into the mesh router. This eliminates 
agent drop-off during reboots — agents stay registered until explicitly
deregistered, even across hub restarts.

Combined with the SessionManager's SQLite persistence, this means BOTH
sessions AND agents survive restarts. Only in-flight task state is lost.
"""

from __future__ import annotations
import json
import os
import time
from typing import Any

from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


class AgentPersistence:
    """SQLite-backed agent registry.

    Usage:
        ap = AgentPersistence("/tmp/vt_agents.db")
        ap.persist(manifest)        # save agent on register
        ap.load_all()               # reload all agents on startup
        ap.remove(tether_id)        # remove on deregister
    """

    DEFAULT_DB_PATH = "/tmp/vt_agents.db"

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or os.environ.get("VOIDTETHER_AGENT_DB", self.DEFAULT_DB_PATH)
        self._db = None
        self._init_db()

    def _init_db(self):
        """Initialize SQLite agent registry."""
        try:
            import sqlite3
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    tether_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    capabilities TEXT NOT NULL,
                    protocols_json TEXT DEFAULT '[]',
                    authentication TEXT DEFAULT '{}',
                    metadata TEXT DEFAULT '{}',
                    registered_at REAL NOT NULL,
                    last_seen REAL NOT NULL
                )
            """)
            self._db.commit()
        except Exception:
            self._db = None

    def persist(self, manifest: TetherManifest) -> None:
        """Save an agent manifest to SQLite."""
        if not self._db:
            return
        try:
            now = time.time()
            # Try update first (re-registration), then insert
            self._db.execute("""
                INSERT OR REPLACE INTO agents 
                (tether_id, name, protocol, capabilities, protocols_json, authentication, metadata, registered_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT registered_at FROM agents WHERE tether_id = ?), ?), ?)
            """, (
                manifest.tether_id,
                manifest.name,
                manifest.origin_protocol.value,
                json.dumps(manifest.capabilities),
                json.dumps([self._endpoint_to_dict(p) for p in manifest.protocols]),
                json.dumps(manifest.authentication),
                json.dumps(manifest.metadata),
                manifest.tether_id,  # for COALESCE
                now,
                now,
            ))
            self._db.commit()
        except Exception:
            pass

    def remove(self, tether_id: str) -> None:
        """Remove an agent from SQLite."""
        if not self._db:
            return
        try:
            self._db.execute("DELETE FROM agents WHERE tether_id = ?", (tether_id,))
            self._db.commit()
        except Exception:
            pass

    def load_all(self) -> list[TetherManifest]:
        """Load all persisted agents from SQLite.

        Returns a list of TetherManifest objects ready for mesh.register().
        """
        if not self._db:
            return []
        manifests = []
        try:
            cursor = self._db.execute("SELECT * FROM agents")
            for row in cursor.fetchall():
                try:
                    tether_id, name, protocol_str, caps_json, prots_json, auth_json, meta_json, reg_at, last_seen = row
                    manifest = TetherManifest(
                        tether_id=tether_id,
                        name=name,
                        origin_protocol=Protocol(protocol_str),
                        capabilities=json.loads(caps_json),
                        protocols=[self._dict_to_endpoint(p) for p in json.loads(prots_json)],
                        authentication=json.loads(auth_json),
                        metadata=json.loads(meta_json),
                    )
                    # Preserve registration timestamp
                    if "registered_at" not in manifest.metadata:
                        manifest.metadata["registered_at"] = reg_at
                    if "last_seen" not in manifest.metadata:
                        manifest.metadata["last_seen"] = last_seen
                    manifests.append(manifest)
                except Exception:
                    continue
        except Exception:
            pass
        return manifests

    def _endpoint_to_dict(self, p: ProtocolEndpoint) -> dict:
        """Serialize a ProtocolEndpoint to dict."""
        return {
            "protocol": p.protocol.value,
            "config": p.config,
            "agent_card_url": p.agent_card_url,
            "tools": p.tools,
            "skill": p.skill,
            "agent_fn": p.agent_fn,
            "role": p.role,
            "node_id": p.node_id,
            "endpoint_url": p.endpoint_url,
            "acp_command": p.acp_command,
            "acp_transport": p.acp_transport,
        }

    def _dict_to_endpoint(self, d: dict) -> ProtocolEndpoint:
        """Convert a dict back to a ProtocolEndpoint."""
        return ProtocolEndpoint(
            protocol=Protocol(d.get("protocol", "custom")),
            config=d.get("config", {}),
            agent_card_url=d.get("agent_card_url"),
            tools=d.get("tools", []),
            skill=d.get("skill"),
            agent_fn=d.get("agent_fn"),
            role=d.get("role"),
            node_id=d.get("node_id"),
            endpoint_url=d.get("endpoint_url"),
            acp_command=d.get("acp_command"),
            acp_transport=d.get("acp_transport", "stdio"),
        )

    def list_persisted(self) -> list[dict]:
        """List all persisted agents as plain dicts (for API)."""
        if not self._db:
            return []
        try:
            cursor = self._db.execute("SELECT tether_id, name, protocol, capabilities, registered_at, last_seen FROM agents ORDER BY registered_at DESC")
            return [
                {
                    "tether_id": r[0],
                    "name": r[1],
                    "protocol": r[2],
                    "capabilities": json.loads(r[3]),
                    "registered_at": r[4],
                    "last_seen": r[5],
                }
                for r in cursor.fetchall()
            ]
        except Exception:
            return []

    def get_persisted(self, tether_id: str) -> dict | None:
        """Get a single persisted agent."""
        if not self._db:
            return None
        try:
            cursor = self._db.execute("SELECT tether_id, name, protocol, capabilities, registered_at, last_seen FROM agents WHERE tether_id = ?", (tether_id,))
            row = cursor.fetchone()
            if row:
                return {"tether_id": row[0], "name": row[1], "protocol": row[2], "capabilities": json.loads(row[3]), "registered_at": row[4], "last_seen": row[5]}
        except Exception:
            pass
        return None

    def update_last_seen(self, tether_id: str) -> None:
        """Update the last_seen timestamp for an agent (call on heartbeat)."""
        if not self._db:
            return
        try:
            self._db.execute("UPDATE agents SET last_seen = ? WHERE tether_id = ?", (time.time(), tether_id))
            self._db.commit()
        except Exception:
            pass

    def count(self) -> int:
        """Count persisted agents."""
        if not self._db:
            return 0
        try:
            cursor = self._db.execute("SELECT COUNT(*) FROM agents")
            return cursor.fetchone()[0]
        except Exception:
            return 0

    def close(self):
        """Close the database connection."""
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None


# Global singleton
_agent_db: AgentPersistence | None = None


def get_agent_db() -> AgentPersistence:
    global _agent_db
    if _agent_db is None:
        _agent_db = AgentPersistence()
    return _agent_db
