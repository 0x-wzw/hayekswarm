"""Session management for multi-agent conversations with turn policy enforcement."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import asyncio
import time
import uuid


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"      # Human gate waiting
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    HUMAN_GATE = "human_gate"


@dataclass
class ChatMessage:
    """A single message in a session."""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    role: MessageRole = MessageRole.USER
    sender: str = ""          # tether_id or "user"
    sender_name: str = ""     # Display name
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Protocol trace
    protocol: str = ""        # Which protocol this came from
    task_id: str = ""         # A2A/TetherTask task ID

    # Human gate
    requires_approval: bool = False
    approved: bool | None = None  # None = pending

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role.value,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "protocol": self.protocol,
            "task_id": self.task_id,
            "requires_approval": self.requires_approval,
            "approved": self.approved,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatMessage:
        return cls(
            message_id=data.get("message_id", str(uuid.uuid4())),
            session_id=data.get("session_id", ""),
            role=MessageRole(data.get("role", "user")),
            sender=data.get("sender", ""),
            sender_name=data.get("sender_name", ""),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            protocol=data.get("protocol", ""),
            task_id=data.get("task_id", ""),
            requires_approval=data.get("requires_approval", False),
            approved=data.get("approved"),
        )


@dataclass
class Session:
    """A multi-agent conversation session with turn policy enforcement."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "Untitled Session"
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Participants
    participants: list[str] = field(default_factory=list)   # tether_ids
    human_in_loop: bool = False

    # Messages
    messages: list[ChatMessage] = field(default_factory=list)

    # Configuration
    turn_policy: str = "round_robin"    # round_robin | priority | llm_selected | human_moderator
    max_turns: int = 100
    current_turn: int = 0

    # Task tracking
    active_tasks: dict[str, str] = field(default_factory=dict)  # task_id -> tether_id

    # max_messages: safety cap to prevent unbounded memory growth
    max_messages: int = 1000

    # ── Session TTL / Inactivity Timeout ──────────────────────────────
    inactivity_timeout: float | None = 3600.0  # seconds before archiving (default 1h)
    last_activity: float = 0.0                 # monotonic timestamp of last message

    # ── Turn Policy State ──────────────────────────────────────────────
    _turn_index: int = 0  # Internal pointer for round_robin

    @property
    def turn_order(self) -> list[str]:
        """Ordered list of agent tether_ids for turn-based policies."""
        return [p for p in self.participants if p != "user"]

    def can_speak(self, sender: str, role: str) -> tuple[bool, str]:
        """Check if a sender is allowed to speak under the current turn policy.

        Returns (allowed: bool, reason: str).
        System messages and human_gate messages always pass.
        """
        # System and gate messages always pass
        if role in ("system", "human_gate") or sender == "system":
            return True, "system_exempt"

        # If no turn policy enforcement for user messages
        if role == "user":
            return True, "user_free"

        # If no participants or sender is user, allow
        if not self.turn_order:
            return True, "no_agents"

        # ── Round Robin ────────────────────────────────────────────────
        if self.turn_policy == "round_robin":
            expected = self.turn_order[self._turn_index % len(self.turn_order)]
            if sender == expected:
                self._turn_index += 1
                self.current_turn += 1
                return True, "round_robin_ok"
            return False, f"round_robin: expected '{expected}', got '{sender}'"

        # ── Human Moderator ────────────────────────────────────────────
        if self.turn_policy == "human_moderator":
            # Only system/user can initiate; agents must be explicitly approved
            # This is a soft check — the message will be queued as requires_approval
            return True, "human_moderator_deferred"

        # ── Priority (by capability count — more specialized first) ────
        if self.turn_policy == "priority":
            # Allow all but track turns; priority ordering is handled at discovery
            self.current_turn += 1
            return True, "priority_ok"

        # ── LLM Selected (placeholder — orchestrator decides) ──────────
        if self.turn_policy == "llm_selected":
            # In production, an LLM orchestrator would set the next speaker.
            # For now, allow all.
            self.current_turn += 1
            return True, "llm_selected_unenforced"

        # Unknown policy: allow
        return True, "unknown_policy"

    def add_message(self, msg: ChatMessage) -> None:
        """Add a message to the session. Evicts oldest if over cap."""
        msg.session_id = self.session_id
        self.messages.append(msg)
        # Track activity for inactivity timeout
        self.last_activity = time.time()
        # Evict oldest messages when over cap (keep 80% as buffer)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-int(self.max_messages * 0.8):]
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "participants": self.participants,
            "human_in_loop": self.human_in_loop,
            "messages": [m.to_dict() for m in self.messages],
            "turn_policy": self.turn_policy,
            "max_turns": self.max_turns,
            "current_turn": self.current_turn,
            "active_tasks": self.active_tasks,
            "inactivity_timeout": self.inactivity_timeout,
            "last_activity": self.last_activity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        messages = [ChatMessage.from_dict(m) for m in data.get("messages", [])]
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            title=data.get("title", "Untitled Session"),
            status=SessionStatus(data.get("status", "active")),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            participants=data.get("participants", []),
            human_in_loop=data.get("human_in_loop", False),
            messages=messages,
            turn_policy=data.get("turn_policy", "round_robin"),
            max_turns=data.get("max_turns", 100),
            current_turn=data.get("current_turn", 0),
            active_tasks=data.get("active_tasks", {}),
            inactivity_timeout=data.get("inactivity_timeout", 3600.0),
            last_activity=data.get("last_activity", time.time()),
        )


