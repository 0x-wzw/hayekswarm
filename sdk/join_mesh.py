#!/usr/bin/env python3
"""Join this VM to the VoidTether mesh as a persistent agent.

Auto-reconnects on WebSocket drops. Listens for tasks from 
the orchestrator and other mesh agents.
"""

from __future__ import annotations
import asyncio
import json
import os
import signal
import sys
import logging
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client import VoidTetherClient

logger = logging.getLogger("mesh-agent")

HUB_URL = os.environ.get("VOIDTETHER_HUB_URL", "http://100.84.202.9:8901")
SECRET = os.environ.get("VOIDTETHER_HMAC_SECRET", "voidtether-dev-insecure-secret")
TETHER_ID = os.environ.get("VOIDTETHER_TETHER_ID", "hermes-vm")
AGENT_NAME = os.environ.get("VOIDTETHER_AGENT_NAME", "Hermes VM (Agent)")
TASKS = [
    "code", "review", "debug", "refactor", "test",
    "document", "explain", "research", "summarize",
    "shell_command", "system_admin", "file_ops",
    "qa", "planning", "general", "swarm_task",
]

_agent_tasks: set[str] = set()


async def process_message(content: str, sender: str) -> str:
    """Process incoming messages and dispatch to appropriate handler."""
    content_lower = content.strip().lower()

    if content_lower in ("ping", "pong"):
        return f"🏓 **Pong** from {AGENT_NAME} (v0.4.0) — mesh alive ✅"

    if content_lower in ("hello", "hi", "hey"):
        return f"👋 Hello **{sender}**! I'm {AGENT_NAME} on the VoidTether mesh."

    if content_lower == "status":
        import platform
        return (
            f"📊 **{AGENT_NAME} Status**\n"
            f"- Host: `{platform.node()}`\n"
            f"- Platform: `{platform.system()} {platform.release()}`\n"
            f"- Tasks: `{len(TASKS)}` registered\n"
            f"- Protocol: Hermes\n"
            f"- Local clone: voidtether @ `{os.popen('cd ~/voidtether && git rev-parse --short HEAD').read().strip()}`\n"
        )

    if content_lower in ("help", "commands", "?"):
        return (
            f"🆘 **Commands:**\n"
            f"- `ping` — health check\n"
            f"- `status` — VM & git info\n"
            f"- `agents` — list mesh agents\n"
            f"- `sessions` — list mesh sessions\n"
            f"- `push` — trigger me to push commits upstream\n"
            f"- `deploy` — ask orchestrator to deploy updates\n"
            f"- `run <cmd>` — execute shell command\n"
            f"- any other message — ack + route to orchestrator\n"
        )

    if content_lower == "agents":
        try:
            import httpx
            async with httpx.AsyncClient() as hc:
                resp = await hc.get(f"{HUB_URL}/api/agents")
                agents = resp.json()
            lines = [f"🔍 **Mesh Agents ({len(agents)}):**"]
            for a in agents:
                tasks = a.get("capabilities", {}).get("tasks", [])
                lines.append(f"- `{a.get('tether_id','?')}` — {a.get('name','?')}  [{', '.join(tasks[:3])}]")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error listing agents: {e}"

    if content_lower == "sessions":
        try:
            import httpx
            async with httpx.AsyncClient() as hc:
                resp = await hc.get(f"{HUB_URL}/api/sessions")
                sessions = resp.json()
            lines = [f"📋 **Sessions ({len(sessions)}):**"]
            for s in sessions:
                lines.append(f"- `{s.get('session_id','?')[:12]}..` — {s.get('title','?')}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error listing sessions: {e}"

    if content_lower == "push":
        return await _do_push()

    if content_lower == "deploy":
        return (
            f"📦 **Deploy request received.**\n"
            f"The orchestrator-admin agent can pull the latest from:\n"
            f"`https://github.com/0x-wzw/voidtether.git` (branch: main)\n"
            f"Latest commit: `{os.popen('cd ~/voidtether && git rev-parse --short HEAD').read().strip()}`\n"
            f"Message: `{os.popen('cd ~/voidtether && git log -1 --pretty=%s').read().strip()}`\n\n"
            f"Ask orchestrator-admin to run the deployment workflow."
        )

    if content_lower.startswith("run "):
        cmd = content[4:].strip()
        try:
            import subprocess
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            out = result.stdout[-800:] or "(no stdout)"
            err = result.stderr[-400:] or ""
            resp = f"⚡ **Shell: `{cmd}`**\nExit code: {result.returncode}\n```\n{out}\n```"
            if err:
                resp += f"\nStderr:\n```\n{err}\n```"
            return resp
        except subprocess.TimeoutExpired:
            return f"⏱️ Command `{cmd}` timed out after 30s"
        except Exception as e:
            return f"❌ Command failed: {e}"

    return (
        f"✅ **Message received** from `{sender}`\n"
        f"> {content[:200]}\n\n"
        f"Acknowledged. Forwarding to orchestrator for task routing."
    )


async def _do_push() -> str:
    """Push local commits upstream."""
    import subprocess
    try:
        r1 = subprocess.run(
            "cd ~/voidtether && git add -A && git commit --allow-empty -m 'chore: mesh agent sync $(date -u +%Y-%m-%dT%H:%M:%SZ)'",
            shell=True, capture_output=True, text=True, timeout=15
        )
        r2 = subprocess.run(
            "cd ~/voidtether && git pull --rebase origin main && git push origin main",
            shell=True, capture_output=True, text=True, timeout=30
        )
        out = (r1.stderr + "\n" + r2.stdout + r2.stderr).strip()
        return f"📤 **Push result:**\n```\n{out[-800:]}\n```"
    except Exception as e:
        return f"❌ Push failed: {e}"


async def main():
    retries = 0
    while True:
        try:
            logger.info(f"Connecting to VoidTether hub at {HUB_URL}...")
            client = VoidTetherClient(
                hub_url=HUB_URL,
                secret=SECRET,
                tether_id=TETHER_ID,
                name=AGENT_NAME,
                protocol="hermes",
                capabilities={"tasks": TASKS},
            )

            async with client:
                reg = await client.register()
                if "error" in reg:
                    logger.error(f"Registration failed: {reg}")
                    await asyncio.sleep(10)
                    continue

                logger.info(f"✅ Registered as '{TETHER_ID}' ({AGENT_NAME})")

                session = await client.create_session(
                    title=f"Mesh Agent — {AGENT_NAME}",
                    participants=[TETHER_ID],
                    turn_policy="round_robin",
                )
                session_id = session.get("session_id", "")
                logger.info(f"📡 Session: {session_id}")

                announce = (
                    f"🤖 **{AGENT_NAME}** connected to mesh at `{datetime.now().isoformat()}`\n"
                    f"Ready for: `{', '.join(TASKS)}`\n"
                    f"Repo: `{os.popen('cd ~/voidtether && git rev-parse --short HEAD').read().strip()}`"
                )
                await client.send_message(session_id, announce, role="agent")
                logger.info("📤 Announcement sent")

                # Reconnect to orchestrator session if it exists
                try:
                    import httpx
                    async with httpx.AsyncClient() as hc:
                        resp = await hc.get(f"{HUB_URL}/api/sessions")
                        sessions = resp.json()
                    for s in sessions:
                        parts = s.get("participants", [])
                        title = s.get("title", "")
                        if ("orchestrator" in title.lower() or "K2" in title) and "hermes-vm" in parts:
                            logger.info(f"🔗 Rejoining session: {title}")
                            await client.send_message(
                                s["session_id"],
                                f"🔄 **{AGENT_NAME}** reconnected. Ready for tasks.",
                                role="agent",
                            )
                except Exception:
                    pass

                logger.info("🔗 Connecting WebSocket...")

                async def ws_handler(data: dict) -> str | None:
                    event_type = data.get("type") or data.get("event_type", "")
                    sender = data.get("sender", "")
                    content = data.get("content", "")
                    role = data.get("role", "")
                    message_id = data.get("message_id", "")

                    if sender == TETHER_ID:
                        return None

                    if event_type == "message" and role == "user" and content:
                        logger.info(f"📨 From [{sender}]: {content[:120]}")
                        task_key = f"{message_id or content[:40]}"
                        if task_key in _agent_tasks:
                            return None
                        _agent_tasks.add(task_key)
                        if len(_agent_tasks) > 200:
                            _agent_tasks.clear()

                        response = await process_message(content, sender)
                        logger.info(f"📤 Response: {response[:120]}...")
                        return response
                    return None

                await client.connect_websocket(session_id, handler=ws_handler)

        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            retries += 1
            delay = min(10 * retries, 60)
            logger.warning(f"Connection lost ({e}). Reconnecting in {delay}s... (attempt {retries})")
            await asyncio.sleep(delay)
        except KeyboardInterrupt:
            logger.info("Shutting down.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(30)


if __name__ == "__main__":
    import httpx
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception(f"Fatal: {e}")
        sys.exit(1)
