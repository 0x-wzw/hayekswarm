#!/usr/bin/env python3
"""ACP Stdio Bridge — connects ACP agents to the VoidTether Hub.

Uses raw JSON-RPC over stdio with correct ACP protocol semantics.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import signal
import sys
import logging
from typing import Any

logger = logging.getLogger("voidtether.acp_bridge")


class ACPStdioBridge:
    """Bridges an ACP stdio agent to the VoidTether Hub over Tailscale."""
    
    def __init__(
        self,
        tether_id: str,
        name: str,
        agent_command: str,
        tasks: list[str],
        secret: str,
        hub_url: str,
    ):
        self.tether_id = tether_id
        self.name = name
        self.agent_command = agent_command
        self.tasks = tasks
        self.secret = secret
        self.hub_url = hub_url
        
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._running = False
        self._session_id: str = ""
        self._req_counter = 0
    
    async def _send(self, data: dict) -> None:
        if not self._process or not self._process.stdin or self._process.stdin.is_closing():
            raise RuntimeError("ACP agent stdin not available")
        line = json.dumps(data) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()
    
    async def _read_response(self, expected_id: str, timeout: float = 120.0) -> dict:
        """Read until we get a JSON-RPC response with the expected id.
        
        Captures streaming text from session/update notifications along the way.
        """
        if not self._process or not self._process.stdout:
            raise RuntimeError("ACP agent stdout not available")
        
        captured_text = ""
        while True:
            line = await asyncio.wait_for(self._process.stdout.readline(), timeout=timeout)
            if not line:
                raise RuntimeError("ACP agent closed stdout")
            try:
                data = json.loads(line.decode().strip())
            except json.JSONDecodeError:
                continue
            
            # Capture streaming text from session/update notifications
            if data.get("method") == "session/update":
                update = data.get("params", {}).get("update", {})
                if update.get("sessionUpdate") == "agent_message_chunk":
                    content = update.get("content", {})
                    if isinstance(content, dict) and content.get("type") == "text":
                        captured_text += content.get("text", "")
                continue
            
            # Skip other notifications
            if data.get("id") is None:
                continue
            
            # This is the response we're waiting for
            if data.get("id") == expected_id:
                if captured_text:
                    data["_captured_text"] = captured_text
                return data
    
    async def _drain_notifications(self, timeout: float = 0.5) -> None:
        """Drain any pending notifications."""
        if not self._process or not self._process.stdout:
            return
        try:
            while True:
                line = await asyncio.wait_for(self._process.stdout.readline(), timeout=timeout)
                if not line:
                    break
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
    
    async def spawn_agent(self) -> bool:
        """Spawn the ACP agent and create a session."""
        cmd_parts = self.agent_command.split()
        env = os.environ.copy()
        env["ACP_TRANSPORT"] = "stdio"
        
        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            logger.info(f"ACP agent spawned: {self.agent_command} (PID {self._process.pid})")
            
            # Initialize
            await self._send({
                "jsonrpc": "2.0", "id": "init",
                "method": "initialize",
                "params": {
                    "protocol_version": 1,
                    "client_info": {"name": "voidtether-bridge", "version": "0.4.0"},
                },
            })
            resp = await self._read_response("init")
            logger.info("ACP agent initialized")
            
            # New session
            await self._send({
                "jsonrpc": "2.0", "id": "ns",
                "method": "session/new",
                "params": {"cwd": os.getcwd(), "mcpServers": []},
            })
            resp = await self._read_response("ns")
            result = resp.get("result", {})
            meta = result.get("_meta", {}) or {}
            hermes_meta = meta.get("hermes", {}) if isinstance(meta, dict) else {}
            provenance = hermes_meta.get("sessionProvenance", {}) if isinstance(hermes_meta, dict) else {}
            self._session_id = (
                provenance.get("acpSessionId")
                or result.get("session_id")
                or result.get("sessionId")
                or ""
            )
            logger.info(f"ACP session created: {self._session_id}")
            
            # Drain post-session notifications
            await self._drain_notifications()
            
            return True
        except Exception as exc:
            logger.error(f"Failed to spawn ACP agent: {exc}")
            return False
    
    async def execute_prompt(self, text: str) -> dict[str, Any]:
        """Send a prompt to the ACP agent and return the result."""
        async with self._lock:
            self._req_counter += 1
            req_id = f"p{self._req_counter}"
            
            await self._send({
                "jsonrpc": "2.0", "id": req_id,
                "method": "session/prompt",
                "params": {
                    "session_id": self._session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            })
            
            try:
                resp = await self._read_response(req_id, timeout=120.0)
                
                if "error" in resp:
                    return {"error": resp["error"].get("message", "ACP error"), "is_error": True}
                
                captured = resp.get("_captured_text", "")
                result = resp.get("result", {})
                
                return {
                    "status": result.get("stopReason", "completed"),
                    "text": captured or str(result),
                }
            except asyncio.TimeoutError:
                return {"error": "ACP agent timed out", "is_error": True}
            except Exception as exc:
                return {"error": f"ACP agent error: {exc}", "is_error": True}
    
    async def shutdown(self) -> None:
        if not self._process or self._process.returncode is not None:
            return
        try:
            self._process.terminate()
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            if self._process:
                self._process.kill()
    
    async def run(self) -> None:
        """Main bridge loop."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'sdk'))
        from client import VoidTetherClient
        
        # Spawn ACP agent
        if not await self.spawn_agent():
            logger.error("Failed to spawn ACP agent. Exiting.")
            return
        
        # Connect to hub
        client = VoidTetherClient(
            hub_url=self.hub_url,
            secret=self.secret,
            tether_id=self.tether_id,
            name=self.name,
            protocol="acp",
            capabilities={"tasks": self.tasks, "modalities": ["text", "structured_output"], "streaming": False},
        )
        
        async with client:
            await client.register()
            logger.info(f"Bridge connected to hub: {self.tether_id}")
            
            session = await client.create_session(
                title=f"ACP Bridge: {self.name}",
                participants=[self.tether_id],
            )
            session_id = session["session_id"]
            logger.info(f"Bridge session: {session_id}")
            
            self._running = True
            
            import websockets
            
            ws_url = self.hub_url.replace("http", "ws").replace("https", "wss")
            ws_uri = f"{ws_url}/ws/{session_id}"
            
            while self._running:
                try:
                    async with websockets.connect(ws_uri) as ws:
                        await ws.recv()  # Skip history
                        logger.info("WebSocket connected, listening for tasks...")
                        
                        while self._running:
                            msg = await ws.recv()
                            data = json.loads(msg)
                            
                            event_type = data.get("event_type", data.get("type", ""))
                            if event_type == "message":
                                content = data.get("content", "")
                                sender = data.get("sender", "")
                                role = data.get("role", "user")
                                
                                if sender == self.tether_id:
                                    continue
                                
                                if role == "user" and content:
                                    logger.info(f"Received: {content[:80]}")
                                    result = await self.execute_prompt(content)
                                    
                                    response_text = result.get("text", json.dumps(result))
                                    await ws.send(json.dumps({
                                        "type": "message",
                                        "content": response_text,
                                        "role": "agent",
                                        "sender": self.tether_id,
                                        "sender_name": self.name,
                                    }))
                                    
                                    await client.send_message(
                                        session_id,
                                        response_text,
                                        role="agent",
                                    )
                
                except Exception as exc:
                    if not self._running:
                        break
                    logger.warning(f"WebSocket disconnected: {exc}, reconnecting in 3s...")
                    await asyncio.sleep(3)
        
        await self.shutdown()
        logger.info("Bridge shut down.")
    
    def stop(self) -> None:
        self._running = False


def main():
    parser = argparse.ArgumentParser(
        description="ACP Stdio Bridge — connects ACP agents to VoidTether Hub",
    )
    parser.add_argument("--tether-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--secret", default=None)
    parser.add_argument("--hub", default="http://100.84.202.9:8901")
    parser.add_argument("--log-level", default="INFO")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    secret = args.secret or os.environ.get("VOIDTETHER_HMAC_SECRET", "voidtether-dev-insecure-secret")
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    
    bridge = ACPStdioBridge(
        tether_id=args.tether_id,
        name=args.name,
        agent_command=args.command,
        tasks=tasks,
        secret=secret,
        hub_url=args.hub,
    )
    
    def signal_handler(sig, frame):
        bridge.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    asyncio.run(bridge.run())


if __name__ == "__main__":
    main()
