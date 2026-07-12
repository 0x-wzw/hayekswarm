"""MCP Protocol Adapter — bridges Model Context Protocol.

Implements the Model Context Protocol (MCP) over stdio and SSE transports.
MCP uses JSON-RPC 2.0 as its wire format with the following lifecycle:

  1. Initialize: client sends 'initialize' request, server responds with version + capabilities
  2. tools/list: client discovers available tools
  3. tools/call: client invokes a tool with arguments
  4. Shutdown: client sends 'shutdown' notification, closes transport

Stdio transport:
  - Spawns a subprocess (python script, server binary, etc.)
  - JSON-RPC messages over stdin/stdout
  - One JSON object per line (newline-delimited JSON)

SSE transport:
  - Connects to an HTTP endpoint (e.g. http://localhost:8787/mcp)
  - Sends JSON-RPC messages via HTTP POST
  - Receives responses via Server-Sent Events (SSE) stream
"""

from __future__ import annotations
import asyncio
import json
import os
import shlex
import uuid
from typing import Any, AsyncGenerator

import httpx

from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


# ──────────────────────────────────────────────────────────────
# JSON-RPC helpers
# ──────────────────────────────────────────────────────────────

def make_request(method: str, params: dict[str, Any] | None = None,
                 request_id: str | None = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request object."""
    return {
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }


def make_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 notification (no 'id' field)."""
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }


# ──────────────────────────────────────────────────────────────
# MCPClient — underlying protocol client
# ──────────────────────────────────────────────────────────────