class SessionManager:
    """In-memory session manager with optional SQLite persistence.

    Set VOIDTETHER_DB_PATH env var to enable persistence.
    Falls back to pure in-memory if not set or if sqlite3 unavailable.
    """

    # Default inactivity timeout (seconds)
    DEFAULT_INACTIVITY_TIMEOUT = 3600.0  # 1 hour
    CLEANUP_INTERVAL = 300.0             # check every 5 minutes

    def __init__(self, db_path: str | None = None):
        self._sessions: dict[str, Session] = {}
        self._db_path = db_path
        self._db = None
        self._cleanup_task: asyncio.Task | None = None
        self._running = False

        if db_path:
            self._init_db()

        # Start background cleanup loop
        self._start_cleanup()

    def _init_db(self):
        """Initialize SQLite persistence layer."""
        try:
            import sqlite3
            import json as _json
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            self._db.commit()
            self._load_all()
        except Exception:
            # Graceful fallback to in-memory
            self._db = None

    def _load_all(self):
        """Load all sessions from SQLite on startup."""
        if not self._db:
            return
        try:
            import json as _json
            cursor = self._db.execute("SELECT data FROM sessions")
            for row in cursor.fetchall():
                data = _json.loads(row[0])
                session = Session.from_dict(data)
                self._sessions[session.session_id] = session
        except Exception:
            pass

    def _persist(self, session: Session):
        """Persist a session to SQLite."""
        if not self._db:
            return
        try:
            import json as _json
            data = _json.dumps(session.to_dict())
            self._db.execute(
                "INSERT OR REPLACE INTO sessions (session_id, data, updated_at) VALUES (?, ?, ?)",
                (session.session_id, data, session.updated_at)
            )
            self._db.commit()
        except Exception:
            pass

    def create_session(self, **kwargs) -> Session:
        session = Session(**kwargs)
        self._sessions[session.session_id] = session
        self._persist(session)
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def update_session(self, session: Session) -> None:
        self._sessions[session.session_id] = session
        self._persist(session)

    def delete_session(self, session_id: str) -> bool:
        removed = self._sessions.pop(session_id, None) is not None
        if removed and self._db:
            try:
                self._db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                self._db.commit()
            except Exception:
                pass
        return removed

    def add_message(self, session_id: str, message: ChatMessage) -> Session:
        session = self._sessions[session_id]
        session.add_message(message)
        self._persist(session)
        return session

    # ── Inactivity Timeout / Cleanup ──────────────────────────────────

    def _start_cleanup(self) -> None:
        """Start the background session cleanup loop."""
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.ensure_future(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically check for and retire inactive sessions."""
        while self._running:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL)
                retired = self.retire_inactive_sessions()
                if retired:
                    print(f"   🧹 Retired {len(retired)} inactive session(s):")
                    for sid, title, msgs in retired:
                        print(f"       - {sid[:12]}... '{title}' ({msgs} msgs)")
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def retire_inactive_sessions(self) -> list[tuple[str, str, int]]:
        """Find and retire sessions past their inactivity timeout.

        Returns list of (session_id, title, message_count) for retired sessions.
        """
        now = time.time()
        retired = []
        for sid in list(self._sessions.keys()):
            session = self._sessions[sid]
            timeout = session.inactivity_timeout or self.DEFAULT_INACTIVITY_TIMEOUT
            if session.status in (SessionStatus.COMPLETED, SessionStatus.ARCHIVED):
                continue
            if session.last_activity > 0 and (now - session.last_activity) > timeout:
                session.status = SessionStatus.ARCHIVED
                session.updated_at = datetime.now(timezone.utc).isoformat()
                self._persist(session)
                retired.append((sid, session.title, len(session.messages)))
                # Log to changelog
                try:
                    from voidtether.server.changelog import get_changelog
                    changelog = get_changelog()
                    changelog.record("session_retired", {
                        "session_id": sid,
                        "title": session.title,
                        "messages": len(session.messages),
                        "inactivity_timeout": timeout,
                        "last_activity": session.last_activity,
                    })
                except Exception:
                    pass
        return retired

    def stop_cleanup(self) -> None:
        """Stop the background cleanup loop (call on shutdown)."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None