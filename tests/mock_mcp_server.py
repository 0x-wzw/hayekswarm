#!/usr/bin/env python3
"""Mock MCP server for testing - JSON-RPC over stdio."""

import json
import sys
import traceback


def send_response(request_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": request_id}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle_request(request):
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        send_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mock-mcp-server", "version": "1.0.0"},
        })
    elif method == "tools/list":
        send_response(req_id, {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo back the input",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                        },
                        "required": ["message"],
                    },
                },
                {
                    "name": "add",
                    "description": "Add two numbers",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "number"},
                            "b": {"type": "number"},
                        },
                        "required": ["a", "b"],
                    },
                },
                {
                    "name": "error_tool",
                    "description": "Always returns an error",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            ]
        })
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        if name == "echo":
            send_response(req_id, {
                "content": [{"type": "text", "text": arguments.get("message", "")}],
            })
        elif name == "add":
            result = arguments.get("a", 0) + arguments.get("b", 0)
            send_response(req_id, {
                "content": [{"type": "text", "text": str(result)}],
            })
        elif name == "error_tool":
            send_response(req_id, None, {
                "code": -1,
                "message": "Tool execution failed intentionally",
            })
        else:
            send_response(req_id, None, {
                "code": -32602,
                "message": "Unknown tool: {}".format(name),
            })
    elif method == "shutdown":
        sys.exit(0)
    else:
        send_response(req_id, None, {
            "code": -32601,
            "message": "Method not found: {}".format(method),
        })


def main():
    if "--slow" in sys.argv:
        import time
        time.sleep(2)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            handle_request(request)
        except json.JSONDecodeError:
            continue
        except SystemExit:
            break
        except Exception:
            send_response(None, None, {
                "code": -32603,
                "message": traceback.format_exc(),
            })


if __name__ == "__main__":
    main()