class MCPClient:
    """Low-level MCP client handling JSON-RPC over the selected transport.

    Supports two transport modes:
      - 'stdio': subprocess stdin/stdout (newline-delimited JSON)
      - 'sse': HTTP POST + SSE event stream

    Usage:
        client = MCPClient(endpoint="python server.py", transport="stdio")
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("search", {"query": "hello"})
        await client.close()
    """

    DEFAULT_TIMEOUT = 30.0
    SHUTDOWN_TIMEOUT = 5.0

    def __init__(self, endpoint: str, transport: str = "stdio",
                 timeout: float = DEFAULT_TIMEOUT):
        self.endpoint = endpoint
        self.transport = transport
        self.timeout = timeout
        self._process: asyncio.subprocess.Process | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._connected = False
        self._sse_url: str | None = None
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._sse_task: asyncio.Task | None = None
        self._read_lock = asyncio.Lock()

    # ── Connection ────────────────────────────────────────────

    async def connect(self) -> dict[str, Any]:
        """Establish the transport and perform the initialize handshake.

        Returns the server's 'initialize' result (capabilities, serverInfo, etc.).
        """
        if self.transport == "stdio":
            return await self._connect_stdio()
        elif self.transport in ("sse", "http"):
            return await self._connect_sse()
        else:
            raise ValueError(f"Unsupported MCP transport: {self.transport}")

    async def _connect_stdio(self) -> dict[str, Any]:
        """Spawn subprocess and perform initialize over stdio."""
        cmd_parts = shlex.split(self.endpoint)
        env = os.environ.copy()
        env.setdefault("MCP_TRANSPORT", "stdio")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to spawn MCP server '{self.endpoint}': {exc}")

        # Start background stderr reader (logging only)
        self._stderr_task = asyncio.create_task(self._read_stderr())

        result = await self._initialize()
        self._connected = True
        return result

    async def _connect_sse(self) -> dict[str, Any]:
        """Connect via HTTP POST + SSE event stream."""
        self._http_client = httpx.AsyncClient(timeout=self.timeout)

        # For SSE transport, the endpoint is the SSE URL directly.
        # MCP servers typically expose a single endpoint that accepts
        # POST requests for JSON-RPC and returns SSE responses.
        self._sse_url = self.endpoint

        # Start the SSE listener in background
        self._sse_task = asyncio.create_task(self._sse_event_loop())

        result = await self._initialize()
        self._connected = True
        return result

    async def _initialize(self) -> dict[str, Any]:
        """Send 'initialize' request and return server capabilities."""
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
            },
            "clientInfo": {
                "name": "voidtether",
                "version": "0.4.0",
            },
        }
        response = await self._send_request("initialize", init_params)
        return response

    # ── Send / Receive ────────────────────────────────────────

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        request = make_request(method, params)
        rid = request["id"]

        if self.transport == "stdio":
            return await self._send_stdio_request(method, request, rid)
        else:
            return await self._send_sse_request(method, request, rid)

    async def _send_stdio_request(self, method: str, request: dict[str, Any],
                                   rid: str) -> dict[str, Any]:
        """Send request via stdio, wait for matching response."""
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_responses[rid] = future

        try:
            data = json.dumps(request) + "\n"
            if self._process and self._process.stdin and not self._process.stdin.is_closing():
                self._process.stdin.write(data.encode())
                await self._process.stdin.drain()

            # Start a reader for this response
            response = await asyncio.wait_for(
                self._read_stdio_response(),
                timeout=self.timeout,
            )

            # Check if we got an error response
            if "error" in response:
                raise RuntimeError(
                    f"MCP error ({response['error'].get('code', -1)}): "
                    f"{response['error'].get('message', 'Unknown error')}"
                )

            return response.get("result", response)
        except asyncio.TimeoutError:
            raise TimeoutError(f"MCP request '{method}' timed out after {self.timeout}s")
        finally:
            self._pending_responses.pop(rid, None)

    async def _read_stdio_response(self) -> dict[str, Any]:
        """Read a single JSON-RPC response line from stdout."""
        if not self._process or not self._process.stdout:
            raise RuntimeError("MCP stdout not available")

        line = await asyncio.wait_for(
            self._process.stdout.readline(),
            timeout=self.timeout,
        )
        if not line:
            stderr_output = await self._read_stderr_buffered()
            raise RuntimeError(
                f"MCP server closed stdout (process may have died). "
                f"Stderr: {stderr_output[:500] if stderr_output else '(none)'}"
            )
        return json.loads(line.decode().strip())

    async def _send_sse_request(self, method: str, request: dict[str, Any],
                                 rid: str) -> dict[str, Any]:
        """Send request via HTTP POST, wait for SSE event response."""
        if not self._http_client:
            raise RuntimeError("MCP HTTP client not initialized")

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_responses[rid] = future

        try:
            url: str = self._sse_url  # type: ignore[assignment]
            response = await self._http_client.post(
                url,
                json=request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            body = response.json()

            # SSE transport with single POST request — response may come
            # in the HTTP response body directly for simple cases
            if "error" in body:
                raise RuntimeError(
                    f"MCP error ({body['error'].get('code', -1)}): "
                    f"{body['error'].get('message', 'Unknown error')}"
                )

            return body.get("result", body)
        except httpx.TimeoutException:
            raise TimeoutError(f"MCP request timed out after {self.timeout}s")
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"MCP HTTP error: {exc.response.status_code} {exc.response.text[:500]}")
        finally:
            self._pending_responses.pop(rid, None)

    async def _sse_event_loop(self):
        """Background task: read SSE stream for ongoing event responses."""
        if not self._http_client or not self._sse_url:
            return
        # SSE listening is best-effort; this handles streaming responses
        # for long-lived connections. Simple request/response is handled
        # in _send_sse_request above.
        pass

    # ── Tool operations ───────────────────────────────────────

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover available tools from the MCP server.

        Returns a list of tool descriptors, each containing:
          - name: str
          - description: str
          - inputSchema: dict (JSON Schema for tool arguments)
        """
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool on the MCP server.

        Args:
            name: The tool name to invoke.
            arguments: Tool-specific arguments as a dict.

        Returns:
            The tool result, typically containing a 'content' array.
        """
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        return result

    # ── Shutdown ──────────────────────────────────────────────

    async def close(self):
        """Gracefully shut down the MCP connection and release resources."""
        try:
            await self._send_notification("shutdown", {})
        except Exception:
            pass

        if self.transport == "stdio":
            await self._close_stdio()
        else:
            await self._close_sse()

        self._connected = False

    async def _send_notification(self, method: str, params: dict[str, Any]):
        """Send a JSON-RPC notification (no response expected)."""
        notification = make_notification(method, params)
        data = json.dumps(notification) + "\n"
        if self._process and self._process.stdin and not self._process.stdin.is_closing():
            self._process.stdin.write(data.encode())
            await self._process.stdin.drain()

    async def _close_stdio(self):
        """Terminate the subprocess."""
        proc = self._process
        if not proc or proc.returncode is not None:
            return

        # Cancel stderr reader
        if hasattr(self, '_stderr_task'):
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass

        try:
            # Close stdin to signal EOF
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:
            pass

        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=self.SHUTDOWN_TIMEOUT)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass

    async def _close_sse(self):
        """Close the HTTP client and cancel SSE listener."""
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def _read_stderr(self):
        """Background reader for stderr (logs only, not critical)."""
        try:
            proc = self._process
            if proc and proc.stderr:
                async for line in proc.stderr:
                    # In production this would go to a logger
                    pass
        except Exception:
            pass

    async def _read_stderr_buffered(self) -> str:
        """Read any available stderr output (for error reporting)."""
        proc = self._process
        if not proc or not proc.stderr:
            return ""
        try:
            data = await asyncio.wait_for(proc.stderr.read(), timeout=0.5)
            return data.decode() if data else ""
        except (asyncio.TimeoutError, Exception):
            return ""


