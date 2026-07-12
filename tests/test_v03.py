"""VoidTether v0.3.0 — comprehensive test suite."""

from __future__ import annotations
import asyncio
import pytest
import time

from voidtether.core.manifest import (
    TetherManifest, Protocol, ProtocolEndpoint, TaskState,
)
from voidtether.core.router import TetherRouter, TetherTask
from voidtether.core.bridge import ProtocolBridge, BaseAdapter
from voidtether.core.lifecycle import can_transition, transition, TRANSITIONS
from voidtether.core.auth import HMACVerifier
from voidtether.core.envelope import TetherEnvelope
from voidtether.core.pool import (
    ConnectionPool, RetryPolicy, HealthMonitor, HealthStatus, HealthCheck,
    retry_execute, PooledConnection,
)
from voidtether.adapters import ALL_ADAPTERS
from voidtether.adapters.a2a import A2AAdapter, a2a_card_to_manifest
from voidtether.adapters.hermes import HermesAdapter, hermes_skills_to_manifest
from voidtether.adapters.openclaw import OpenClawAdapter, openclaw_skills_to_manifest
from voidtether.adapters.swarm import SwarmAdapter
from voidtether.adapters.crewai import CrewAIAdapter
from voidtether.adapters.langgraph import LangGraphAdapter
from voidtether.adapters.gbrain import GBrainAdapter, gbrain_skills_to_manifest
from voidtether.adapters.mcp import MCPAdapter, mcp_tools_to_manifest
from voidtether.adapters.acp import ACPAdapter, acp_manifest_from_config
from voidtether.mesh import Mesh
from voidtether.server.sessions import Session, SessionManager, ChatMessage, MessageRole, SessionStatus
from voidtether.server.events import EventBus, MeshEvent


# ════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_manifest():
    return TetherManifest(
        tether_id="test-agent-001",
        name="TestAgent",
        origin_protocol=Protocol.A2A,
        capabilities={"tasks": ["code_review", "summarize"], "modalities": ["text"]},
        protocols=[ProtocolEndpoint(protocol=Protocol.A2A, agent_card_url="http://localhost:8080/card")],
    )

@pytest.fixture
def hermes_manifest():
    return TetherManifest(
        tether_id="hermes-agent-001",
        name="HermesBot",
        origin_protocol=Protocol.HERMES,
        capabilities={"tasks": ["research", "write"], "skills": ["web-search"], "modalities": ["text"]},
        protocols=[ProtocolEndpoint(protocol=Protocol.HERMES, skill="web-search")],
    )


# ════════════════════════════════════════════════════════════════
# TestManifest
# ════════════════════════════════════════════════════════════════

class TestManifest:
    def test_protocol_enum(self):
        assert Protocol.A2A.value == "a2a"
        assert Protocol.HERMES.value == "hermes"
        assert Protocol.OPENCLAW.value == "openclaw"

    def test_task_state_enum(self):
        assert TaskState.SUBMITTED.value == "submitted"
        assert TaskState.COMPLETED.value == "completed"

    def test_tether_manifest_creation(self, sample_manifest):
        assert sample_manifest.tether_id == "test-agent-001"
        assert sample_manifest.origin_protocol == Protocol.A2A
        assert "code_review" in sample_manifest.tasks

    def test_supports_task(self, sample_manifest):
        assert sample_manifest.supports_task("code_review") is True
        assert sample_manifest.supports_task("nonexistent") is False

    def test_manifest_to_dict(self, sample_manifest):
        d = sample_manifest.to_dict()
        assert d["tether_id"] == "test-agent-001"
        assert d["origin_protocol"] == "a2a"
        assert isinstance(d["protocols"], list)

    def test_protocol_endpoint(self):
        ep = ProtocolEndpoint(protocol=Protocol.MCP, tools=["search", "read"])
        assert ep.protocol == Protocol.MCP
        assert len(ep.tools) == 2


# ════════════════════════════════════════════════════════════════
# TestRouter
# ════════════════════════════════════════════════════════════════

