"""Tests for rate limiter middleware and audit logging."""

from __future__ import annotations
import time
import json
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from voidtether.server.changelog import ChangeLog, get_changelog
from voidtether.server.app import RateLimiterMiddleware


# ════════════════════════════════════════════════════════════════
# Rate Limiter Tests
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def rate_limiter_app():
    """A minimal FastAPI app wrapped with RateLimiterMiddleware for isolated testing."""
    app = FastAPI()
    
    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}
    
    app.add_middleware(
        RateLimiterMiddleware,
        agent_limit=5,
        ip_limit=10,
        window_seconds=60,
    )
    return app


@pytest.fixture
def ratelimit_client(rate_limiter_app):
    return TestClient(rate_limiter_app)


class TestRateLimiter:
    """Verify the in-memory sliding window rate limiter."""

    def test_allows_normal_traffic(self, ratelimit_client):
        """Rate limiter allows well-below-threshold traffic."""
        for _ in range(5):
            resp = ratelimit_client.get("/test", headers={"X-Tether-Id": "agent-1"})
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_allows_multiple_agents(self, ratelimit_client):
        """Different agents share the global IP limit but have separate agent limits."""
        for i in range(10):
            resp = ratelimit_client.get(
                "/test",
                headers={"X-Tether-Id": f"agent-{i % 3}"},
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_blocks_after_agent_threshold(self, ratelimit_client):
        """Rate limiter returns 429 when a single agent exceeds its limit."""
        for _ in range(5):
            resp = ratelimit_client.get("/test", headers={"X-Tether-Id": "blocked-agent"})
            assert resp.status_code == 200
        # The 6th request should be blocked (agent_limit=5)
        resp = ratelimit_client.get("/test", headers={"X-Tether-Id": "blocked-agent"})
        assert resp.status_code == 429, f"Expected 429, got {resp.status_code}"
        data = resp.json()
        assert "rate limit exceeded" in data["detail"].lower()
        assert "retry_after" in data

    def test_blocks_after_ip_threshold(self, ratelimit_client):
        """Rate limiter returns 429 when IP exceeds its limit."""
        # Use 10 distinct agent IDs so we hit the IP limit (10) before the agent limit (5)
        # But wait — agent limit is 5, so we need to stagger. Actually with agent_limit=5,
        # each agent gets 5, so for 10 reqs using 10 agents, each agent makes 1 req.
        # IP limit is 10, so the 11th should fail.
        for i in range(10):
            resp = ratelimit_client.get("/test", headers={"X-Tether-Id": f"ip-agent-{i}"})
            assert resp.status_code == 200, f"Expected 200 at req {i}"
        resp = ratelimit_client.get("/test", headers={"X-Tether-Id": "ip-agent-extra"})
        assert resp.status_code == 429, f"Expected 429, got {resp.status_code}"
        data = resp.json()
        assert "rate limit exceeded" in data["detail"].lower()

    def test_returns_retry_after_header(self, ratelimit_client):
        """429 response includes a Retry-After header."""
        for _ in range(5):
            ratelimit_client.get("/test", headers={"X-Tether-Id": "retry-agent"})
        resp = ratelimit_client.get("/test", headers={"X-Tether-Id": "retry-agent"})
        assert resp.status_code == 429
        assert "retry-after" in resp.headers or "Retry-After" in resp.headers

    def test_resets_after_window(self):
        """Rate limiter allows traffic again after the window expires."""
        # Use a very short window
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.add_middleware(
            RateLimiterMiddleware,
            agent_limit=2,
            ip_limit=10,
            window_seconds=1,  # 1-second window
        )
        client = TestClient(app)

        # Exhaust agent limit (2)
        resp = client.get("/test", headers={"X-Tether-Id": "reset-agent"})
        assert resp.status_code == 200
        resp = client.get("/test", headers={"X-Tether-Id": "reset-agent"})
        assert resp.status_code == 200
        # 3rd should be blocked
        resp = client.get("/test", headers={"X-Tether-Id": "reset-agent"})
        assert resp.status_code == 429, f"Expected 429, got {resp.status_code}"

        # Wait for the window to pass
        time.sleep(1.1)

        # Now it should be allowed again
        resp = client.get("/test", headers={"X-Tether-Id": "reset-agent"})
        assert resp.status_code == 200, f"Expected 200 after reset, got {resp.status_code}"


# ════════════════════════════════════════════════════════════════
# Audit Log Tests
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def audit_changelog():
    """Create an isolated ChangeLog with a temp in-memory DB for audit tests."""
    import tempfile
    import os
    fd, path = tempfile.mkstemp(suffix="_audit_test.db")
    os.close(fd)
    clog = ChangeLog(db_path=path)
    yield clog
    # Cleanup
    try:
        os.unlink(path)
    except OSError:
        pass


class TestAuditLog:
    """Verify audit logging of agent operations."""

    def test_records_register_agent(self, audit_changelog):
        """Audit log records agent registration."""
        audit_changelog.record_audit(
            agent_id="agent-001",
            action="register_agent",
            source_ip="192.168.1.1",
            details={"name": "Test Agent", "protocol": "hermes"},
        )
        events = audit_changelog.get_audit_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "audit_register_agent"
        data = events[0]["data"]
        assert data["agent_id"] == "agent-001"
        assert data["action"] == "register_agent"
        assert data["source_ip"] == "192.168.1.1"
        assert data["details"]["name"] == "Test Agent"

    def test_records_unregister_agent(self, audit_changelog):
        """Audit log records agent deregistration."""
        audit_changelog.record_audit(
            agent_id="agent-002",
            action="unregister_agent",
            source_ip="10.0.0.1",
        )
        events = audit_changelog.get_audit_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "audit_unregister_agent"
        assert events[0]["data"]["agent_id"] == "agent-002"

    def test_records_create_session(self, audit_changelog):
        """Audit log records session creation."""
        audit_changelog.record_audit(
            agent_id="session-abc",
            action="create_session",
            source_ip="10.0.0.2",
            details={"title": "Test Session", "participants": ["agent-001"]},
        )
        events = audit_changelog.get_audit_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "audit_create_session"
        data = events[0]["data"]
        assert data["agent_id"] == "session-abc"
        assert data["details"]["title"] == "Test Session"

    def test_records_delete_session(self, audit_changelog):
        """Audit log records session deletion."""
        audit_changelog.record_audit(
            agent_id="session-xyz",
            action="delete_session",
            source_ip="10.0.0.3",
            details={"title": "Old Session"},
        )
        events = audit_changelog.get_audit_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "audit_delete_session"
        assert events[0]["data"]["agent_id"] == "session-xyz"

    def test_audit_log_is_queryable(self, audit_changelog):
        """Audit events can be queried and filtered by action type."""
        # Record multiple events
        audit_changelog.record_audit("a1", "register_agent", "10.0.0.1")
        audit_changelog.record_audit("s1", "create_session", "10.0.0.1")
        audit_changelog.record_audit("a2", "register_agent", "10.0.0.2")
        audit_changelog.record_audit("s1", "delete_session", "10.0.0.3")
        audit_changelog.record_audit("a1", "unregister_agent", "10.0.0.1")

        # All events
        all_events = audit_changelog.get_audit_events()
        assert len(all_events) == 5

        # Filter by action
        register_events = audit_changelog.get_audit_events(action="register_agent")
        assert len(register_events) == 2
        for e in register_events:
            assert e["data"]["action"] == "register_agent"

        delete_events = audit_changelog.get_audit_events(action="delete_session")
        assert len(delete_events) == 1
        assert delete_events[0]["data"]["agent_id"] == "s1"

        # Limit works
        limited = audit_changelog.get_audit_events(limit=2)
        assert len(limited) <= 2

    def test_records_admin_operations(self, audit_changelog):
        """All four required admin operations are recorded correctly."""
        operations = [
            ("agent-01", "register_agent", "192.168.1.10"),
            ("agent-01", "unregister_agent", "192.168.1.10"),
            ("session-01", "create_session", "192.168.1.20"),
            ("session-01", "delete_session", "192.168.1.20"),
        ]
        for agent_id, action, source_ip in operations:
            audit_changelog.record_audit(agent_id, action, source_ip)

        events = audit_changelog.get_audit_events()
        recorded_actions = {e["data"]["action"] for e in events}
        assert recorded_actions == {"register_agent", "unregister_agent", "create_session", "delete_session"}


# ════════════════════════════════════════════════════════════════
# End-to-end: audit via the API server
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def audit_api_app():
    """A FastAPI app with changelog-wired endpoints for real audit logging."""
    from voidtether.mesh import Mesh
    from voidtether.server.sessions import SessionManager
    from voidtether.server.events import EventBus, get_event_bus
    from voidtether.server.changelog import ChangeLog, get_changelog
    from voidtether.core import Protocol, TetherManifest
    import tempfile
    import os

    # Reset singletons
    import voidtether.server.changelog as cl_mod
    import voidtether.server.events as ev_mod

    fd, db_path = tempfile.mkstemp(suffix="_audit_api_test.db")
    os.close(fd)
    os.environ["VOIDTETHER_CHANGE_LOG"] = db_path
    cl_mod._changelog = ChangeLog(db_path=db_path)
    ev_mod._event_bus = EventBus()

    from voidtether.server.app import create_app

    mesh = Mesh()
    app = create_app(mesh=mesh)
    app.state.mesh = mesh
    app.state.sessions = SessionManager()  # in-memory for testing
    app.state.events = get_event_bus()

    yield app, db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


class TestAuditAPI:
    """Integration tests that audit via actual API endpoints."""

    def test_audit_log_queryable(self, audit_api_app):
        """Audit log endpoint returns events that can be queried."""
        app, db_path = audit_api_app
        client = TestClient(app)
        resp = client.get("/api/changelog?limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