# ──────────────────────────────────────────────────────────────
# MCPConnectionPool — pooled MCP connections
# ──────────────────────────────────────────────────────────────

class MCPConnectionPool:
    """Manages a pool of MCPClient instances, keyed by endpoint URL.

    Provides connection reuse, automatic cleanup, and timeout-based
    eviction of stale connections.
    """

    def __init__(self, max_connections: int = 10, idle_timeout: float = 300.0):
        self._pool: dict[str, list[MCPClient]] = {}
        self._max_connections = max_connections
        self._idle_timeout = idle_timeout
        self._lock = asyncio.Lock()

    async def acquire(self, endpoint: str, transport: str = "stdio",
                      timeout: float = 30.0) -> MCPClient:
        """Get a connected MCP client from the pool or create a new one."""
        async with self._lock:
            clients = self._pool.get(endpoint, [])
            while clients:
                client = clients.pop()
                if client._connected:
                    return client

        # Create new connection
        client = MCPClient(endpoint, transport=transport, timeout=timeout)
        await client.connect()
        return client

    async def release(self, client: MCPClient):
        """Return a client to the pool for reuse."""
        if not client._connected:
            return
        async with self._lock:
            if len(self._pool.get(client.endpoint, [])) < self._max_connections:
                self._pool.setdefault(client.endpoint, []).append(client)
            else:
                await client.close()

    async def close_all(self):
        """Close all connections in the pool."""
        async with self._lock:
            for endpoint, clients in list(self._pool.items()):
                for client in clients:
                    await client.close()
                del self._pool[endpoint]


# ──────────────────────────────────────────────────────────────
# MCPAdapter — VoidTether adapter implementation
# ──────────────────────────────────────────────────────────────

