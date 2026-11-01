"""MCP client + server over real subprocesses (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from zyko.exceptions import MCPError
from zyko.mcp.client import MCPClient
from zyko.mcp.protocol import decode, encode, request
from zyko.mcp.server import ZykoMCPServer

FIXTURE = Path(__file__).parent / "fixtures" / "echo_server.py"


def _client() -> MCPClient:
    return MCPClient("echo", [sys.executable, str(FIXTURE)], request_timeout=10.0)


async def test_full_lifecycle():
    client = _client()
    await client.start()
    try:
        assert client.server_info["name"] == "echo"
        tools = await client.list_tools()
        assert [t["name"] for t in tools] == ["echo"]
        assert tools[0]["parameters"]["properties"]["text"]["type"] == "string"
        out = await client.call_tool("echo", {"text": "hello zyko"})
        assert out == "echo: hello zyko"
        namespaced = client.as_tools(tools)
        assert namespaced[0]["name"] == "echo__echo"
        assert MCPClient.split_qualified("echo__echo") == ("echo", "echo")
    finally:
        await client.aclose()


async def test_unknown_tool_raises():
    client = _client()
    await client.start()
    try:
        with pytest.raises(MCPError):
            await client.call_tool("missing", {})
    finally:
        await client.aclose()


async def test_start_with_empty_command_raises():
    with pytest.raises(MCPError):
        MCPClient("empty", [])


async def test_missing_executable_raises():
    client = MCPClient("nope", ["/definitely/not/a/real/binary"])
    with pytest.raises(MCPError):
        await client.start()


# ------------------------------------------------------------------- protocol
def test_protocol_roundtrip():
    raw = encode(request(1, "ping"))
    msg = decode(raw)
    assert msg["id"] == 1 and msg["method"] == "ping"


# -------------------------------------------------------------- server side
async def test_zyko_mcp_server_initialize_and_tools_list():
    server = ZykoMCPServer()
    reply = await server.handle(decode(encode(request(7, "initialize", {"protocolVersion": "2024-11-05", "clientInfo": {}}))))
    assert reply["result"]["serverInfo"]["name"] == "zyko"
    reply = await server.handle(decode(encode(request(8, "tools/list"))))
    names = [t["name"] for t in reply["result"]["tools"]]
    assert {"zyko_chat", "zyko_route", "zyko_models"} <= set(names)


async def test_zyko_mcp_server_models_tool():
    server = ZykoMCPServer()
    reply = await server.handle(decode(encode(request(9, "tools/call", {"name": "zyko_models", "arguments": {}}))))
    text = reply["result"]["content"][0]["text"]
    # Keyless env: _ensure_router falls back to the demo provider, and the
    # listing reflects what the router can actually route (policy-filtered),
    # not a static vendor catalog.
    assert "mock/mock-mini" in text


async def test_zyko_mcp_server_unknown_method():
    server = ZykoMCPServer()
    reply = await server.handle(decode(encode(request(10, "bogus/method"))))
    assert reply["error"]["code"] == -32601


async def test_zyko_mcp_server_notification_is_silent():
    server = ZykoMCPServer()
    assert await server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
