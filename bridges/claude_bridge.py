#!/usr/bin/env python3
"""VoidTether Bridge for Claude Code CLI.

Same-machine integration. Claude Code CLI runs this script;
it registers with the Hub, listens for mesh events, and
pipes messages to/from stdout for Claude Code to process.

Usage:
    python3 claude_bridge.py                    # Auto-register + listen
    python3 claude_bridge.py --send <session_id> <message>  # Send a message
    python3 claude_bridge.py --create <title>    # Create a session
    python3 claude_bridge.py --list              # List sessions
"""

import asyncio
import sys
import os
import json

# SDK is on the same machine
sys.path.insert(0, os.path.expanduser("~/voidtether-sdk"))
sys.path.insert(0, os.path.expanduser("~/voidtether"))

from voidtether_sdk import VoidTetherClient

HUB_URL = "http://localhost:8901"
STATE_FILE = os.path.expanduser("~/.voidtether_bridge_state.json")
CLIENT = None


def load_state():
    """Load persisted tether_id so we reuse the same agent identity."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    """Persist tether_id for future runs."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


async def get_client():
    global CLIENT
    if CLIENT is None:
        state = load_state()
        tether_id = state.get("tether_id")
        CLIENT = VoidTetherClient(
            hub_url=HUB_URL,
            tether_id=tether_id,  # Reuse persisted ID if available
            name="Claude Code",
            capabilities={"tasks": ["code", "review", "analyze", "write"]},
        )
        CLIENT._persisted_tether_id = tether_id  # Track what we loaded
    return CLIENT


async def ensure_registered():
    """Ensure the client is registered AND reuses the persisted identity.

    This fixes the bug where --send created ephemeral identities.
    """
    client = await get_client()
    if not client._registered:
        # If we have a persisted tether_id, use it explicitly
        state = load_state()
        persisted_id = state.get("tether_id")
        if persisted_id:
            client.tether_id = persisted_id
        await client.register()
        save_state({"tether_id": client.tether_id})
    return client


async def cmd_register():
    """Register with the Hub and print tether_id. Persists for reuse."""
    client = await get_client()
    result = await client.quickstart()
    if "error" in result:
        print(f"ERROR: {result}", file=sys.stderr)
        sys.exit(1)
    save_state({"tether_id": client.tether_id})
    print(client.tether_id)


async def cmd_create(title):
    """Create a session with this agent as participant and print session_id."""
    client = await ensure_registered()
    session = await client.create_session(title, participants=[client.tether_id])
    print(session["session_id"])


async def cmd_list():
    """List all sessions."""
    client = await get_client()
    sessions = await client.list_sessions()
    for s in sessions:
        print(f"{s['session_id']}  {s['title']}  ({len(s['participants'])} agents, {len(s['messages'])} msgs)")


async def cmd_send(session_id, message):
    """Send a message to a session."""
    client = await ensure_registered()
    result = await client.send_message(session_id, message, role="agent")
    if "message_id" in result:
        print(f"OK: {result['message_id']}")
    else:
        print(f"ERROR: {result}", file=sys.stderr)
        sys.exit(1)


async def cmd_listen(session_id, timeout=0):
    """Listen to a session stream. Prints JSON events to stdout.

    Each event is printed as a single JSON line.
    Claude Code CLI can parse these and respond.

    Args:
        session_id: The session to listen to.
        timeout: Max seconds to listen (0 = forever).
    """
    client = await ensure_registered()

    try:
        async for event in client.stream(session_id):
            # Only print real events, not pings
            if event.get("_event_type") == "ping":
                continue
            import json
            print(json.dumps(event), flush=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"STREAM_ERROR: {e}", file=sys.stderr)


async def cmd_interactive(session_id):
    """Interactive mode: listens for events and accepts input from stdin.

    Claude Code CLI pipes messages in via stdin (one per line),
    and receives events via stdout (one JSON per line).
    """
    client = await ensure_registered()

    async def stdin_reader():
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if line:
                await client.send_message(session_id, line, role="agent")

    async def stream_reader():
        import json
        async for event in client.stream(session_id):
            if event.get("_event_type") == "ping":
                continue
            print(json.dumps(event), flush=True)

    await asyncio.gather(stdin_reader(), stream_reader())


async def main():
    args = sys.argv[1:]

    if not args or args[0] == "--register":
        await cmd_register()
        await (await get_client()).disconnect()

    elif args[0] == "--create":
        title = args[1] if len(args) > 1 else "Claude Code Session"
        await cmd_create(title)
        await (await get_client()).disconnect()

    elif args[0] == "--list":
        await cmd_list()
        await (await get_client()).disconnect()

    elif args[0] == "--send":
        if len(args) < 3:
            print("Usage: claude_bridge.py --send <session_id> <message>", file=sys.stderr)
            sys.exit(1)
        await cmd_send(args[1], " ".join(args[2:]))
        await (await get_client()).disconnect()

    elif args[0] == "--listen":
        if len(args) < 2:
            print("Usage: claude_bridge.py --listen <session_id>", file=sys.stderr)
            sys.exit(1)
        await cmd_listen(args[1])

    elif args[0] == "--interactive":
        if len(args) < 2:
            print("Usage: claude_bridge.py --interactive <session_id>", file=sys.stderr)
            sys.exit(1)
        await cmd_interactive(args[1])

    elif args[0] == "--health":
        client = await get_client()
        h = await client.health()
        r = await client.ready()
        import json
        print(json.dumps({"health": h, "ready": r}, indent=2))
        await client.disconnect()

    elif args[0] == "--discover":
        task = args[1] if len(args) > 1 else ""
        client = await get_client()
        agents = await client.discover(task)
        import json
        print(json.dumps(agents, indent=2))
        await client.disconnect()

    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())