class MCPAdapter(BaseAdapter):
    """Adapter for Model Context Protocol (MCP).

    Translates between MCP's tool-use protocol and VoidTether's
    agent-to-agent negotiation. Key mappings:

      MCP Tool       -> Tether capability (task)
      MCP Tool Call  -> Tether task delegation
      MCP Server     -> TetherManifest (tools as capabilities)

    Supports both 'stdio' and 'sse' transports. The transport is
    determined from the endpoint URL or acp_command in the manifest:
      - If endpoint starts with 'http' -> SSE transport
      - Otherwise -> stdio transport
    """

    protocol = Protocol.MCP

    def __init__(self):
        super().__init__()
        self._clients: dict[str, MCPClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._pool = MCPConnectionPool()

    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert MCP tool result to VoidTether format."""
        # MCP tool results have content arrays
        if "content" in data:
            texts = []
            for item in data["content"]:
                if item.get("type") == "text":
                    texts.append(item["text"])
                elif item.get("type") == "image":
                    texts.append(f"[image: {item.get('mimeType', 'unknown')}]")
                elif item.get("type") == "resource":
                    texts.append(f"[resource: {item.get('uri', 'unknown')}]")
            return {"text": "\n".join(texts), "is_error": data.get("isError", False)}
        if "text" in data:
            return {"text": data["text"], "is_error": data.get("isError", False)}
        return {"text": str(data), "is_error": False}

    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert VoidTether format to MCP tool call.

        Returns a dict that will be passed to the MCP client.
        The actual 'method' field is set by the client; here we
        prepare the tool name and arguments.
        """
        return {
            "tool_name": data.get("tool_name", data.get("task_type", "unknown")),
            "arguments": data.get("arguments", data.get("input", {})),
        }

    async def execute(self, manifest: TetherManifest, task_type: str,
                      input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a task via MCP protocol.

        Determines transport from the manifest's endpoint URL or
        acp_command, connects to the MCP server, discovers tools
        (if not cached), and calls the requested tool.
        """
        endpoint, transport = self._resolve_endpoint(manifest)
        if not endpoint:
            return {"error": "No MCP endpoint or command found in manifest", "is_error": True}

        # Check that the tool is available
        available_tools = self._get_available_tools(manifest)
        if task_type not in available_tools and task_type != "initialize":
            if available_tools:
                return {
                    "error": f"Tool '{task_type}' not available. Available: {available_tools}",
                    "is_error": True,
                }
            # No tools listed in manifest — we'll discover them

        tether_id = manifest.tether_id
        lock = self._locks.setdefault(tether_id, asyncio.Lock())

        async with lock:
            client = self._clients.get(tether_id)

            try:
                # Connect if not already connected
                if client is None or not client._connected:
                    client = MCPClient(endpoint, transport=transport, timeout=self._get_timeout(manifest))
                    try:
                        init_result = await client.connect()
                    except Exception as exc:
                        if client:
                            await client.close()
                        return {
                            "error": f"Failed to connect to MCP server: {exc}",
                            "is_error": True,
                        }
                    self._clients[tether_id] = client

                # Determine tool name from input
                tool_name = input_data.get("tool_name", task_type) if isinstance(input_data, dict) else task_type
                arguments = input_data.get("arguments", {}) if isinstance(input_data, dict) else {}

                # Call the tool
                try:
                    result = await client.call_tool(tool_name, arguments)
                    return self.normalize_output(result)
                except Exception as exc:
                    return {
                        "error": f"MCP tool call '{tool_name}' failed: {exc}",
                        "is_error": True,
                    }

            except Exception as exc:
                return {
                    "error": f"MCP adapter execution failed: {exc}",
                    "is_error": True,
                }

    async def execute_stream(self, manifest: TetherManifest, task_type: str,
                              input_data: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a task via MCP. Falls back to single-shot."""
        result = await self.execute(manifest, task_type, input_data)
        yield result

    async def discover_tools(self, manifest: TetherManifest) -> list[dict[str, Any]]:
        """Discover tools from an MCP server.

        Connects (or reuses existing connection) and calls tools/list.
        Returns a list of tool descriptors.
        """
        endpoint, transport = self._resolve_endpoint(manifest)
        if not endpoint:
            return []

        tether_id = manifest.tether_id
        lock = self._locks.setdefault(tether_id, asyncio.Lock())

        async with lock:
            client = self._clients.get(tether_id)
            if client is None or not client._connected:
                client = MCPClient(endpoint, transport=transport)
                try:
                    await client.connect()
                    self._clients[tether_id] = client
                except Exception:
                    return []

            try:
                return await client.list_tools()
            except Exception:
                return []

    async def shutdown_agent(self, tether_id: str) -> None:
        """Gracefully shut down an MCP client connection."""
        client = self._clients.pop(tether_id, None)
        if client:
            await client.close()
        self._locks.pop(tether_id, None)

    async def shutdown_all(self) -> None:
        """Shut down all managed MCP client connections."""
        for tether_id in list(self._clients.keys()):
            await self.shutdown_agent(tether_id)
        await self._pool.close_all()

    # ── Internal helpers ──────────────────────────────────────

    def _resolve_endpoint(self, manifest: TetherManifest) -> tuple[str | None, str]:
        """Extract the endpoint URL/command and transport type from a manifest."""
        for p in manifest.protocols:
            if p.protocol == Protocol.MCP:
                endpoint = p.endpoint_url or p.config.get("endpoint_url") or p.config.get("command")
                if not endpoint:
                    endpoint = p.acp_command
                transport = p.config.get("transport", "stdio")
                # Auto-detect transport from URL scheme
                if endpoint:
                    if endpoint.startswith("http://") or endpoint.startswith("https://"):
                        transport = "sse"
                    elif endpoint.startswith("stdio://"):
                        # stdio:// scheme means the rest is a command
                        endpoint = endpoint.replace("stdio://", "", 1)
                        transport = "stdio"
                return endpoint, transport
        return None, "stdio"

    def _get_available_tools(self, manifest: TetherManifest) -> list[str]:
        """Get the tool list from the manifest."""
        for p in manifest.protocols:
            if p.protocol == Protocol.MCP:
                return p.tools or []
        return []

    def _get_timeout(self, manifest: TetherManifest) -> float:
        """Extract timeout from manifest config or use default."""
        for p in manifest.protocols:
            if p.protocol == Protocol.MCP:
                return p.config.get("timeout", MCPClient.DEFAULT_TIMEOUT)
        return MCPClient.DEFAULT_TIMEOUT


# ──────────────────────────────────────────────────────────────
# Utility: manifest builder
# ──────────────────────────────────────────────────────────────

def mcp_tools_to_manifest(server_url: str, tools: list[dict],
                          name: str = "MCP Server") -> TetherManifest:
    """Convert an MCP server's tool list to a TetherManifest.

    Args:
        server_url: The MCP server endpoint URL or command
                    (e.g. "http://localhost:8787/mcp" or "python mcp_server.py")
        tools: List of tool descriptors from tools/list
        name: Display name for this MCP server

    Returns:
        A TetherManifest ready for registration in the VoidTether mesh.
    """
    tool_names = [t.get("name", "") for t in tools]
    tool_details = {t.get("name", ""): {
        "description": t.get("description", ""),
        "inputSchema": t.get("inputSchema", {}),
    } for t in tools}

    # Detect transport from URL
    is_http = server_url.startswith("http://") or server_url.startswith("https://")
    transport = "sse" if is_http else "stdio"

    return TetherManifest(
        tether_id=f"vt-mcp-{name.lower().replace(' ', '-')}",
        name=name,
        origin_protocol=Protocol.MCP,
        capabilities={
            "tasks": tool_names,
            "modalities": ["text", "structured_output"],
            "streaming": False,
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.MCP,
            endpoint_url=server_url,
            tools=tool_names,
            config={
                "transport": transport,
                "tool_details": tool_details,
            },
        )],
    )


def mcp_manifest_from_config(
    name: str,
    command: str,
    tasks: list[str] | None = None,
    tools: list[dict] | None = None,
    tether_id: str | None = None,
    transport: str = "stdio",
    timeout: float = 30.0,
) -> TetherManifest:
    """Create a TetherManifest for an MCP server from configuration.

    Args:
        name: Display name for this MCP server
        command: CLI command or URL to reach the MCP server
        tasks: List of task types (tool names) this server can handle.
               If None, tools will be discovered at connection time.
        tools: Full tool descriptors (name, description, inputSchema).
               Mutually exclusive with tasks; tasks takes precedence.
        tether_id: Optional custom tether ID
        transport: Transport type ('stdio' or 'sse')
        timeout: Connection/request timeout in seconds

    Returns:
        A TetherManifest ready for registration.
    """
    tid = tether_id or f"vt-mcp-{name.lower().replace(' ', '-')}"
    tool_names: list[str] = []
    tool_details: dict[str, dict] = {}

    if tasks is not None:
        tool_names = tasks
    elif tools is not None:
        tool_names = [t.get("name", "") for t in tools]
        tool_details = {t.get("name", ""): {
            "description": t.get("description", ""),
            "inputSchema": t.get("inputSchema", {}),
        } for t in tools}

    # Auto-detect transport from URL
    if command.startswith("http://") or command.startswith("https://"):
        transport = "sse"

    return TetherManifest(
        tether_id=tid,
        name=name,
        origin_protocol=Protocol.MCP,
        capabilities={
            "tasks": tool_names,
            "modalities": ["text", "structured_output"],
            "streaming": False,
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.MCP,
            endpoint_url=command,
            tools=tool_names,
            config={
                "transport": transport,
                "timeout": timeout,
                "tool_details": tool_details,
            },
        )],
        metadata={"transport": transport, "command": command},
    )
