"""JSON-RPC 2.0 framing for the Model Context Protocol (stdio transport).

MCP frames are newline-delimited JSON objects. This module is transport-only:
encoding, decoding, request/response ids and protocol error codes.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from zyko.exceptions import MCPError

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def encode(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(raw: bytes | str) -> dict[str, Any]:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MCPError(f"invalid JSON-RPC frame: {exc}") from exc
    if not isinstance(message, dict):
        raise MCPError("JSON-RPC frame must be an object")
    return message


def request(msg_id: int | str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def result(msg_id: int | str, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": value}


def error(msg_id: int | str, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


async def read_messages(stream: AsyncIterator[bytes]) -> AsyncIterator[dict[str, Any]]:
    """Yield decoded JSON-RPC messages from an async byte stream."""
    buf = b""
    async for chunk in stream:
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if line:
                yield decode(line)
    line = buf.strip()
    if line:
        yield decode(line)