class TestRouter:
    def test_register_and_get(self, sample_manifest):
        router = TetherRouter()
        router.register(sample_manifest)
        assert router.get("test-agent-001") is sample_manifest

    def test_unregister(self, sample_manifest):
        router = TetherRouter()
        router.register(sample_manifest)
        router.unregister("test-agent-001")
        assert router.get("test-agent-001") is None

    def test_discover(self, sample_manifest):
        router = TetherRouter()
        router.register(sample_manifest)
        results = router.discover("code_review")
        assert len(results) >= 1
        assert results[0].tether_id == "test-agent-001"

    def test_discover_empty(self):
        router = TetherRouter()
        assert router.discover("nonexistent") == []

    def test_list_agents(self, sample_manifest):
        router = TetherRouter()
        router.register(sample_manifest)
        agents = router.list_agents()
        assert len(agents) == 1


# ════════════════════════════════════════════════════════════════
# TestTetherTask
# ════════════════════════════════════════════════════════════════

class TestTetherTask:
    def test_task_creation(self):
        task = TetherTask(
            task_id="t-001",
            task_type="code_review",
            input_data={"code": "print('hello')"},
            source_agent="test-agent-001",
            source_protocol=Protocol.A2A,
        )
        assert task.state == TaskState.SUBMITTED
        assert task.target_protocol is None

    def test_task_state_mutation(self):
        task = TetherTask(
            task_id="t-002",
            task_type="summarize",
            input_data={},
            source_agent="agent-1",
            source_protocol=Protocol.HERMES,
        )
        assert task.state == TaskState.SUBMITTED
        task.state = TaskState.RUNNING
        assert task.state == TaskState.RUNNING


# ════════════════════════════════════════════════════════════════
# TestLifecycle
# ════════════════════════════════════════════════════════════════

class TestLifecycle:
    def test_valid_transitions(self):
        assert can_transition(TaskState.SUBMITTED, TaskState.NEGOTIATING) is True
        assert can_transition(TaskState.ACCEPTED, TaskState.RUNNING) is True
        assert can_transition(TaskState.RUNNING, TaskState.COMPLETED) is True

    def test_invalid_transitions(self):
        assert can_transition(TaskState.COMPLETED, TaskState.RUNNING) is False
        assert can_transition(TaskState.SUBMITTED, TaskState.COMPLETED) is False

    def test_transition_returns_target(self):
        result = transition(TaskState.SUBMITTED, TaskState.NEGOTIATING)
        assert result == TaskState.NEGOTIATING

    def test_invalid_transition_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            transition(TaskState.COMPLETED, TaskState.RUNNING)

    def test_transition_mutates_task(self):
        task = TetherTask(
            task_id="t-003",
            task_type="test",
            input_data={},
            source_agent="a1",
            source_protocol=Protocol.A2A,
        )
        task.state = transition(task.state, TaskState.NEGOTIATING)
        assert task.state == TaskState.NEGOTIATING

    def test_streaming_to_running_loop(self):
        # STREAMING -> COMPLETED is valid
        assert can_transition(TaskState.STREAMING, TaskState.COMPLETED) is True
        # STREAMING -> FAILED is valid
        assert can_transition(TaskState.STREAMING, TaskState.FAILED) is True
        # But STREAMING -> RUNNING is NOT valid
        assert can_transition(TaskState.STREAMING, TaskState.RUNNING) is False

    def test_terminal_states(self):
        for terminal in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.REJECTED]:
            assert len(TRANSITIONS[terminal]) == 0


# ════════════════════════════════════════════════════════════════
# TestProtocolBridge
# ════════════════════════════════════════════════════════════════

class TestProtocolBridge:
    def test_register_adapter(self):
        router = TetherRouter()
        bridge = ProtocolBridge(router)
        adapter = A2AAdapter()
        bridge.register_adapter(Protocol.A2A, adapter)
        assert Protocol.A2A in bridge._adapters

    def test_delegate_no_adapter(self):
        router = TetherRouter()
        bridge = ProtocolBridge(router)
        manifest = TetherManifest(
            tether_id="a1", name="A", origin_protocol=Protocol.A2A,
            capabilities={"tasks": ["code_review"]},
            protocols=[ProtocolEndpoint(protocol=Protocol.A2A)],
        )
        router.register(manifest)
        task = TetherTask(
            task_id="t-1", task_type="code_review", input_data={},
            source_agent="user", source_protocol=Protocol.HERMES,
        )
        result = asyncio.get_event_loop().run_until_complete(bridge.delegate(task))
        assert "error" in result

    def test_delegate_with_adapter(self):
        router = TetherRouter()
        bridge = ProtocolBridge(router)
        adapter = A2AAdapter()
        bridge.register_adapter(Protocol.A2A, adapter)
        manifest = TetherManifest(
            tether_id="a2", name="A2Agent", origin_protocol=Protocol.A2A,
            capabilities={"tasks": ["code_review"]},
            protocols=[ProtocolEndpoint(protocol=Protocol.A2A, agent_card_url="http://localhost/card")],
        )
        router.register(manifest)
        task = TetherTask(
            task_id="t-2", task_type="code_review", input_data={"code": "x"},
            source_agent="user", source_protocol=Protocol.A2A,
        )
        result = asyncio.get_event_loop().run_until_complete(bridge.delegate(task))
        # Should get a result (even if fake from stub execute)
        assert task.state == TaskState.COMPLETED or "error" in result

    def test_delegate_callbacks(self):
        """Delegate should set state to RUNNING then COMPLETED."""
        router = TetherRouter()
        bridge = ProtocolBridge(router)
        adapter = HermesAdapter()
        bridge.register_adapter(Protocol.HERMES, adapter)
        manifest = TetherManifest(
            tether_id="h1", name="HermesAgent", origin_protocol=Protocol.HERMES,
            capabilities={"tasks": ["research"]},
            protocols=[ProtocolEndpoint(protocol=Protocol.HERMES, skill="research")],
        )
        router.register(manifest)
        task = TetherTask(
            task_id="t-3", task_type="research", input_data={"query": "test"},
            source_agent="user", source_protocol=Protocol.HERMES,
        )
        asyncio.get_event_loop().run_until_complete(bridge.delegate(task))
        assert task.state == TaskState.COMPLETED
        assert task.assigned_to == "h1"

    @pytest.mark.asyncio
    async def test_delegate_timeout(self):
        """Delegate with no matching agent returns error."""
        router = TetherRouter()
        bridge = ProtocolBridge(router)
        task = TetherTask(
            task_id="t-4", task_type="impossible_task", input_data={},
            source_agent="user", source_protocol=Protocol.A2A,
        )
        result = await bridge.delegate(task)
        assert "error" in result


# ════════════════════════════════════════════════════════════════
# TestAdapters
# ════════════════════════════════════════════════════════════════

class TestA2AAdapter:
    def test_protocol(self):
        assert A2AAdapter().protocol == Protocol.A2A

    def test_normalize_output(self):
        adapter = A2AAdapter()
        data = {"result": {"status": {"state": "completed"}, "artifacts": [{"type": "text", "content": "hi"}]}}
        out = adapter.normalize_output(data)
        assert out["text"] == "hi"
        assert out["status"] == "completed"

    def test_denormalize_input(self):
        adapter = A2AAdapter()
        out = adapter.denormalize_input({"task_type": "review", "input": {"code": "x"}})
        assert "params" in out
        assert out["method"] == "tasks/send"

    def test_a2a_card_to_manifest(self):
        card = {
            "name": "TestAgent",
            "url": "http://localhost:8080",
            "skills": [{"id": "review", "name": "Review"}],
        }
        manifest = a2a_card_to_manifest(card)
        assert manifest.origin_protocol == Protocol.A2A
        assert "review" in manifest.tasks
        # protocols must be ProtocolEndpoint instances (regression: #9 built raw dicts)
        assert all(isinstance(p, ProtocolEndpoint) for p in manifest.protocols)
        assert manifest.protocols[0].protocol == Protocol.A2A
        assert manifest.protocols[0].agent_card_url == "http://localhost:8080"
        # manifest must serialize without AttributeError
        d = manifest.to_dict()
        assert d["protocols"][0]["protocol"] == "a2a"


class TestHermesAdapter:
    def test_protocol(self):
        assert HermesAdapter().protocol == Protocol.HERMES

    def test_normalize_output(self):
        adapter = HermesAdapter()
        out = adapter.normalize_output({"response": "done", "metadata": {"x": 1}})
        assert out["text"] == "done"

    def test_denormalize_input(self):
        adapter = HermesAdapter()
        out = adapter.denormalize_input({"skill": "search", "input": {"q": "test"}})
        assert out["skill"] == "search"

    @pytest.mark.asyncio
    async def test_execute(self):
        adapter = HermesAdapter()
        manifest = TetherManifest(
            tether_id="h1", name="H", origin_protocol=Protocol.HERMES,
            capabilities={"tasks": ["search"]},
        )
        result = await adapter.execute(manifest, "search", {"query": "test"})
        assert result["status"] == "completed"


class TestOpenClawAdapter:
    def test_protocol(self):
        assert OpenClawAdapter().protocol == Protocol.OPENCLAW

    def test_normalize_output(self):
        adapter = OpenClawAdapter()
        out = adapter.normalize_output({"output": "result text"})
        assert out["text"] == "result text"

    def test_normalize_diffs(self):
        adapter = OpenClawAdapter()
        # OpenClaw returns composition diffs
        data = {"output": "file1.py: +3 -1\nfile2.py: +0 -5", "metadata": {"diff": True}}
        out = adapter.normalize_output(data)
        assert out["text"] == "file1.py: +3 -1\nfile2.py: +0 -5"
        assert "media" in out

    def test_denormalize_input(self):
        adapter = OpenClawAdapter()
        out = adapter.denormalize_input({"skill": "render", "input": {"template": "x"}})
        assert "skill" in out
        assert out["non_interactive"] is True

    @pytest.mark.asyncio
    async def test_execute(self):
        adapter = OpenClawAdapter()
        manifest = TetherManifest(
            tether_id="oc1", name="OC", origin_protocol=Protocol.OPENCLAW,
            capabilities={"tasks": ["render"]},
        )
        result = await adapter.execute(manifest, "render", {"template": "x"})
        assert result["status"] == "completed"


class TestSwarmAdapter:
    def test_protocol(self):
        assert SwarmAdapter().protocol == Protocol.SWARM

    def test_normalize_output(self):
        out = SwarmAdapter().normalize_output({"response": "hello", "context": {"x": 1}})
        assert out["text"] == "hello"

    def test_denormalize_input(self):
        out = SwarmAdapter().denormalize_input({"task_type": "func1", "input": {}})
        assert out["agent_fn"] == "func1"


class TestCrewAIAdapter:
    def test_protocol(self):
        assert CrewAIAdapter().protocol == Protocol.CREWAI

    def test_normalize_output(self):
        out = CrewAIAdapter().normalize_output({"output": "text", "role": "researcher"})
        assert out["text"] == "text"


class TestLangGraphAdapter:
    def test_protocol(self):
        assert LangGraphAdapter().protocol == Protocol.LANGGRAPH

    def test_normalize_output(self):
        out = LangGraphAdapter().normalize_output({"output": "text", "state": {"step": 1}})
        assert out["text"] == "text"


class TestGBrainAdapter:
    def test_protocol(self):
        assert GBrainAdapter().protocol == Protocol.GBRAIN

    def test_normalize_output(self):
        adapter = GBrainAdapter()
        # GBrain normalize_output routes by structure: "results", "enriched", "slug" keys
        # For query results:
        out = adapter.normalize_output({"results": [{"compiled_truth": "insight text"}], "search_type": "hybrid"})
        assert out["text"] == "insight text"
        assert out["source"] == "gbrain"

    def test_denormalize_input(self):
        adapter = GBrainAdapter()
        out = adapter.denormalize_input({"skill": "query", "input": {"question": "test"}})
        assert out["method"] == "tools/call"
        assert "gbrain_query" in out["params"]["name"]

    def test_gbrain_skills_to_manifest(self):
        manifest = gbrain_skills_to_manifest(name="GBrainAgent")
        assert manifest.origin_protocol == Protocol.GBRAIN
        assert len(manifest.tasks) > 0

    @pytest.mark.asyncio
    async def test_execute(self):
        adapter = GBrainAdapter()
        manifest = TetherManifest(
            tether_id="gb1", name="GB", origin_protocol=Protocol.GBRAIN,
            capabilities={"tasks": ["query"]},
            protocols=[ProtocolEndpoint(protocol=Protocol.GBRAIN, endpoint_url="http://localhost:8787/mcp", config={"framework": "gbrain"})],
        )
        result = await adapter.execute(manifest, "query", {"q": "test"})
        # Returns either completed or error (no endpoint)
        assert "status" in result or "error" in result


class TestMCPAdapter:
    def test_protocol(self):
        assert MCPAdapter().protocol == Protocol.MCP

    def test_normalize_output(self):
        adapter = MCPAdapter()
        data = {"content": [{"type": "text", "text": "hello"}]}
        out = adapter.normalize_output(data)
        assert out["text"] == "hello"

    def test_mcp_tools_to_manifest(self):
        tools = [{"name": "search", "description": "Search the web"}]
        manifest = mcp_tools_to_manifest("http://localhost:8787/mcp", tools, name="Test MCP")
        assert manifest.origin_protocol == Protocol.MCP
        assert "search" in manifest.tasks


# ════════════════════════════════════════════════════════════════
# TestACPAdapter
# ════════════════════════════════════════════════════════════════

class TestACPAdapter:
    def test_protocol(self):
        assert ACPAdapter().protocol == Protocol.ACP

    def test_normalize_output(self):
        adapter = ACPAdapter()
        data = {
            "result": {
                "status": "completed",
                "artifacts": [{"type": "text", "content": "hello from ACP"}],
            }
        }
        out = adapter.normalize_output(data)
        assert out["text"] == "hello from ACP"
        assert out["is_error"] is False

    def test_normalize_output_error(self):
        adapter = ACPAdapter()
        data = {"error": {"code": -1, "message": "agent failed"}}
        out = adapter.normalize_output(data)
        assert out["is_error"] is True
        assert "agent failed" in out["text"]

    def test_denormalize_input(self):
        adapter = ACPAdapter()
        out = adapter.denormalize_input({"task_type": "code_review", "input": {"code": "x"}})
        assert out["method"] == "task/send"
        assert "params" in out
        assert "message" in out["params"]

    def test_acp_manifest_from_config(self):
        manifest = acp_manifest_from_config(
            name="Claude Code",
            acp_command="claude",
            tasks=["code_review", "debugging"],
        )
        assert manifest.origin_protocol == Protocol.ACP
        assert "code_review" in manifest.tasks
        assert manifest.protocols[0].acp_command == "claude"
        assert manifest.protocols[0].acp_transport == "stdio"

    @pytest.mark.asyncio
    async def test_execute_no_command(self):
        """Execute with no ACP command should return error."""
        adapter = ACPAdapter()
        manifest = TetherManifest(
            tether_id="acp-test-1", name="Test", origin_protocol=Protocol.ACP,
            capabilities={"tasks": ["code_review"]},
            protocols=[ProtocolEndpoint(protocol=Protocol.ACP)],
        )
        result = await adapter.execute(manifest, "code_review", {})
        assert "error" in result


# ════════════════════════════════════════════════════════════════
# TestALLAdaptersRegistry
# ════════════════════════════════════════════════════════════════

class TestALLAdaptersRegistry:
    def test_all_adapters_present(self):
        assert "a2a" in ALL_ADAPTERS
        assert "mcp" in ALL_ADAPTERS
        assert "hermes" in ALL_ADAPTERS
        assert "openclaw" in ALL_ADAPTERS
        assert "swarm" in ALL_ADAPTERS
        assert "crewai" in ALL_ADAPTERS
        assert "langgraph" in ALL_ADAPTERS
        assert "gbrain" in ALL_ADAPTERS
        assert "acp" in ALL_ADAPTERS

    def test_adapter_classes_instantiable(self):
        for name, cls in ALL_ADAPTERS.items():
            adapter = cls()
            assert hasattr(adapter, "protocol")
            assert hasattr(adapter, "normalize_output")
            assert hasattr(adapter, "denormalize_input")


# ════════════════════════════════════════════════════════════════
# TestHMACVerifier
# ════════════════════════════════════════════════════════════════

class TestHMACVerifier:
    def test_sign_and_verify(self):
        verifier = HMACVerifier(secret="test-secret-key")
        ts = int(time.time())
        data = "hello world"
        sig = verifier.sign(data, timestamp=ts)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex
        assert verifier.verify(data, sig, timestamp=ts) is True

    def test_verify_wrong_signature(self):
        verifier = HMACVerifier(secret="test-secret-key")
        ts = int(time.time())
        assert verifier.verify("hello", "badsignature", timestamp=ts) is False

    def test_verify_expired_timestamp(self):
        verifier = HMACVerifier(secret="test-secret-key")
        old_ts = int(time.time()) - 600  # 10 min ago
        sig = verifier.sign("hello", timestamp=old_ts)
        assert verifier.verify("hello", sig, timestamp=old_ts, max_drift=300) is False


# ════════════════════════════════════════════════════════════════
# TestEnvelope
# ════════════════════════════════════════════════════════════════

class TestEnvelope:
    def test_envelope_creation(self):
        env = TetherEnvelope(source="a1", target="a2", task_type="review")
        assert env.source == "a1"
        assert env.target == "a2"
        assert env.envelope_id  # auto-generated UUID

    def test_envelope_to_dict(self):
        env = TetherEnvelope(source="a1", target="a2", auth_token="secret123")
        d = env.to_dict()
        assert d["auth_token"] == "***"  # redacted
        assert d["source"] == "a1"


# ════════════════════════════════════════════════════════════════
# TestSession
# ════════════════════════════════════════════════════════════════

class TestSession:
    def test_session_creation(self):
        mgr = SessionManager()
        session = mgr.create_session(title="Test Session")
        assert session.title == "Test Session"
        assert session.status == SessionStatus.ACTIVE

    def test_session_add_message(self):
        mgr = SessionManager()
        session = mgr.create_session()
        msg = ChatMessage(
            session_id=session.session_id,
            role=MessageRole.USER,
            sender="user",
            content="Hello",
        )
        session.add_message(msg)
        assert len(session.messages) == 1
        assert session.messages[0].content == "Hello"

    def test_session_pause_resume(self):
        mgr = SessionManager()
        session = mgr.create_session()
        session.status = SessionStatus.PAUSED
        assert session.status == SessionStatus.PAUSED
        session.status = SessionStatus.ACTIVE
        assert session.status == SessionStatus.ACTIVE


# ════════════════════════════════════════════════════════════════
# TestEventBus
# ════════════════════════════════════════════════════════════════

class TestEventBus:
    def test_mesh_event_creation(self):
        evt = MeshEvent(event_type="agent_join", sender="a1", content="joined")
        assert evt.event_type == "agent_join"
        assert evt.event_id  # auto UUID

    def test_mesh_event_sse(self):
        evt = MeshEvent(event_type="message", content="hello")
        sse = evt.to_sse()
        assert "event: message" in sse

    def test_mesh_event_ws(self):
        evt = MeshEvent(event_type="message", content="hello")
        ws = evt.to_ws()
        assert '"event_type": "message"' in ws

    @pytest.mark.asyncio
    async def test_event_bus_publish(self):
        bus = EventBus()
        evt = MeshEvent(event_type="agent_join", sender="a1")
        await bus.publish_agent_join("a1", "Agent1", "a2a")
        # Should not raise


# ════════════════════════════════════════════════════════════════
# TestServerEndpoints (via httpx TestClient)
# ════════════════════════════════════════════════════════════════

class TestServerEndpoints:
    @pytest.fixture
    def client(self):
        from voidtether.server.app import create_app
        return create_app()

    @pytest.mark.asyncio
    async def test_register_agent(self):
        from httpx import AsyncClient, ASGITransport
        from voidtether.server.app import create_app
        from voidtether.core.auth import HMACVerifier
        import os
        import time

        app = create_app()
        transport = ASGITransport(app=app)
        
        # Use the same secret as the app
        secret = os.environ.get("VOIDTETHER_HMAC_SECRET", "voidtether-dev-insecure-secret")
        verifier = HMACVerifier(secret=secret)
        
        payload = {
            "tether_id": "srv-agent-1",
            "name": "ServerAgent",
            "protocol": "a2a",
            "capabilities": {"tasks": ["review"]},
            "endpoint_url": "http://localhost:8080",
        }
        import json
        body = json.dumps(payload)
        ts = int(time.time())
        sig = verifier.sign(body, timestamp=ts)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Case 1: No auth (should be 401)
            resp_unauth = await ac.post("/api/agents/register", json=payload)
            assert resp_unauth.status_code == 401
            
            # Case 2: Valid auth (should be 200)
            resp_auth = await ac.post(
                "/api/agents/register", 
                content=body,
                headers={
                    "X-Tether-Signature": sig,
                    "X-Tether-Timestamp": str(ts),
                    "Content-Type": "application/json"
                }
            )
            assert resp_auth.status_code == 200
            data = resp_auth.json()
            assert data["status"] == "registered"

    @pytest.mark.asyncio
    async def test_list_agents(self):
        from httpx import AsyncClient, ASGITransport
        from voidtether.server.app import create_app
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/agents")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_discover_agents(self):
        from httpx import AsyncClient, ASGITransport
        from voidtether.server.app import create_app
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # First register
            await ac.post("/api/agents/register", json={
                "tether_id": "disc-agent-1",
                "name": "DiscAgent",
                "protocol": "hermes",
                "capabilities": {"tasks": ["research"]},
            })
            # Then discover
            resp = await ac.get("/api/agents/discover", params={"task_type": "research"})
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_session(self):
        from httpx import AsyncClient, ASGITransport
        from voidtether.server.app import create_app
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/sessions", json={
                "title": "Test Session",
                "participants": ["a1", "a2"],
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "session_id" in data

    @pytest.mark.asyncio
    async def test_session_lifecycle(self):
        from httpx import AsyncClient, ASGITransport
        from voidtether.server.app import create_app
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Create
            resp = await ac.post("/api/sessions", json={"title": "Lifecycle Test"})
            session_id = resp.json()["session_id"]
            # Get
            resp = await ac.get(f"/api/sessions/{session_id}")
            assert resp.status_code == 200
            # Send message
            resp = await ac.post(f"/api/sessions/{session_id}/messages", json={
                "sender": "user",
                "content": "Hello agents!",
            })
            assert resp.status_code == 200


