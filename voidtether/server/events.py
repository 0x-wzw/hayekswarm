"""Event bus for real-time message streaming with session-scoped channels."""

from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable
import uuid

@dataclass
class MeshEvent:
    """An event in the VoidTether mesh — broadcast to subscribers."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""           # message | agent_join | agent_leave | task_start | task_complete | human_gate | system
    session_id: str = ""
    sender: str = ""               # tether_id or "user" or "system"
    sender_name: str = ""
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "content": self.content,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        data = json.dumps(self.to_dict())
        return f"event: {self.event_type}\ndata: {data}\nid: {self.event_id}\n\n"

    def to_ws(self) -> str:
        """Format as WebSocket JSON message."""
        return json.dumps(self.to_dict())


class EventBus:
    """Session-scoped async event bus.

    Subscribers can subscribe to:
    - A specific session: receive only events for that session + global events
    - All events (global subscription, session_id=None)

    This eliminates the O(sessions × subscribers) waste of the original
    global fan-out design — session events only reach session subscribers.
    """

    MAX_SUBSCRIBERS = 1000

    def __init__(self):
        self._session_subs: dict[str, list[asyncio.Queue[MeshEvent]]] = {}
        self._global_subs: list[asyncio.Queue[MeshEvent]] = []

    def subscribe(self, session_id: str | None = None) -> asyncio.Queue[MeshEvent]:
        """Subscribe to events.

        If session_id is provided, the subscriber receives:
          - Events with matching session_id
          - Global events (session_id == "")

        If session_id is None, the subscriber receives ALL events.
        """
        total = len(self._global_subs) + sum(len(s) for s in self._session_subs.values())
        if total >= self.MAX_SUBSCRIBERS:
            raise RuntimeError(f"EventBus subscriber limit reached ({self.MAX_SUBSCRIBERS})")

        queue: asyncio.Queue[MeshEvent] = asyncio.Queue(maxsize=500)

        if session_id:
            self._session_subs.setdefault(session_id, []).append(queue)
        else:
            self._global_subs.append(queue)

        return queue

    def unsubscribe(self, queue: asyncio.Queue[MeshEvent], session_id: str | None = None) -> None:
        """Unsubscribe from events. Safe to call if already removed."""
        if session_id and session_id in self._session_subs:
            try:
                self._session_subs[session_id].remove(queue)
            except ValueError:
                pass
            if not self._session_subs[session_id]:
                del self._session_subs[session_id]
        else:
            try:
                self._global_subs.remove(queue)
            except ValueError:
                pass

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._global_subs) + sum(len(s) for s in self._session_subs.values())

    async def publish(self, event: MeshEvent) -> None:
        """Broadcast an event to the correct subscribers.

        Session events (event.session_id set) → session subscribers + global subscribers.
        Global events (event.session_id empty) → all subscribers.
        """
        if event.session_id:
            targets = self._session_subs.get(event.session_id, []) + self._global_subs
        else:
            # Global event: deliver to everyone
            targets = list(self._global_subs)
            for subs in self._session_subs.values():
                targets.extend(subs)

        dead_queues: list[asyncio.Queue[MeshEvent]] = []
        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()  # Discard oldest
                    queue.put_nowait(event)  # Insert newest
                except (asyncio.QueueFull, asyncio.QueueEmpty):
                    dead_queues.append(queue)

        for q in dead_queues:
            self.unsubscribe(q)

    async def publish_message(
        self, session_id: str, sender: str, sender_name: str,
        content: str, event_type: str = "message", **kwargs
    ) -> MeshEvent:
        """Convenience: publish a chat message event.

        Semantic extraction runs off the event loop via asyncio.to_thread
        to prevent CPU-bound regex from stalling async I/O.
        """
        # --- Semantic Mesh Hook (off event loop) ---
        from voidtether.core.semantic_registry import registry
        if content:
            await asyncio.to_thread(registry.register_event, session_id, content)
        # -------------------------------------------

        event = MeshEvent(
            event_type=event_type,
            session_id=session_id,
            sender=sender,
            sender_name=sender_name,
            content=content,
            data=kwargs,
        )
        await self.publish(event)
        return event

    async def publish_system(self, session_id: str, content: str, **kwargs) -> MeshEvent:
        """Publish a system notification."""
        event = MeshEvent(
            event_type="system",
            session_id=session_id,
            sender="system",
            sender_name="VoidTether",
            content=content,
            data=kwargs,
        )
        await self.publish(event)
        return event

    async def publish_agent_join(self, session_id: str, tether_id: str, name: str) -> MeshEvent:
        """Publish an agent join notification."""
        event = MeshEvent(
            event_type="agent_join",
            session_id=session_id,
            sender=tether_id,
            sender_name=name,
            content=f"{name} joined the session",
        )
        await self.publish(event)
        return event

    async def publish_human_gate(
        self, session_id: str, sender: str, sender_name: str,
        content: str, **kwargs
    ) -> MeshEvent:
        """Publish a human approval gate event."""
        event = MeshEvent(
            event_type="human_gate",
            session_id=session_id,
            sender=sender,
            sender_name=sender_name,
            content=content,
            data={"requires_approval": True, **kwargs},
        )
        await self.publish(event)
        return event


# Global event bus singleton
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus