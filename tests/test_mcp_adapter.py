"""Comprehensive tests for MCP adapter -- stdio/SSE transport, tool discovery, execution, error handling.

Uses an asyncio-based mock MCP server as a subprocess (stdio transport)
to verify the adapter end-to-end.
"""

from __future__ import annotations
import asyncio
import os
from typing import Any

import httpx
import pytest

from voidtether.adapters.mcp.adapter import (
    MCPAdapter,
    MCPClient,
    MCPConnectionPool,
    mcp_tools_to_manifest,
    mcp_manifest_from_config,
    make_request,
    make_notification,
)
from voidtether.core.manifest import (
    TetherManifest,
    Protocol,
    ProtocolEndpoint,
)

# Path to the mock MCP server script (co-located with this test file)
MOCK_SERVER_PATH = os.path.join(os.path.dirname(__file__), "mock_mcp_server.py")
MOCK_SERVER_CMD = f"python3 {MOCK_SERVER_PATH}"


# ════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════

@pytest.fixture
def mcp_stdio_manifest():
    """TetherManifest pointing to the mock stdio MCP server."""
    return TetherManifest(
        tether_id="vt-mcp-mock-stdio",
        name="Mock Stdio MCP",
        origin_protocol=Protocol.MCP,
        capabilities={
            "tasks": ["echo", "add", "error_tool"],
            "modalities": ["text", "structured_output"],
            "streaming": False,
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.MCP,
            endpoint_url=MOCK_SERVER_CMD,
            tools=["echo", "add", "error_tool"],
            config={"transport": "stdio", "timeout": 10.0},
        )],
    )


@pytest.fixture
def mcp_sse_manifest():
    """TetherManifest pointing to a (mock) SSE MCP server."""
    return TetherManifest(
        tether_id="vt-mcp-mock-sse",
        name="Mock SSE MCP",
        origin_protocol=Protocol.MCP,
        capabilities={
            "tasks": ["echo"],
            "modalities": ["text"],
            "streaming": False,
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.MCP,
            endpoint_url="http://127.0.0.1:19876/mcp",
            tools=["echo"],
            config={"transport": "sse", "timeout": 5.0},
        )],
    )


@pytest.fixture
def empty_manifest():
    """Manifest with no MCP protocol endpoint."""
    return TetherManifest(
        tether_id="vt-empty",
        name="Empty",
        origin_protocol=Protocol.MCP,
        capabilities={"tasks": ["echo"]},
        protocols=[],
    )


@pytest.fixture
def adapter():
    """Fresh MCPAdapter instance."""
    return MCPAdapter()


# ════════════════════════════════════════════════════════════════
# Test: JSON-RPC helpers
# ════════════════════════════════════════════════════════════════

class TestJsonRpcHelpers:
    def test_make_request(self):
        req = make_request("tools/list", {})
        assert req["jsonrpc"] == "2.0"
        assert req["method"] == "tools/list"
        assert req["params"] == {}
        assert "id" in req
        assert req["id"] is not None

    def test_make_request_with_id(self):
        req = make_request("initialize", {"foo": "bar"}, request_id="my-id")
        assert req["id"] == "my-id"
        assert req["params"] == {"foo": "bar"}

    def test_make_notification(self):
        notif = make_notification("shutdown", {})
        assert notif["jsonrpc"] == "2.0"
        assert notif["method"] == "shutdown"
        assert "id" not in notif
        assert notif["params"] == {}


# ════════════════════════════════════════════════════════════════
# Test: MCPClient -- stdio transport
# ════════════════════════════════════════════════════════════════

class TestMCPClientStdio:
    """Test raw MCPClient over stdio transport with a real subprocess."""

    @pytest.mark.asyncio
    async def test_connect_and_initialize(self):
        """Connect to the mock server and verify the initialize handshake."""
        client = MCPClient(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        try:
            result = await client.connect()
            assert "protocolVersion" in result
            assert "serverInfo" in result
            assert result["serverInfo"]["name"] == "mock-mcp-server"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_list_tools(self):
        """Discover tools from the mock server."""
        client = MCPClient(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        try:
            await client.connect()
            tools = await client.list_tools()
            assert isinstance(tools, list)
            tool_names = [t["name"] for t in tools]
            assert "echo" in tool_names
            assert "add" in tool_names
            assert "error_tool" in tool_names
            assert len(tools) == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_call_tool_echo(self):
        """Call the echo tool and verify the response."""
        client = MCPClient(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        try:
            await client.connect()
            result = await client.call_tool("echo", {"message": "Hello MCP!"})
            assert "content" in result
            assert result["content"][0]["text"] == "Hello MCP!"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_call_tool_add(self):
        """Call the add tool and verify arithmetic."""
        client = MCPClient(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        try:
            await client.connect()
            result = await client.call_tool("add", {"a": 30, "b": 12})
            assert result["content"][0]["text"] == "42"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_call_tool_error(self):
        """Call error_tool should raise RuntimeError."""
        client = MCPClient(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        try:
            await client.connect()
            with pytest.raises(RuntimeError, match="Tool execution failed"):
                await client.call_tool("error_tool", {})
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        """Calling an unknown tool should raise RuntimeError."""
        client = MCPClient(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        try:
            await client.connect()
            with pytest.raises(RuntimeError, match="Unknown tool"):
                await client.call_tool("nonexistent", {})
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Closing an already-closed client should not raise."""
        client = MCPClient(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        await client.close()  # close before connect -- no-op
        await client.close()  # idempotent

    @pytest.mark.asyncio
    async def test_connect_with_timeout(self):
        """Test connecting to a slow server that times out."""
        slow_cmd = f"python3 {MOCK_SERVER_PATH} --slow"
        client = MCPClient(slow_cmd, transport="stdio", timeout=1.0)
        try:
            with pytest.raises((TimeoutError, asyncio.TimeoutError, RuntimeError)):
                await client.connect()
        finally:
            await client.close()


# ════════════════════════════════════════════════════════════════
# Test: MCPClient -- SSE/HTTP transport (mocked via connection refused)
# ════════════════════════════════════════════════════════════════

class TestMCPClientSSE:
    """Test MCPClient over SSE transport using connection attempts."""

    @pytest.mark.asyncio
    async def test_connect_connection_refused(self):
        """Connecting to a non-listening port should fail gracefully."""
        client = MCPClient(
            "http://127.0.0.1:1/mcp",
            transport="sse",
            timeout=2.0,
        )
        try:
            with pytest.raises((RuntimeError, httpx.ConnectError,
                                httpx.RemoteProtocolError, OSError)):
                await client.connect()
        finally:
            await client.close()


# ════════════════════════════════════════════════════════════════
# Test: MCPConnectionPool
# ════════════════════════════════════════════════════════════════

class TestMCPConnectionPool:
    """Test connection pooling for MCP clients."""

    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        """Acquire a client from pool, use it, and release it back."""
        pool = MCPConnectionPool()
        client = await pool.acquire(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        try:
            tools = await client.list_tools()
            assert len(tools) == 3
        finally:
            await pool.release(client)
        await pool.close_all()

    @pytest.mark.asyncio
    async def test_pool_reuses_connections(self):
        """Pool should reuse released connections by returning the same instance."""
        pool = MCPConnectionPool()
        client_a = await pool.acquire(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        await pool.release(client_a)
        client_b = await pool.acquire(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        # Pool reuses the same instance (correct pooling behavior)
        assert client_b is client_a
        await pool.release(client_b)
        await pool.close_all()

    @pytest.mark.asyncio
    async def test_close_all(self):
        """close_all should close all connections without errors."""
        pool = MCPConnectionPool()
        c1 = await pool.acquire(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        await pool.release(c1)
        c2 = await pool.acquire(MOCK_SERVER_CMD, transport="stdio", timeout=10.0)
        await pool.release(c2)
        await pool.close_all()  # Should not raise


# ════════════════════════════════════════════════════════════════
# Test: MCPAdapter -- normalize / denormalize
# ════════════════════════════════════════════════════════════════

class TestMCPAdapterNormalization:
    """Test the normalize_output and denormalize_input methods."""

    def test_protocol(self):
        assert MCPAdapter().protocol == Protocol.MCP

    def test_normalize_output_text(self):
        adapter = MCPAdapter()
        data = {"content": [{"type": "text", "text": "hello world"}]}
        out = adapter.normalize_output(data)
        assert out["text"] == "hello world"
        assert out["is_error"] is False

    def test_normalize_output_multiple_texts(self):
        adapter = MCPAdapter()
        data = {
            "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ]
        }
        out = adapter.normalize_output(data)
        assert "line1" in out["text"]
        assert "line2" in out["text"]

    def test_normalize_output_image(self):
        adapter = MCPAdapter()
        data = {"content": [{"type": "image", "mimeType": "image/png"}]}
        out = adapter.normalize_output(data)
        assert "[image: image/png]" in out["text"]

    def test_normalize_output_resource(self):
        adapter = MCPAdapter()
        data = {"content": [{"type": "resource", "uri": "file:///data.txt"}]}
        out = adapter.normalize_output(data)
        assert "[resource: file:///data.txt]" in out["text"]

    def test_normalize_output_empty(self):
        adapter = MCPAdapter()
        data = {"status": "ok"}
        out = adapter.normalize_output(data)
        assert "text" in out

    def test_normalize_output_is_error(self):
        adapter = MCPAdapter()
        data = {"content": [{"type": "text", "text": "oops"}], "isError": True}
        out = adapter.normalize_output(data)
        assert out["is_error"] is True
        assert out["text"] == "oops"

    def test_normalize_output_plain_text(self):
        adapter = MCPAdapter()
        data = {"text": "direct text", "isError": False}
        out = adapter.normalize_output(data)
        assert out["text"] == "direct text"

    def test_denormalize_input_with_task_type(self):
        adapter = MCPAdapter()
        out = adapter.denormalize_input({"task_type": "search", "input": {"q": "hello"}})
        assert out["tool_name"] == "search"
        assert out["arguments"] == {"q": "hello"}

    def test_denormalize_input_with_tool_name(self):
        adapter = MCPAdapter()
        out = adapter.denormalize_input({"tool_name": "custom_tool", "arguments": {"x": 1}})
        assert out["tool_name"] == "custom_tool"
        assert out["arguments"] == {"x": 1}

    def test_denormalize_input_defaults(self):
        adapter = MCPAdapter()
        out = adapter.denormalize_input({})
        assert out["tool_name"] == "unknown"
        assert out["arguments"] == {}


# ════════════════════════════════════════════════════════════════
# Test: MCPAdapter -- execute with real stdio subprocess
# ════════════════════════════════════════════════════════════════

class TestMCPAdapterExecute:
    """Integration tests: MCPAdapter.execute() with a real mock subprocess."""

    @pytest.mark.asyncio
    async def test_execute_echo(self, adapter, mcp_stdio_manifest):
        """Execute the echo tool via the adapter."""
        result = await adapter.execute(
            mcp_stdio_manifest, "echo", {"arguments": {"message": "Hello from VoidTether!"}}
        )
        assert result["is_error"] is False
        assert "Hello from VoidTether!" in result["text"]

    @pytest.mark.asyncio
    async def test_execute_add(self, adapter, mcp_stdio_manifest):
        """Execute the add tool via the adapter."""
        result = await adapter.execute(
            mcp_stdio_manifest, "add", {"arguments": {"a": 100, "b": 200}}
        )
        assert result["is_error"] is False
        assert result["text"] == "300"

    @pytest.mark.asyncio
    async def test_execute_no_endpoint(self, adapter, empty_manifest):
        """Execute with no MCP endpoint should return error."""
        result = await adapter.execute(empty_manifest, "echo", {})
        assert result["is_error"] is True
        assert "No MCP endpoint" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_invalid_endpoint(self, adapter):
        """Execute with a non-existent endpoint should return error."""
        manifest = TetherManifest(
            tether_id="vt-mcp-bad",
            name="Bad MCP",
            origin_protocol=Protocol.MCP,
            capabilities={"tasks": ["echo"]},
            protocols=[ProtocolEndpoint(
                protocol=Protocol.MCP,
                endpoint_url="python3 /nonexistent/script.py",
                tools=["echo"],
                config={"transport": "stdio", "timeout": 3.0},
            )],
        )
        result = await adapter.execute(manifest, "echo", {})
        assert result["is_error"] is True
        assert "Failed to connect" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, adapter, mcp_stdio_manifest):
        """Execute a tool not matching the mock server's tools should error."""
        result = await adapter.execute(
            mcp_stdio_manifest, "nonexistent", {"arguments": {}}
        )
        assert result["is_error"] is True

    @pytest.mark.asyncio
    async def test_execute_reuses_connection(self, adapter, mcp_stdio_manifest):
        """Calling execute twice should reuse the same client connection."""
        result1 = await adapter.execute(
            mcp_stdio_manifest, "echo", {"arguments": {"message": "first"}}
        )
        assert result1["is_error"] is False
        assert result1["text"] == "first"

        result2 = await adapter.execute(
            mcp_stdio_manifest, "echo", {"arguments": {"message": "second"}}
        )
        assert result2["is_error"] is False
        assert result2["text"] == "second"

        # Connection should be cached
        assert mcp_stdio_manifest.tether_id in adapter._clients

    @pytest.mark.asyncio
    async def test_discover_tools(self, adapter, mcp_stdio_manifest):
        """Discover tools from the mock server via the adapter."""
        tools = await adapter.discover_tools(mcp_stdio_manifest)
        assert len(tools) == 3
        tool_names = [t["name"] for t in tools]
        assert "echo" in tool_names
        assert "add" in tool_names
        assert "error_tool" in tool_names

    @pytest.mark.asyncio
    async def test_shutdown_agent(self, adapter, mcp_stdio_manifest):
        """Shutting down an agent should close the connection."""
        await adapter.execute(
            mcp_stdio_manifest, "echo", {"arguments": {"message": "hello"}}
        )
        assert mcp_stdio_manifest.tether_id in adapter._clients
        await adapter.shutdown_agent(mcp_stdio_manifest.tether_id)
        assert mcp_stdio_manifest.tether_id not in adapter._clients

    @pytest.mark.asyncio
    async def test_shutdown_all(self, adapter, mcp_stdio_manifest):
        """shutdown_all should close all connections."""
        await adapter.execute(
            mcp_stdio_manifest, "echo", {"arguments": {"message": "hello"}}
        )
        await adapter.shutdown_all()
        assert len(adapter._clients) == 0

    @pytest.mark.asyncio
    async def test_execute_sse_connection_refused(self, adapter, mcp_sse_manifest):
        """SSE transport: connecting to a non-listening port should return error."""
        result = await adapter.execute(
            mcp_sse_manifest, "echo", {"arguments": {"message": "test"}}
        )
        assert result["is_error"] is True

    @pytest.mark.asyncio
    async def test_execute_stream(self, adapter, mcp_stdio_manifest):
        """execute_stream yields the result from execute()."""
        count = 0
        async for chunk in adapter.execute_stream(
            mcp_stdio_manifest, "echo", {"arguments": {"message": "stream test"}}
        ):
            count += 1
            if "is_error" in chunk:
                assert chunk["is_error"] is False
        assert count >= 1


# ════════════════════════════════════════════════════════════════
# Test: mcp_tools_to_manifest / mcp_manifest_from_config
# ════════════════════════════════════════════════════════════════

class TestManifestBuilders:
    """Test the manifest builder utility functions."""

    def test_mcp_tools_to_manifest_http(self):
        """mcp_tools_to_manifest with HTTP URL should use SSE transport."""
        tools = [
            {"name": "search", "description": "Search the web", "inputSchema": {}},
            {"name": "read", "description": "Read a URL", "inputSchema": {}},
        ]
        manifest = mcp_tools_to_manifest(
            "http://localhost:8787/mcp", tools, name="Test MCP"
        )
        assert manifest.origin_protocol == Protocol.MCP
        assert "search" in manifest.tasks
        assert "read" in manifest.tasks
        assert manifest.protocols[0].endpoint_url == "http://localhost:8787/mcp"
        assert manifest.protocols[0].config["transport"] == "sse"

    def test_mcp_tools_to_manifest_stdio(self):
        """mcp_tools_to_manifest with a command should use stdio transport."""
        tools = [{"name": "echo", "description": "Echo back"}]
        manifest = mcp_tools_to_manifest(
            "python3 server.py", tools, name="Local MCP"
        )
        assert manifest.protocols[0].config["transport"] == "stdio"
        assert "echo" in manifest.tasks

    def test_mcp_manifest_from_config_with_tasks(self):
        """mcp_manifest_from_config with explicit task list."""
        manifest = mcp_manifest_from_config(
            name="My MCP Server",
            command="python3 server.py",
            tasks=["search", "read"],
            timeout=15.0,
        )
        assert manifest.origin_protocol == Protocol.MCP
        assert manifest.tether_id == "vt-mcp-my-mcp-server"
        assert manifest.tasks == ["search", "read"]
        assert manifest.protocols[0].config["timeout"] == 15.0
        assert manifest.protocols[0].config["transport"] == "stdio"

    def test_mcp_manifest_from_config_with_tools(self):
        """mcp_manifest_from_config with full tool descriptors."""
        tools = [
            {"name": "search", "description": "Search", "inputSchema": {}},
            {"name": "read", "description": "Read", "inputSchema": {}},
        ]
        manifest = mcp_manifest_from_config(
            name="Tool MCP",
            command="python3 server.py",
            tools=tools,
            tether_id="custom-id",
        )
        assert manifest.tether_id == "custom-id"
        assert manifest.tasks == ["search", "read"]
        assert "tool_details" in manifest.protocols[0].config

    def test_mcp_manifest_from_config_http_detects_sse(self):
        """HTTP URL should auto-detect SSE transport."""
        manifest = mcp_manifest_from_config(
            name="Remote MCP",
            command="https://mcp.example.com/api",
            tasks=["search"],
        )
        assert manifest.protocols[0].config["transport"] == "sse"

    def test_mcp_manifest_from_config_empty_tools(self):
        """Empty tasks/tools should result in empty tool list."""
        manifest = mcp_manifest_from_config(
            name="Empty MCP",
            command="python3 server.py",
        )
        assert manifest.tasks == []

    def test_mcp_tools_to_manifest_tool_details(self):
        """Tool details should be preserved in config."""
        tools = [
            {"name": "search", "description": "Search the web",
             "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}},
        ]
        manifest = mcp_tools_to_manifest("http://localhost:8787/mcp", tools)
        details = manifest.protocols[0].config["tool_details"]
        assert "search" in details
        assert details["search"]["description"] == "Search the web"


# ════════════════════════════════════════════════════════════════
# Test: MCPAdapter -- edge cases and error handling
# ════════════════════════════════════════════════════════════════

class TestMCPAdapterEdgeCases:
    """Edge cases and error scenarios for the MCP adapter."""

    @pytest.mark.asyncio
    async def test_execute_with_raw_string_input(self, adapter, mcp_stdio_manifest):
        """Adapter should handle non-dict input gracefully."""
        result = await adapter.execute(mcp_stdio_manifest, "echo", "raw string")
        # Should not crash; the client builds arguments from task_type
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_double_shutdown(self, adapter, mcp_stdio_manifest):
        """Calling shutdown_agent twice should be safe."""
        await adapter.execute(
            mcp_stdio_manifest, "echo", {"arguments": {"message": "test"}}
        )
        await adapter.shutdown_agent(mcp_stdio_manifest.tether_id)
        await adapter.shutdown_agent(mcp_stdio_manifest.tether_id)  # idempotent
        assert mcp_stdio_manifest.tether_id not in adapter._clients

    @pytest.mark.asyncio
    async def test_discover_tools_no_endpoint(self, adapter, empty_manifest):
        """Discover tools with no endpoint should return empty list."""
        tools = await adapter.discover_tools(empty_manifest)
        assert tools == []
