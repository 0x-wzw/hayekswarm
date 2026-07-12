#!/usr/bin/env python3
"""VoidTether CLI — `vt` command-line interface."""

import argparse
import asyncio
import json
import sys

from voidtether.core import TetherManifest, Protocol
from voidtether.mesh import Mesh


def cmd_serve(args):
    """Start a VoidTether mesh server with web UI."""
    try:
        import uvicorn
    except ImportError:
        print("⚫ Error: uvicorn not installed. Install with: pip install voidtether[server]")
        sys.exit(1)
    
    from voidtether.server import create_app
    
    mesh = Mesh()
    app = create_app(mesh)
    
    print(f"⚫ VoidTether mesh server starting on port {args.port}...")
    print(f"   The cord that binds across the void.")
    print(f"   API: http://localhost:{args.port}")
    print(f"   Docs: http://localhost:{args.port}/docs")
    print(f"   WebSocket: ws://localhost:{args.port}/ws/{{session_id}}")
    print(f"   SSE: http://localhost:{args.port}/api/sessions/{{session_id}}/stream")
    
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_register(args):
    """Register an agent with the mesh."""
    protocol = Protocol(args.protocol)
    manifest = TetherManifest(
        tether_id=f"vt-{args.protocol}-{args.name or 'agent'}",
        name=args.name or f"{args.protocol} agent",
        origin_protocol=protocol,
        capabilities={"tasks": args.tasks.split(",") if args.tasks else []},
        protocols=[{"protocol": args.protocol, "endpoint_url": args.url}],
    )
    print(f"⚫ Registered: {manifest.tether_id}")
    print(f"   Protocol: {manifest.origin_protocol.value}")
    print(f"   Capabilities: {manifest.tasks}")
    print(manifest.to_json())


def cmd_list(args):
    """List all tethered agents."""
    print("⚫ No agents registered (mesh not started)")


def cmd_delegate(args):
    """Delegate a task across the mesh."""
    print(f"⚫ Delegating task '{args.to}'...")
    print("   [placeholder — implement in v0.2.0]")


def main():
    parser = argparse.ArgumentParser(
        prog="vt",
        description="VoidTether CLI — the cord that binds across the void",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # serve
    serve_parser = subparsers.add_parser("serve", help="Start mesh server with web layer")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_parser.add_argument("--port", type=int, default=8901, help="Port number")
    
    # register
    reg_parser = subparsers.add_parser("register", help="Register an agent")
    reg_parser.add_argument("--protocol", required=True, choices=[p.value for p in Protocol])
    reg_parser.add_argument("--name", default=None)
    reg_parser.add_argument("--url", default="http://localhost:8080")
    reg_parser.add_argument("--tasks", default="", help="Comma-separated task list")
    
    # list
    subparsers.add_parser("list", help="List tethered agents")
    
    # delegate
    del_parser = subparsers.add_parser("delegate", help="Delegate a task")
    del_parser.add_argument("--to", required=True, help="Task type to delegate")
    del_parser.add_argument("--protocol", default="any")
    del_parser.add_argument("--input", default="{}")
    
    args = parser.parse_args()
    
    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "register":
        cmd_register(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "delegate":
        cmd_delegate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()