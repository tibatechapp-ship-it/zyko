"""ZykoMCPServer deep tests: in-memory stdio round-trips + tool texts."""

from __future__ import annotations

import io
import json

from zyko.mcp.server import ZykoMCPServer
from zyko.version import PROTOCOL_VERSION


def _serve(server: ZykoMCPServer, incoming: list[dict]) -> list[dict]:
    """Run the serve loop against in-memory buffers; return decoded responses."""
    stdin_bytes = "".join(json.dumps(m) + "\n" for m in incoming).encode()
    stdin = io.BytesIO(stdin_bytes)
    stdout = io.BytesIO()

    import asyncio

    asyncio.run(server.serve(stdin=stdin, stdout=stdout))
    out: list[dict] = []
    for line in stdout.getvalue().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def test_initialize_handshake():
    server = ZykoMCPServer(router=object())
    responses = _serve(
        server,
        [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSION}}],
    )
    assert len(responses) == 1
    result = responses[0]["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "zyko"


def test_initialize_downgrades_unknown_protocol():
    server = ZykoMCPServer(router=object())
    responses = _serve(
        server,
        [{"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}],
    )
    assert responses[0]["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_ping_and_tools_list():
    server = ZykoMCPServer(router=object())
    responses = _serve(
        server,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
    )
    assert responses[0]["result"] == {}
    names = [t["name"] for t in responses[1]["result"]["tools"]]
    assert names == ["zyko_models", "zyko_route", "zyko_chat"]


def test_notifications_get_no_response():
    server = ZykoMCPServer(router=object())
    responses = _serve(
        server,
        [{"jsonrpc": "2.0", "method": "notifications/initialized"}],
    )
    assert responses == []


def test_unknown_method_returns_error():
    server = ZykoMCPServer(router=object())
    responses = _serve(
        server,
        [{"jsonrpc": "2.0", "id": 3, "method": "resources/list"}],
    )
    body = responses[0]
    assert body["error"]["code"] == -32601
    assert "resources/list" in body["error"]["message"]


def test_zyko_models_text_uses_router(monkeypatch):
    from tests.fakes import FakeProvider

    router = type("R", (), {"providers": {"fake": FakeProvider()}})()
    server = ZykoMCPServer(router=router)
    server._router_built = True
    text = server._models_text()
    assert "fake/fake-small" in text
    assert "fake/fake-large" in text
    assert "$0.5/$1.5 per Mtok" in text  # list prices shown for routing


def test_zyko_route_text_with_prompt():
    from zyko import kernel

    server = ZykoMCPServer(router=object())
    server._router_built = True

    class FakeRouter:
        strategy = "balanced"

        def explain(self, *, est_input_tokens=800, est_output_tokens=400):
            assert est_input_tokens >= kernel.estimate_tokens("route me now")
            return {
                "strategy": "balanced",
                "ranking": [
                    {"candidate": "fake/fake-small", "total": 0.9, "quality": 0.8,
                     "cost_score": 1.0, "latency_score": 0.5},
                ],
            }

    server._ensure_router = lambda: FakeRouter()  # type: ignore[assignment]
    text = __import__("asyncio").run(server._route_text("route me now"))
    assert "strategy: balanced" in text
    assert "fake/fake-small" in text


def test_zyko_chat_text_includes_receipt_footer():
    from types import SimpleNamespace

    outcome = SimpleNamespace(
        response=SimpleNamespace(text="the answer"),
        receipt={"chosen": "fake/fake-small", "strategy": "balanced", "attempts": [{"candidate": "fake/fake-small"}]},
    )

    class FakeRouter:
        async def aroute(self, request):
            return outcome

    server = ZykoMCPServer(router=FakeRouter())
    server._router_built = True
    text = __import__("asyncio").run(server._chat_text("hello", None))
    assert text.startswith("the answer")
    assert "routed via fake/fake-small" in text


def test_zyko_chat_empty_prompt_is_tool_error():
    server = ZykoMCPServer(router=object())
    server._router_built = True
    responses = _serve(
        server,
        [{"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "zyko_chat", "arguments": {"prompt": "   "}}}],
    )
    assert responses[0]["result"]["isError"] is True
    assert "non-empty" in responses[0]["result"]["content"][0]["text"]


def test_unknown_tool_call_is_error():
    server = ZykoMCPServer(router=object())
    responses = _serve(
        server,
        [{"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "nope", "arguments": {}}}],
    )
    assert responses[0]["result"]["isError"] is True
    assert "unknown tool" in responses[0]["result"]["content"][0]["text"]


def test_malformed_frame_gets_parse_error_and_server_survives():
    """A bad line must not kill the host: JSON-RPC spec says reply -32700, continue."""
    stdin = io.BytesIO(
        b"not-json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
        + b"\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}).encode()
        + b"\n"
    )
    stdout = io.BytesIO()
    import asyncio

    asyncio.run(ZykoMCPServer(router=object()).serve(stdin=stdin, stdout=stdout))
    lines = [x for x in stdout.getvalue().splitlines() if x.strip()]
    assert len(lines) == 3  # parse error + two pings
    first, second, third = (json.loads(x) for x in lines)
    assert first["error"]["code"] == -32700 and first["id"] is None
    assert second["result"] == {}
    assert third["result"] == {}
