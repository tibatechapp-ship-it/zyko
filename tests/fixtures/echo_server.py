"""A minimal MCP server used as a test fixture (newline-delimited JSON-RPC)."""

import json
import sys

PROTO = "2024-11-05"

for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        continue
    method = msg.get("method")
    msg_id = msg.get("id")
    if msg_id is None:
        continue  # notification
    if method == "initialize":
        result = {
            "protocolVersion": PROTO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "echo", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Return the input text prefixed with 'echo:'",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }
            ]
        }
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        if name != "echo":
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": f"unknown tool: {name}"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        args = params.get("arguments") or {}
        result = {
            "content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}],
            "isError": False,
        }
    elif method == "ping":
        result = {}
    else:
        sys.stdout.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": "no such method"},
                }
            )
            + "\n"
        )
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()