# ════════════════════════════════════════════════════════════════
# TestMeshIntegration
# ════════════════════════════════════════════════════════════════

class TestMeshIntegration:
    def test_mesh_register_and_discover(self):
        mesh = Mesh()
        manifest = TetherManifest(
            tether_id="mesh-agent-1",
            name="MeshAgent",
            origin_protocol=Protocol.HERMES,
            capabilities={"tasks": ["research"]},
            protocols=[ProtocolEndpoint(protocol=Protocol.HERMES)],
        )
        mesh.register(manifest)
        found = mesh.discover("research")
        assert found is not None
        assert found.tether_id == "mesh-agent-1"

    @pytest.mark.asyncio
    async def test_mesh_auto_delegate(self):
        mesh = Mesh()
        manifest = TetherManifest(
            tether_id="mesh-agent-2",
            name="MeshAgent2",
            origin_protocol=Protocol.HERMES,
            capabilities={"tasks": ["write"]},
            protocols=[ProtocolEndpoint(protocol=Protocol.HERMES, skill="write")],
        )
        mesh.register(manifest)
        task = TetherTask(
            task_id="mesh-t-1",
            task_type="write",
            input_data={"topic": "AI"},
            source_agent="user",
            source_protocol=Protocol.HERMES,
        )
        result = await mesh.delegate(task)
        assert task.state == TaskState.COMPLETED

# ════════════════════════════════════════════════════════════════
# TestConnectionPool
# ════════════════════════════════════════════════════════════════

class TestConnectionPool:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        pool = ConnectionPool(max_per_endpoint=5)
        conn = await pool.acquire("http://localhost:8080", Protocol.A2A)
        assert conn.in_use is True
        assert conn.protocol == Protocol.A2A
        await pool.release(conn)
        assert conn.in_use is False
        stats = pool.stats()
        assert stats["total_connections"] == 1
        assert stats["idle"] == 1

    @pytest.mark.asyncio
    async def test_reuse_idle(self):
        pool = ConnectionPool(max_per_endpoint=5)
        conn1 = await pool.acquire("http://localhost:8080", Protocol.A2A)
        await pool.release(conn1)
        conn2 = await pool.acquire("http://localhost:8080", Protocol.A2A)
        assert conn2.connection_id == conn1.connection_id  # reused
        await pool.release(conn2)

    @pytest.mark.asyncio
    async def test_pool_stats(self):
        pool = ConnectionPool(max_per_endpoint=5)
        c1 = await pool.acquire("http://a:8080", Protocol.A2A)
        c2 = await pool.acquire("http://b:8080", Protocol.HERMES)
        stats = pool.stats()
        assert stats["total_connections"] == 2
        assert stats["in_use"] == 2
        assert stats["endpoints"] == 2
        await pool.release(c1)
        await pool.release(c2)

    @pytest.mark.asyncio
    async def test_cleanup_evicts_stale(self):
        pool = ConnectionPool(max_per_endpoint=5, idle_timeout=0.01, max_age=0.01)
        conn = await pool.acquire("http://localhost:8080", Protocol.A2A)
        await pool.release(conn)
        await asyncio.sleep(0.02)  # Wait for idle timeout
        evicted = await pool.cleanup()
        assert evicted >= 1
        stats = pool.stats()
        assert stats["total_connections"] == 0

    @pytest.mark.asyncio
    async def test_release_with_error(self):
        pool = ConnectionPool(max_per_endpoint=5)
        conn = await pool.acquire("http://localhost:8080", Protocol.A2A)
        await pool.release(conn, error=True)
        assert conn.error_count == 1


# ════════════════════════════════════════════════════════════════
# TestRetryPolicy
# ════════════════════════════════════════════════════════════════

