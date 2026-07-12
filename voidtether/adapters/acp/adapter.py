"""ACP Protocol Adapter — bridges stdio-based Agent Client Protocol.

ACP is a JSON-RPC protocol over stdio. This adapter:
  1. Spawns ACP agents as subprocesses with stdin/stdout pipes
  2. Translates TetherTask -> ACP JSON-RPC requests
  3. Pipes requests to agent stdin, reads responses from stdout
  4. Translates ACP responses back to TetherTask results

Key mappings:
  ACP Agent Card  -> TetherManifest
  ACP Task        -> TetherTask
  ACP JSON-RPC    -> TetherEnvelope (over stdio, not network)
  ACP Skills      -> Tether capabilities.tasks
"""

from __future__ import annotations
import asyncio
import json
import os
import shlex
from typing import Any, AsyncGenerator

from voidtether.core.bridge import BaseAdapter
from voidtether.core.manifest import TetherManifest, Protocol, ProtocolEndpoint


class ACPAdapter(BaseAdapter):
    """Adapter for ACP (Agent Client Protocol) agents.
    
    ACP agents communicate via JSON-RPC over stdio. This adapter spawns
    the agent process, manages the stdio pipes, and translates between
    ACP's JSON-RPC protocol and VoidTether's normalized format.
    
    Lifecycle:
      1. spawn: asyncio.create_subprocess_exec(command)
      2. negotiate: send initialize request, receive capabilities
      3. execute: send task requests, receive responses
      4. shutdown: send shutdown notification, terminate process
    """
    
    protocol = Protocol.ACP
    
    INITIALIZE = "initialize"
    TASK_SEND = "task/send"
    SHUTDOWN = "shutdown"
    
    def __init__(self):
        super().__init__()
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._locks: dict[str, asyncio.Lock] = {}
    
    def normalize_output(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert ACP JSON-RPC response to VoidTether format."""
        if "error" in data:
            return {
                "text": data["error"].get("message", "Unknown ACP error"),
                "is_error": True,
                "metadata": {"code": data["error"].get("code", -1)},
            }
        
        result = data.get("result", {})
        artifacts = result.get("artifacts", [])
        text_parts = []
        for art in artifacts:
            if isinstance(art, dict):
                if art.get("type") == "text":
                    text_parts.append(art.get("content", ""))
                elif art.get("type") == "data":
                    text_parts.append(json.dumps(art.get("data", {})))
        
        return {
            "text": "\n".join(text_parts) if text_parts else str(result),
            "status": result.get("status", "completed"),
            "artifacts": artifacts,
            "metadata": result.get("metadata", {}),
            "is_error": False,
        }
    
    def denormalize_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert VoidTether format to ACP JSON-RPC request."""
        message = {
            "role": "user",
            "parts": [],
        }
        
        if "text" in data:
            message["parts"].append({"type": "text", "text": data["text"]})
        if "input" in data:
            message["parts"].append({"type": "data", "data": data["input"]})
        if not message["parts"]:
            message["parts"].append({"type": "text", "text": str(data)})
        
        return {
            "jsonrpc": "2.0",
            "method": self.TASK_SEND,
            "params": {"message": message},
        }
    
    async def _ensure_process(self, manifest: TetherManifest) -> asyncio.subprocess.Process | None:
        """Spawn or retrieve the ACP agent subprocess."""
        tether_id = manifest.tether_id
        
        if tether_id in self._processes:
            proc = self._processes[tether_id]
            if proc.returncode is not None:
                del self._processes[tether_id]
                self._locks.pop(tether_id, None)
            else:
                return proc
        
        acp_command = None
        for p in manifest.protocols:
            if p.protocol == Protocol.ACP:
                acp_command = p.acp_command
                break
        
        if not acp_command:
            return None
        
        cmd_parts = shlex.split(acp_command)
        env = os.environ.copy()
        env["ACP_TRANSPORT"] = "stdio"
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._processes[tether_id] = proc
            self._locks[tether_id] = asyncio.Lock()
            
            init_request = {
                "jsonrpc": "2.0",
                "id": f"init-{tether_id}",
                "method": self.INITIALIZE,
                "params": {
                    "client_id": "voidtether",
                    "client_version": "0.4.0",
                },
            }
            await self._send_rpc(proc, init_request)
            response = await self._read_rpc(proc, timeout=10.0)
            
            return proc
        except Exception:
            return None
    
    async def _send_rpc(self, proc: asyncio.subprocess.Process, request: dict) -> None:
        """Send a JSON-RPC message to the agent's stdin."""
        data = json.dumps(request) + "\n"
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.write(data.encode())
            await proc.stdin.drain()
    
    async def _read_rpc(self, proc: asyncio.subprocess.Process, timeout: float = 120.0) -> dict:
        """Read a JSON-RPC response from the agent's stdout."""
        if not proc.stdout:
            raise RuntimeError("ACP agent stdout not available")
        
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        if not line:
            raise RuntimeError("ACP agent closed stdout (process may have died)")
        return json.loads(line.decode().strip())
    
    async def execute(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a task via ACP stdio protocol."""
        tether_id = manifest.tether_id
        
        lock = self._locks.get(tether_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[tether_id] = lock
        
        async with lock:
            proc = await self._ensure_process(manifest)
            if not proc:
                return {"error": f"Failed to spawn ACP agent for {tether_id}"}
            
            self._request_counter = getattr(self, '_request_counter', 0) + 1
            req_id = f"task-{self._request_counter}"
            
            request = self.denormalize_input({
                "task_type": task_type,
                "input": input_data,
            })
            request["id"] = req_id
            request["params"]["task_type"] = task_type
            
            try:
                await self._send_rpc(proc, request)
                response = await self._read_rpc(proc, timeout=120.0)
                return self.normalize_output(response)
            except asyncio.TimeoutError:
                return {"error": f"ACP agent timed out on task '{task_type}'"}
            except Exception as exc:
                return {"error": f"ACP agent communication failed: {exc}"}
    
    async def execute_stream(self, manifest: TetherManifest, task_type: str, input_data: dict[str, Any]) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a task via ACP. Falls back to single-shot."""
        result = await self.execute(manifest, task_type, input_data)
        yield result
    
    async def shutdown_agent(self, tether_id: str) -> None:
        """Gracefully shut down an ACP agent process."""
        proc = self._processes.get(tether_id)
        if not proc or proc.returncode is not None:
            return
        
        try:
            await self._send_rpc(proc, {
                "jsonrpc": "2.0",
                "method": self.SHUTDOWN,
                "params": {},
            })
        except Exception:
            pass
        
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            proc.kill()
        
        self._processes.pop(tether_id, None)
        self._locks.pop(tether_id, None)
    
    async def shutdown_all(self) -> None:
        """Shut down all managed ACP agent processes."""
        for tether_id in list(self._processes.keys()):
            await self.shutdown_agent(tether_id)


def acp_manifest_from_config(
    name: str,
    acp_command: str,
    tasks: list[str],
    tether_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TetherManifest:
    """Create a TetherManifest for an ACP agent.
    
    Args:
        name: Display name for this ACP agent
        acp_command: CLI command to spawn the agent (e.g. "claude", "python agent.py")
        tasks: List of task types this agent can handle
        tether_id: Optional custom tether ID
        metadata: Optional metadata dict
    """
    tid = tether_id or f"vt-acp-{name.lower().replace(' ', '-')}"
    return TetherManifest(
        tether_id=tid,
        name=name,
        origin_protocol=Protocol.ACP,
        capabilities={
            "tasks": tasks,
            "modalities": ["text", "structured_output"],
            "streaming": False,
        },
        protocols=[ProtocolEndpoint(
            protocol=Protocol.ACP,
            acp_command=acp_command,
            acp_transport="stdio",
            endpoint_url=f"stdio://{tid}",
        )],
        metadata=metadata or {},
    )
