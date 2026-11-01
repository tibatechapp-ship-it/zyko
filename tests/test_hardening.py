"""Evaluation-round hardening tests: cover the paths earlier suites missed.

Targets the exact gaps found by the coverage audit — calculator edges,
workspace escapes, MCP protocol helpers, the optional Rust-kernel swap,
provider retry/timeout/error mapping, and agent tool-loop failure modes.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path

import httpx
import pytest

from tests.fakes import FakeProvider
from zyko.agents.agent import Agent
from zyko.agents.tools_builtin import BuiltinTool, builtin_tools
from zyko.core.messages import Message, ToolCall
from zyko.core.response import ChatRequest, ChatResponse
from zyko.core.tools import (
    generic_from_openai,
    to_anthropic_tools,
    to_google_tools,
    to_openai_tools,
)
from zyko.exceptions import AuthError, MCPError, ProviderError, ToolError, ZykoTimeoutError
from zyko.mcp.protocol import decode, encode, error, notification, read_messages
from zyko.providers.base import BaseProvider, _retry_after_seconds
from zyko.providers.openai_compat import OpenAICompatProvider
from zyko.router.engine import Router


def _req(**kw):
    return ChatRequest(messages=[Message.user("hi")], **kw)


# ------------------------------------------------------------- core/tools.py
def test_tools_inputschema_fallback_and_empty_description():
    """MCP-style ``inputSchema`` is honored; a missing description becomes ''."""
    tool = {"name": "t", "inputSchema": {"type": "object", "properties": {}}}
    openai = to_openai_tools([tool])[0]
    assert openai["function"]["parameters"] == {"type": "object", "properties": {}}
    assert openai["function"]["description"] == ""
    assert to_anthropic_tools([tool])[0]["input_schema"] == {"type": "object", "properties": {}}
    assert to_google_tools([tool])[0]["functionDeclarations"][0]["name"] == "t"
    # garbage parameters fall back to an empty object schema
    bare = to_openai_tools([{"name": "b", "parameters": "nope"}])[0]
    assert bare["function"]["parameters"] == {"type": "object", "properties": {}}


def test_generic_from_openai_variants():
    """Accepts wrapped {function:...}, bare dicts, and None."""
    wrapped = [{"function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}]
    assert generic_from_openai(wrapped)[0]["name"] == "f"
    bare = generic_from_openai([{"name": "g"}])[0]
    assert bare["name"] == "g" and bare["description"] == ""
    assert bare["parameters"] == {"type": "object", "properties": {}}
    assert generic_from_openai(None) == []


# --------------------------------------------------------- mcp/protocol.py
def test_protocol_error_and_notification():
    err = error(7, -32600, "bad request")
    assert err == {"jsonrpc": "2.0", "id": 7, "error": {"code": -32600, "message": "bad request"}}
    assert notification("ping") == {"jsonrpc": "2.0", "method": "ping"}
    assert notification("ping", {"a": 1}) == {
        "jsonrpc": "2.0",
        "method": "ping",
        "params": {"a": 1},
    }


@pytest.mark.asyncio
async def test_read_messages_chunks_and_flush():
    """Frames split across chunks are reassembled; the tail flushes."""

    async def stream():
        yield b'{"a": 1}\n{"b":'
        yield b' 2}\n{"c": 3}'  # final frame has no trailing newline

    got = [msg async for msg in read_messages(stream())]
    assert got == [{"a": 1}, {"b": 2}, {"c": 3}]
    # round-trip helpers agree with decode
    assert decode(encode({"x": 1})) == {"x": 1}


# ------------------------------------------------------------- kernel swap
def test_kernel_rust_backend_swap(monkeypatch):
    """A healthy zyko_kernel import switches the backend to Rust (and back)."""
    import zyko.kernel as kernel

    fake = types.ModuleType("zyko_kernel")
    fake.estimate_tokens = lambda text: 99
    fake.estimate_messages_tokens = lambda messages: 7
    fake.cosine_similarity = lambda a, b: 1.0
    fake.top_k = lambda values, k: list(values)[:k]
    fake.moving_average = lambda values, window: list(values)
    saved = sys.modules.get("zyko_kernel")
    sys.modules["zyko_kernel"] = fake
    try:
        importlib.reload(kernel)
        assert kernel.backend() == "rust"
        assert kernel.estimate_tokens("hello") == 99
        assert kernel.messages_tokens([]) == 7  # rust fast-path for message lists
    finally:
        if saved is None:
            sys.modules.pop("zyko_kernel", None)
        else:
            sys.modules["zyko_kernel"] = saved
        importlib.reload(kernel)  # restore the pure-python backend
    assert kernel.backend() == "python"


# -------------------------------------------------- tools_builtin edges
def test_calculator_power_cap_unary_and_constants():
    calc = builtin_tools()["calculator"]
    assert (asyncio.run(calc.handler(expression="2**10"))) == "1024"
    with pytest.raises(ToolError, match="exponent too large"):
        asyncio.run(calc.handler(expression="2**9999"))
    assert asyncio.run(calc.handler(expression="-5")) == "-5"
    assert asyncio.run(calc.handler(expression="+5")) == "5"
    assert asyncio.run(calc.handler(expression="pi")) == "3.141592653589793"
    assert asyncio.run(calc.handler(expression="e * 1")) == "2.718281828459045"
    assert asyncio.run(calc.handler(expression="4/2")) == "2"  # 2.0 → int coercion


def test_calculator_rejects_bool_syntax_and_zero_div():
    calc = builtin_tools()["calculator"]
    with pytest.raises(ToolError, match="unsupported expression element"):
        asyncio.run(calc.handler(expression="True"))
    with pytest.raises(ToolError, match="calculator:"):
        asyncio.run(calc.handler(expression="hello world"))  # unknown names
    with pytest.raises(ToolError, match="division by zero"):
        asyncio.run(calc.handler(expression="1/0"))


def test_file_tools_workspace_escape_and_listing(tmp_path):
    tools = builtin_tools(str(tmp_path))
    # ../ escape is blocked on read and write
    with pytest.raises(Exception, match="escapes the agent workspace"):
        asyncio.run(tools["read_file"].handler(path="../secret.txt"))
    with pytest.raises(Exception, match="escapes the agent workspace"):
        asyncio.run(tools["write_file"].handler(path="../evil.txt", content="x"))
    # read a missing file
    with pytest.raises(Exception, match="no such file"):
        asyncio.run(tools["read_file"].handler(path="ghost.txt"))
    # write into a fresh subdir, list it, read it back
    out = asyncio.run(tools["write_file"].handler(path="sub/a.txt", content="hello"))
    assert "wrote 5 chars" in out
    listing = asyncio.run(tools["list_dir"].handler(path="sub"))
    assert "a.txt" in listing  # paths are relative to the workspace root
    assert asyncio.run(tools["read_file"].handler(path="sub/a.txt")) == "hello"
    # list_dir on a file fails
    with pytest.raises(Exception, match="not a directory"):
        asyncio.run(tools["list_dir"].handler(path="sub/a.txt"))


def test_http_get_rejects_non_http_schemes():
    tools = builtin_tools()
    with pytest.raises(Exception, match="only http"):
        asyncio.run(tools["http_get"].handler(url="ftp://example.com/file"))
    with pytest.raises(Exception, match="only http"):
        asyncio.run(tools["http_get"].handler(url="file:///etc/passwd"))


@pytest.mark.skipif(sys.platform == "win32", reason="sleep subprocess timing differs")
def test_shell_timeout_and_success(tmp_path):
    """Danger tool runs only via explicit allow; timeout maps to ToolError."""
    tools = builtin_tools(str(tmp_path))
    out = asyncio.run(tools["shell"].handler(command="echo zyko-shell-ok"))
    assert "exit=0" in out and "zyko-shell-ok" in out
    with pytest.raises(Exception, match="timed out"):
        asyncio.run(tools["shell"].handler(command="sleep 5", timeout=0.2))


# ------------------------------------------- provider base: error/retry map
def _dummy_provider(handler, **kw):
    return OpenAICompatProvider(
        api_key="k", base_url="http://t", transport=httpx.MockTransport(handler), **kw
    )


def test_provider_maps_timeout_network_and_bad_json():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ZykoTimeoutError, match="timed out"):
        asyncio.run(_dummy_provider(timeout_handler, retries=0).acomplete(_req()))

    def net_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError, match="network error"):
        asyncio.run(_dummy_provider(net_handler, retries=0).acomplete(_req()))

    def bad_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="this is not json{")

    with pytest.raises(ProviderError, match="invalid JSON"):
        asyncio.run(_dummy_provider(bad_json_handler).acomplete(_req()))


def test_provider_status_map_auth_retryable_and_hint():
    def handler401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="nope")

    with pytest.raises(AuthError, match="HTTP 401"):
        asyncio.run(_dummy_provider(handler401).acomplete(_req()))

    def handler400(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad payload")

    with pytest.raises(ProviderError, match="HTTP 400"):
        asyncio.run(_dummy_provider(handler400).acomplete(_req()))
    try:
        asyncio.run(_dummy_provider(handler400).acomplete(_req()))
    except ProviderError as exc:
        assert exc.hint and "payload" in exc.hint
        assert exc.retryable is False

    def handler500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ProviderError, match="HTTP 500"):
        asyncio.run(_dummy_provider(handler500, retries=0).acomplete(_req()))


def test_provider_retry_after_header_is_honored():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="rate limited", headers={"Retry-After": "0.05"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = _dummy_provider(handler, retries=2)
    resp = asyncio.run(provider.acomplete(_req()))
    assert resp.content == "ok" and calls["n"] == 2


def test_retry_after_seconds_delay_and_httpdate():
    resp = httpx.Response(429, headers={"Retry-After": "3"})
    assert _retry_after_seconds(resp) == 3.0
    resp_date = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"})
    assert _retry_after_seconds(resp_date) > 0
    assert _retry_after_seconds(httpx.Response(429, headers={"Retry-After": "garbage"})) is None
    assert _retry_after_seconds(httpx.Response(429)) is None


@pytest.mark.asyncio
async def test_provider_streaming_edges_and_collect():
    """SSE with a garbage line, flush at EOF, and astream_collect materialise."""
    body = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        "data: garbage-not-json\n\n"
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    provider = _dummy_provider(handler)
    chunks = [evt async for evt in provider.astream(_req())]
    text = "".join(c.data.get("text", "") for c in chunks if c.type == "text")
    assert "Hel" in text and "lo" in text

    collected = await provider.astream_collect(_req())
    assert collected.content == "Hello"


def test_provider_sync_stream_and_aclose_and_find_model():
    body = 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    provider = _dummy_provider(handler)
    events = list(provider.stream(_req()))
    assert events, "sync stream must yield events"
    asyncio.run(provider.aclose())
    assert provider._clients == {}

    assert provider.find_model("no-such-model") is None  # catalog may be empty


def test_resolve_model_rules_on_minimal_subclass():
    class _Minimal(BaseProvider):
        name = "minimal"
        DEFAULT_MODEL = None

        def _build(self, request, *, stream):
            return "http://t/", {}, {}

        def _parse_response(self, data, request):
            return ChatResponse(id="1", provider=self.name, model="m")

    p = _Minimal()
    assert p._parse_stream_chunk({}, {}) is None  # adapters without streaming
    assert p._resolve_model(_req(model="minimal/whatever")) == "whatever"
    assert p._resolve_model(_req(model="bare-model")) == "bare-model"
    with pytest.raises(ProviderError, match="no model specified"):
        p._resolve_model(_req(model=None))


# ------------------------------------------------- agent tool-loop failures
class _FakeMCP:
    """Minimal MCP client double for agent-loop tests."""

    def __init__(self, name="srv", *, fail_list=False, sleep=None, raise_zyko=False):
        self.name = name
        self.fail_list = fail_list
        self.sleep = sleep
        self.raise_zyko = raise_zyko

    async def start(self):
        pass

    async def list_tools(self):
        if self.fail_list:
            raise MCPError("server down")
        return [{"name": "t", "description": "d", "inputSchema": {"type": "object"}}]

    def as_tools(self, tools):
        return list(tools)

    async def call_tool(self, name, args):
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raise_zyko:
            raise MCPError("mcp exploded")
        return "ok"


def _agent(monkeypatch, *clients, **kw):
    monkeypatch.setattr(
        "zyko.cli.commands.configured_providers", lambda *a, **k: {"fake": FakeProvider()}
    )
    router = Router({"fake": FakeProvider()})
    agent = Agent(router, name="t", mcp_clients=list(clients), **kw)
    return agent


def test_agent_unknown_tool_and_bad_args_and_crash(monkeypatch):
    agent = _agent(monkeypatch)
    out = asyncio.run(agent._execute(ToolCall(id="1", name="nope", arguments={})))
    assert out == "error: unknown tool 'nope'"
    # non-string expression → ast.parse raises TypeError → friendly mapping
    out = asyncio.run(
        agent._execute(ToolCall(id="2", name="calculator", arguments={"expression": 5}))
    )
    assert "bad arguments" in out

    # a tool that crashes must not kill the loop
    def boom(**_kw):
        raise ValueError("kaput")

    agent.builtin_tools["boom"] = BuiltinTool("boom", "crashes", {"type": "object"}, boom)
    out = asyncio.run(agent._execute(ToolCall(id="3", name="boom", arguments={})))
    assert out == "error: ValueError: kaput"


def test_agent_mcp_routing_paths(monkeypatch):
    agent = _agent(monkeypatch, _FakeMCP("srv"))
    out = asyncio.run(agent._execute(ToolCall(id="1", name="other__t", arguments={})))
    assert "no MCP server named 'other'" in out
    out = asyncio.run(agent._execute(ToolCall(id="2", name="srv__t", arguments={})))
    assert out == "ok"
    out = asyncio.run(
        agent._execute(
            ToolCall(id="3", name="srv__t", arguments={}),
        )
    )
    assert out == "ok"

    failing = _FakeMCP("bad", raise_zyko=True)
    agent2 = _agent(monkeypatch, failing)
    out = asyncio.run(agent2._execute(ToolCall(id="4", name="bad__t", arguments={})))
    assert "error: mcp exploded" in out


def test_agent_mcp_timeout(monkeypatch):
    monkeypatch.setattr("zyko.agents.agent.TOOL_TIMEOUT_S", 0.05)
    agent = _agent(monkeypatch, _FakeMCP("slow", sleep=0.5))
    out = asyncio.run(agent._execute(ToolCall(id="1", name="slow__t", arguments={})))
    assert "timed out after 0.05s" in out


def test_agent_tool_specs_survive_dead_mcp(monkeypatch):
    agent = _agent(monkeypatch, _FakeMCP("dead", fail_list=True))
    specs = asyncio.run(agent.tool_specs())
    names = {s["name"] for s in specs}
    assert "calculator" in names  # builtins survive the dead MCP server


# ------------------------------------------------------- CI workflow sanity
def test_ci_workflow_triggers_on_main():
    """Guard: CI push triggers must stay on ['main'].

    Regression guard for a false alarm during the evaluation round — an
    ANSI-sanitizing log pipeline rendered ``[main]`` as ``ain]``, which
    looked like corrupted YAML. Byte-level inspection proved the file was
    always correct; this test pins the trigger so real corruption (or an
    accidental trigger removal) fails fast.
    """
    import yaml

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    push_branches = doc[True]["push"]["branches"]  # bare `on:` parses as boolean True
    assert push_branches == ["main"]