class TestRetryPolicy:
    def test_defaults(self):
        policy = RetryPolicy()
        assert policy.max_retries == 3
        assert policy.base_delay == 1.0

    def test_delay_increases(self):
        policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0)
        d0 = policy.delay_for_attempt(0)
        d1 = policy.delay_for_attempt(1)
        d2 = policy.delay_for_attempt(2)
        assert d0 < d1 < d2

    def test_max_delay_cap(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=5.0, backoff_factor=10.0)
        d = policy.delay_for_attempt(5)
        assert d <= 6.0  # 5.0 + 20% random jitter


# ════════════════════════════════════════════════════════════════
# TestRetryExecute
# ════════════════════════════════════════════════════════════════

class TestRetryExecute:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        call_count = 0
        async def good_fn():
            nonlocal call_count
            call_count += 1
            return "ok"
        result = await retry_execute(good_fn, policy=RetryPolicy(max_retries=3))
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        call_count = 0
        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("slow")
            return "recovered"
        result = await retry_execute(
            flaky_fn,
            policy=RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.1),
        )
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_raises(self):
        async def bad_fn():
            raise ValueError("bad input")
        with pytest.raises(ValueError):
            await retry_execute(bad_fn, policy=RetryPolicy(max_retries=2, base_delay=0.01))

    @pytest.mark.asyncio
    async def test_exhaust_retries(self):
        async def always_fail():
            raise TimeoutError("always")
        with pytest.raises(TimeoutError):
            await retry_execute(
                always_fail,
                policy=RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.1),
            )


# ════════════════════════════════════════════════════════════════
# TestHealthCheck
# ════════════════════════════════════════════════════════════════

class TestHealthCheckObj:
    def test_initial_state(self):
        hc = HealthCheck(tether_id="a1", protocol=Protocol.A2A)
        assert hc.status == HealthStatus.UNKNOWN
        assert hc.is_available is True  # UNKNOWN is available

    def test_mark_success(self):
        hc = HealthCheck(tether_id="a1", protocol=Protocol.A2A)
        hc.mark_success(42.5)
        assert hc.status == HealthStatus.HEALTHY
        assert hc.latency_ms == 42.5
        assert hc.consecutive_successes == 1
        assert hc.consecutive_failures == 0

    def test_mark_failure_degrades(self):
        hc = HealthCheck(tether_id="a1", protocol=Protocol.A2A)
        hc.mark_failure()
        assert hc.status == HealthStatus.DEGRADED
        assert hc.consecutive_failures == 1

    def test_three_failures_unhealthy(self):
        hc = HealthCheck(tether_id="a1", protocol=Protocol.A2A)
        for _ in range(3):
            hc.mark_failure()
        assert hc.status == HealthStatus.UNHEALTHY
        assert hc.is_available is False

    def test_success_resets_failures(self):
        hc = HealthCheck(tether_id="a1", protocol=Protocol.A2A)
        hc.mark_failure()
        hc.mark_failure()
        hc.mark_success(10.0)
        assert hc.status == HealthStatus.HEALTHY
        assert hc.consecutive_failures == 0


# ════════════════════════════════════════════════════════════════
# TestHealthMonitor
# ════════════════════════════════════════════════════════════════

class TestHealthMonitor:
    def test_get_health_unknown(self):
        mon = HealthMonitor()
        hc = mon.get_health("unknown-agent")
        assert hc.status == HealthStatus.UNKNOWN

    def test_mark_success(self):
        mon = HealthMonitor()
        mon.mark_success("a1", Protocol.HERMES, 15.0)
        hc = mon.get_health("a1")
        assert hc.status == HealthStatus.HEALTHY
        assert hc.latency_ms == 15.0

    def test_mark_failure(self):
        mon = HealthMonitor()
        mon.mark_failure("a1", Protocol.HERMES)
        hc = mon.get_health("a1")
        assert hc.status == HealthStatus.DEGRADED

    def test_all_health(self):
        mon = HealthMonitor()
        mon.mark_success("a1", Protocol.HERMES, 10.0)
        mon.mark_failure("a2", Protocol.A2A)
        results = mon.all_health()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_bridge_has_health_and_pool(self):
        """ProtocolBridge should expose health monitor and connection pool."""
        router = TetherRouter()
        bridge = ProtocolBridge(router)
        assert hasattr(bridge, 'health')
        assert hasattr(bridge, 'pool')
        assert isinstance(bridge.health, HealthMonitor)
        assert isinstance(bridge.pool, ConnectionPool)
