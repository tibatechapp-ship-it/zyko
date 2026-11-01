"""Evaluation round (v0.3.2): coverage-driven tests for the weakest modules.

Targets measured gaps from `pytest --cov`:
utils/loop, providers/mock, router/quality, config/settings, gateway/server,
mcp/client, platform/paths, providers/anthropic, providers/openai_compat,
providers registry, cli commands, benchmarks, core/events+response, cli/ui.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.fakes import FakeProvider
from zyko.benchmarks.routing_bench import GRADERS, _run_candidate, build_suite, suite_hash
from zyko.config.settings import Settings
from zyko.core.events import StreamEvent, accumulate_stream, sse_data_events
from zyko.core.messages import Message, ToolCall
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, Usage
from zyko.exceptions import (
    ConfigError,
    MCPError,
    ProviderError,
    ZykoError,
    ZykoTimeoutError,
)
from zyko.gateway.server import serve
from zyko.mcp.client import MCPClient
from zyko.router.engine import Router
from zyko.router.quality import QualityLedger

FIXTURE = Path(__file__).parent / "fixtures" / "echo_server.py"


# ------------------------------------------------------------------ package entry
def test_python_dash_m_version():
    out = subprocess.run(
        [sys.executable, "-m", "zyko", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert "zyko 0." in out.stdout


# ------------------------------------------------------------------- utils/loop
def test_run_sync_inside_running_loop_uses_helper_thread():
    """Calling run_sync from a live loop must not dead-lock (helper thread)."""

    async def inner() -> str:
        async def coro() -> str:
            await asyncio.sleep(0)
            return "ok"

        from zyko.utils.loop import run_sync

        return run_sync(coro())

    assert asyncio.run(inner()) == "ok"


def test_shared_loop_iterate_cancel_on_close():
    from zyko.utils.loop import SHARED_LOOP

    async def agen():
        yield 1
        yield 2
        yield 3

    it = SHARED_LOOP.iterate(agen())
    assert next(it) == 1
    it.close()  # GeneratorExit → cancels the pump task


def test_shared_loop_iterate_propagates_error():
    from zyko.utils.loop import SHARED_LOOP

    async def agen():
        yield "a"
        raise RuntimeError("boom inside stream")

    it = SHARED_LOOP.iterate(agen())
    assert next(it) == "a"
    with pytest.raises(RuntimeError, match="boom inside stream"):
        next(it)


def test_shared_loop_run_timeout():
    from zyko.utils.loop import SharedLoop

    async def slow():
        await asyncio.sleep(5)

    loop = SharedLoop()
    with pytest.raises(TimeoutError):
        loop.run(slow(), timeout=0.1)


# --------------------------------------------------------------- providers/mock
def _mock_request(**meta: Any) -> ChatRequest:
    return ChatRequest(messages=[Message.user("hi")], metadata=dict(meta))


async def test_mock_force_tool_dict_args():
    from zyko.providers.mock import MockProvider

    provider = MockProvider()
    resp = await provider.acomplete(_mock_request(force_tool="calculator", tool_args={"x": 1}))
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].name == "calculator"
    assert resp.tool_calls[0].arguments == {"x": 1}
    assert resp.content is None


async def test_mock_force_tool_json_string_args():
    from zyko.providers.mock import MockProvider

    provider = MockProvider()
    resp = await provider.acomplete(_mock_request(force_tool="calc", tool_args='{"n": 3}'))
    assert resp.tool_calls[0].arguments == {"n": 3}


async def test_mock_force_tool_bad_json_kept_raw():
    from zyko.providers.mock import MockProvider

    provider = MockProvider()
    resp = await provider.acomplete(_mock_request(force_tool="calc", tool_args="not-json"))
    assert resp.tool_calls[0].arguments == {"_raw": "not-json"}


async def test_mock_astream_tool_call_events():
    from zyko.providers.mock import MockProvider

    provider = MockProvider()
    events = [ev async for ev in provider.astream(_mock_request(force_tool="calc"))]
    assert [ev.type for ev in events] == ["tool_call", "done"]
    assert events[0].data["name"] == "calc"
    assert json.loads(events[0].data["args_delta"]) == {}
    assert events[1].data["finish_reason"] == "tool_calls"


def test_mock_demo_enabled_paths(monkeypatch):
    from zyko.providers.mock import demo_enabled

    monkeypatch.delenv("ZYKO_DEMO", raising=False)
    assert demo_enabled() is False
    assert demo_enabled(SimpleNamespace(get=lambda _k, _d=False: True)) is True

    class Exploding:
        def get(self, *_a, **_k):  # pragma: no cover - exercised below
            raise RuntimeError("bad settings")

    assert demo_enabled(Exploding()) is False
    monkeypatch.setenv("ZYKO_DEMO", "1")
    assert demo_enabled() is True


# ------------------------------------------------------------ router/quality
def test_quality_update_merges_ewma_and_categories(tmp_path):
    ledger = QualityLedger(path=tmp_path / "l.json")
    ledger.update("p", "m", quality=0.2, win_rate=0.4, samples=10, categories={"math": 0.3})
    ledger.update("p", "m", quality=1.0, win_rate=0.8, samples=10, categories={"math": 0.9})
    score = ledger.score("p", "m")
    assert score.samples == 20
    assert 0.2 < score.quality < 1.0
    assert 0.3 < score.categories["math"] < 0.9
    assert ledger.known_models() == ["p/m"]


def test_quality_ingest_skips_malformed_entries():
    raw = {
        "schema_version": 1,
        "updated": 1.0,
        "scores": {
            "good/model": {"quality": 0.7, "win_rate": 0.6, "samples": 3, "categories": {"c": 1.5}},
            "bad/model": {"quality": "not-a-number"},
            "bad2/model": {"samples": None},
        },
    }
    ledger = QualityLedger(data=raw)
    assert ledger.known_models() == ["good/model"]
    assert ledger.score("good", "model").categories["c"] == 1.0  # clamped


def test_quality_load_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="unreadable"):
        QualityLedger.load(bad)
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON object"):
        QualityLedger.load(arr)


def test_quality_save_requires_path():
    with pytest.raises(ConfigError, match="no output path"):
        QualityLedger.empty().save()


def test_quality_roundtrip_and_table(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = QualityLedger(path=path)
    ledger.update("openai", "gpt-4o", quality=0.9, win_rate=0.8, samples=5)
    ledger.save()
    loaded = QualityLedger.load(path)
    assert loaded.score("openai", "gpt-4o").samples == 5
    table = loaded.to_table()
    assert "openai/gpt-4o" in table and "quality" in table
    assert "ledger empty" in QualityLedger.empty().to_table()


# ------------------------------------------------------------ config/settings
def test_settings_env_overrides_typed(monkeypatch):
    monkeypatch.setenv("ZYKO_GATEWAY_PORT", "9999")
    monkeypatch.setenv("ZYKO_REQUEST_TIMEOUT", "45.5")
    monkeypatch.setenv("ZYKO_ROUTER_STRATEGY", "quality")
    monkeypatch.setenv("ZYKO_GATEWAY_API_KEY", "secret")
    monkeypatch.setenv("ZYKO_DEFAULT_POLICY", "strict")
    s = Settings.load()
    assert s.get("gateway.port") == 9999
    assert s.get("router.request_timeout_s") == 45.5
    assert s.get("router.strategy") == "quality"
    assert s.get("gateway.api_key") == "secret"
    assert s.get("default_policy") == "strict"


def test_settings_env_overrides_do_not_poison_defaults(monkeypatch):
    """Regression: env overrides used to mutate the module-level DEFAULTS.

    _deep_merge shared nested dicts, so the first Settings.load() call with
    ZYKO_* env vars permanently rewrote the defaults for the whole process —
    contaminating later calls, long-lived gateway processes and other tests.
    """
    monkeypatch.setenv("ZYKO_GATEWAY_PORT", "4242")
    monkeypatch.setenv("ZYKO_ROUTER_STRATEGY", "quality")
    assert Settings.load().get("gateway.port") == 4242
    assert Settings.load().get("router.strategy") == "quality"
    monkeypatch.delenv("ZYKO_GATEWAY_PORT")
    monkeypatch.delenv("ZYKO_ROUTER_STRATEGY")
    fresh = Settings.load()
    assert fresh.get("gateway.port") == 8787
    assert fresh.get("router.strategy") == "balanced"


def test_settings_env_bad_number_stays_string(monkeypatch):
    monkeypatch.setenv("ZYKO_GATEWAY_PORT", "not-a-number")
    assert Settings.load().get("gateway.port") == "not-a-number"


def test_settings_rejects_non_mapping_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYKO_CONFIG_DIR", str(tmp_path))
    cfg = tmp_path / "config.yaml"
    cfg.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML mapping"):
        Settings.load()
    cfg.write_text("router: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid config file"):
        Settings.load()


def test_settings_env_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYKO_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MY_TEST_KEY", "abc123")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("gateway:\n  api_key: ${MY_TEST_KEY}\n", encoding="utf-8")
    s = Settings.load()
    assert s.get("gateway.api_key") == "abc123"
    assert s.source == cfg


def test_settings_section_and_provider_settings():
    s = Settings({"router": "not-a-dict", "providers": {"openai": {}, "bad": 5}})
    assert s.section("router") == {}
    assert s.provider_settings == {"openai": {}}
    assert s.provider_setting("missing") == {}


def test_settings_write_template_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYKO_CONFIG_DIR", str(tmp_path))
    target = tmp_path / "custom.yaml"
    written = Settings({}).write_template(target)
    assert written == target and target.exists()
    with pytest.raises(ConfigError, match="refusing to overwrite"):
        Settings({}).write_template(target)


# ------------------------------------------------------------ gateway/server
@pytest.fixture()
def gw():
    router = Router({"fake": FakeProvider(script=["answer"])})
    httpd = serve(router, host="127.0.0.1", port=0)
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture()
def secured_gw():
    router = Router({"fake": FakeProvider(script=["answer"])})
    httpd = serve(router, host="127.0.0.1", port=0, api_key="kw")
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _post(base: str, path: str, payload: Any, headers: dict | None = None):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    with httpx.Client(base_url=base) as client:
        try:
            resp = client.post(path, content=data, headers=headers or {}, timeout=10)
            return resp.status_code, resp.text
        except httpx.HTTPStatusError as exc:  # pragma: no cover
            return exc.response.status_code, exc.response.text


def test_gateway_get_404_and_query_string(gw):
    with httpx.Client(timeout=10) as client:
        resp = client.get(gw + "/v1/nothing")
        assert resp.status_code == 404
        resp = client.get(gw + "/healthz?probe=1")
        assert resp.status_code == 200 and resp.json()["status"] == "ok"


def test_gateway_get_requires_auth(secured_gw):
    with httpx.Client(timeout=10) as client:
        resp = client.get(secured_gw + "/healthz")
        assert resp.status_code == 401
        resp = client.get(secured_gw + "/v1/models", headers={"Authorization": "Bearer kw"})
        assert resp.status_code == 200


def test_gateway_post_invalid_json_and_bad_messages(gw):
    status, body = _post(gw, "/v1/chat/completions", b"{not json")
    assert status == 400 and "not valid JSON" in body
    status, body = _post(gw, "/v1/chat/completions", {"messages": "just-a-string"})
    assert status == 400 and "bad request" in body


def test_gateway_accepts_tool_messages(gw):
    status, body = _post(
        gw,
        "/v1/chat/completions",
        {
            "model": "auto",
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "calc", "arguments": '{"x": 1}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "res"},
                {"role": "user", "content": "hi"},
            ],
        },
    )
    assert status == 200 and json.loads(body)["choices"][0]["message"]["content"] == "answer"


# --------------------------------------------------------------- mcp/client
def _boom_server(tmp_path: Path) -> Path:
    """MCP fixture: garbage line on stdout, paged tools, an isError tool."""
    script = tmp_path / "boom_server.py"
    script.write_text(
        "import json,sys\n"
        "print('GARBAGE-NOT-JSON'); sys.stdout.flush()\n"
        "for raw in sys.stdin:\n"
        "    raw=raw.strip()\n"
        "    if not raw: continue\n"
        "    try: msg=json.loads(raw)\n"
        "    except Exception: continue\n"
        "    mid=msg.get('id')\n"
        "    if mid is None: continue\n"
        "    m=msg.get('method')\n"
        "    if m=='initialize':\n"
        "        result={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'boom','version':'1'}}\n"
        "    elif m=='tools/list':\n"
        "        cur=(msg.get('params') or {}).get('cursor')\n"
        "        if not cur:\n"
        "            result={'tools':[{'name':'page1','description':'p1','inputSchema':{'type':'object','properties':{}}}],'nextCursor':'2'}\n"
        "        else:\n"
        "            result={'tools':[{'name':'boom','description':'fails','inputSchema':{'type':'object','properties':{}}}]}\n"
        "    elif m=='tools/call':\n"
        "        result={'content':[{'type':'text','text':'it failed'}],'isError':True}\n"
        "    else:\n"
        "        sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':mid,'error':{'code':-32601,'message':'no such method'}})+chr(10)); sys.stdout.flush(); continue\n"
        "    sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':mid,'result':result})+chr(10)); sys.stdout.flush()\n",
        encoding="utf-8",
    )
    return script


async def test_mcp_client_lifecycle_with_echo_fixture():
    client = MCPClient("echo", [sys.executable, str(FIXTURE)])
    await client.start()
    await client.start()  # idempotent
    tools = await client.list_tools()
    assert [t["name"] for t in tools] == ["echo"]
    result = await client.call_tool("echo", {"text": "hi"})
    assert result == "echo: hi"
    assert client.server_info.get("name") == "echo"
    namespaced = client.as_tools()
    assert namespaced[0]["name"] == "echo__echo"
    assert client.as_tools([{"name": "x", "description": "", "parameters": None}])[0][
        "parameters"
    ] == {"type": "object", "properties": {}}
    assert MCPClient.split_qualified("srv__tool") == ("srv", "tool")
    assert MCPClient.split_qualified("plain") is None
    await client.aclose()


def test_mcp_sync_convenience_roundtrip():
    client = MCPClient("echo", [sys.executable, str(FIXTURE)]).start_sync()
    try:
        tools = client.list_tools_sync()
        assert tools and tools[0]["name"] == "echo"
        assert client.call_tool_sync("echo", {"text": "x"}) == "echo: x"
    finally:
        client.close_sync()


async def test_mcp_client_rejects_empty_command():
    with pytest.raises(MCPError, match="empty command"):
        MCPClient("x", [])


async def test_mcp_request_before_start():
    client = MCPClient("x", [sys.executable, str(FIXTURE)])
    with pytest.raises(MCPError, match="not started"):
        await client._request("ping")


async def test_mcp_spawn_failure_is_friendly():
    client = MCPClient("gone", ["/nonexistent/zyko-mcp-binary"])
    with pytest.raises(MCPError, match="cannot spawn"):
        await client.start()


async def test_mcp_request_timeout_raises_friendly_error():
    silent = MCPClient(
        "silent",
        [sys.executable, "-c", "import sys\nfor line in sys.stdin:\n    pass\n"],
        request_timeout=0.3,
    )
    with pytest.raises(ZykoTimeoutError, match="no response to 'initialize'"):
        await silent.start()
    await silent.aclose()


async def test_mcp_server_error_and_unknown_tool(tmp_path):
    client = MCPClient("echo", [sys.executable, str(FIXTURE)])
    await client.start()
    with pytest.raises(MCPError, match="-32601"):
        await client._request("no/such/method")
    with pytest.raises(MCPError, match="unknown tool"):
        await client.call_tool("nope", {})
    await client.aclose()


async def test_mcp_paging_and_iserror(tmp_path):
    client = MCPClient("boom", [sys.executable, str(_boom_server(tmp_path))])
    await client.start()
    tools = await client.list_tools()
    assert [t["name"] for t in tools] == ["page1", "boom"]
    with pytest.raises(MCPError, match="it failed"):
        await client.call_tool("boom", {})
    await client.aclose()


# ------------------------------------------------------------ platform/paths
def test_paths_xdg_branches(tmp_path, monkeypatch):
    from zyko.platform.paths import (
        agents_dir,
        audit_log,
        budget_file,
        cache_dir,
        config_dir,
        data_dir,
        ledger_file,
        policies_dir,
        policies_search_dirs,
        sessions_db,
    )

    for var in ("ZYKO_CONFIG_DIR", "ZYKO_DATA_DIR", "ZYKO_CACHE_DIR"):
        monkeypatch.delenv(var, raising=False)
    # XDG variables are honoured by the Linux branch only (macOS uses
    # ~/Library, Windows uses %APPDATA%), so pin the OS like test_macos_branch.
    import zyko.platform.paths as _paths
    from zyko.platform.detect import OSKind

    monkeypatch.setattr(_paths, "detect_os", lambda: OSKind.LINUX)
    monkeypatch.setattr(_paths, "_home", lambda: tmp_path / "home")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert config_dir() == tmp_path / "cfg" / "zyko"
    assert data_dir() == tmp_path / "data" / "zyko"
    assert cache_dir() == tmp_path / "cache" / "zyko"
    assert agents_dir(create=True).is_dir()
    assert policies_dir(create=True).is_dir()
    assert ledger_file().name == "quality_ledger.json"
    assert budget_file().name == "budget_state.json"
    assert sessions_db().name == "sessions.db"
    assert audit_log().name == "audit.jsonl"
    dirs = policies_search_dirs()
    assert any(d.name == "policies" for d in dirs)


def test_paths_termux_marker_written(tmp_path, monkeypatch):
    from zyko.platform.paths import ensure_layout

    for var in ("ZYKO_CONFIG_DIR", "ZYKO_DATA_DIR", "ZYKO_CACHE_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(sys, "platform", "linux")
    paths = ensure_layout()
    assert (paths["data"] / ".termux-ok").exists()


def test_detect_termux(monkeypatch):
    from zyko.platform.detect import OSKind, detect_os, is_mobile, is_termux

    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    assert is_termux() and detect_os() is OSKind.TERMUX and is_mobile()


# -------------------------------------------------------- providers/anthropic
def _anthropic_provider():
    from zyko.providers.anthropic import AnthropicProvider

    return AnthropicProvider(api_key="k", base_url="http://t")


def test_anthropic_build_request_payload():
    provider = _anthropic_provider()
    request = ChatRequest(
        messages=[Message.system("be nice"), Message.user("hello")],
        temperature=0.4,
        max_tokens=128,
        tools=[
            {"name": "calc", "description": "d", "parameters": {"type": "object", "properties": {}}}
        ],
    )
    url, payload, headers = provider._build(request, stream=False)
    assert url.endswith("/messages")
    assert payload["system"] == "be nice"
    assert payload["max_tokens"] == 128 and payload["temperature"] == 0.4
    assert payload["tools"][0]["name"] == "calc"
    assert headers["x-api-key"] == "k"


def test_anthropic_parse_response_blocks_and_stop_reasons():
    provider = _anthropic_provider()
    request = ChatRequest(messages=[Message.user("hi")])
    resp = provider._parse_response(
        {
            "id": "m1",
            "content": [
                {"type": "text", "text": "part1"},
                {"type": "text", "text": "part2"},
                {"type": "tool_use", "id": "t1", "name": "calc", "input": {"x": 1}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 3, "output_tokens": 4},
        },
        request,
    )
    assert resp.content == "part1\npart2"
    assert resp.tool_calls[0].arguments == {"x": 1}
    assert resp.finish_reason == "tool_calls"
    resp2 = provider._parse_response({"stop_reason": "martian"}, request)
    assert resp2.finish_reason == "stop"


def test_anthropic_stream_chunk_branches():
    provider = _anthropic_provider()
    state: dict[str, Any] = {}
    assert (
        provider._parse_stream_chunk(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}, state
        )
        is None
    )
    assert (
        provider._parse_stream_chunk(
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "t", "name": "calc"},
            },
            state,
        ).type
        == "tool_call"
    )
    ev = provider._parse_stream_chunk(
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"x":'},
        },
        state,
    )
    assert ev.data["args_delta"] == '{"x":'
    assert (
        provider._parse_stream_chunk(
            {"type": "content_block_delta", "index": 0, "delta": {"text": "hey"}}, state
        ).data["text"]
        == "hey"
    )
    assert (
        provider._parse_stream_chunk(
            {"type": "content_block_delta", "index": 0, "delta": {}}, state
        )
        is None
    )
    assert (
        provider._parse_stream_chunk(
            {"type": "message_delta", "usage": {"output_tokens": 5}}, state
        ).type
        == "usage"
    )
    assert provider._parse_stream_chunk({"type": "message_delta"}, state) is None
    assert (
        provider._parse_stream_chunk(
            {"type": "message_start", "message": {"usage": {"input_tokens": 2}}}, state
        ).type
        == "usage"
    )
    assert provider._parse_stream_chunk({"type": "ping"}, state) is None


# --------------------------------------------------- providers/openai_compat
def _openai_provider(**kw: Any):
    from zyko.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(api_key="k", base_url="http://t", **kw)


def test_openai_build_stream_options_and_reasoning_models():
    provider = _openai_provider()
    request = ChatRequest(messages=[Message.user("hi")], max_tokens=100)
    _url, payload, headers = provider._build(request, stream=True)
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_tokens"] == 100
    assert headers["Authorization"] == "Bearer k"
    request2 = ChatRequest(messages=[Message.user("hi")], model="o4-mini", max_tokens=50)
    _url2, payload2, _h2 = provider._build(request2, stream=False)
    assert "stream_options" not in payload2
    assert payload2["max_completion_tokens"] == 50
    request3 = ChatRequest(
        messages=[Message.user("hi")],
        tools=[
            {"name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}
        ],
        tool_choice="auto",
    )
    _u3, payload3, _h3 = provider._build(request3, stream=False)
    assert payload3["tool_choice"] == "auto"


def test_openai_parse_stream_chunk_all_types():
    provider = _openai_provider()
    state: dict[str, Any] = {}
    assert (
        provider._parse_stream_chunk({"choices": [{"delta": {"content": "hi"}}]}, state).data[
            "text"
        ]
        == "hi"
    )
    tc_ev = provider._parse_stream_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "1", "function": {"name": "f", "arguments": "{}"}}
                        ]
                    }
                }
            ]
        },
        state,
    )
    assert tc_ev.type == "tool_call" and tc_ev.data["name"] == "f"
    assert provider._parse_stream_chunk({"usage": {"prompt_tokens": 1}}, state).type == "usage"
    assert (
        provider._parse_stream_chunk(
            {"choices": [{"delta": {}, "finish_reason": "stop"}]}, state
        ).type
        == "done"
    )
    assert provider._parse_stream_chunk({"choices": [{"delta": {}}]}, state) is None


async def test_provider_astream_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="kaboom")

    provider = _openai_provider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="kaboom|500"):
        async for _ev in provider.astream(ChatRequest(messages=[Message.user("hi")])):
            pass


async def test_provider_ndjson_stream_parsing():
    lines = (
        '{"choices": [{"delta": {"content": "hel"}}]}\n'
        '{"choices": [{"delta": {"content": "lo"}}]}\n'
        "not-json\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=lines.encode())

    class NDJSONProvider(_openai_provider().__class__):
        _stream_protocol = "ndjson"

    provider = NDJSONProvider(
        api_key="k", base_url="http://t", transport=httpx.MockTransport(handler)
    )
    events = [ev async for ev in provider.astream(ChatRequest(messages=[Message.user("hi")]))]
    assert "".join(ev.data.get("text", "") for ev in events if ev.type == "text") == "hello"


def test_safe_json_variants():
    from zyko.providers.base import _safe_json

    assert _safe_json('{"a": 1}') == {"a": 1}
    assert _safe_json("") == {}
    assert _safe_json("nope") == {"_raw": "nope"}
    assert _safe_json("[1]") == {"_raw": "[1]"}


# -------------------------------------------------------- providers registry
def test_registry_unknown_provider_hint():
    from zyko.providers import get_provider_class, provider_names

    with pytest.raises(ConfigError, match="available providers"):
        get_provider_class("no-such-provider")
    assert "openai" in provider_names() and "anthropic" in provider_names()


def test_build_provider_requires_key_hint(monkeypatch):
    from zyko.providers import build_provider

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        build_provider("openai", {})


def test_build_provider_local_needs_no_key(monkeypatch):
    from zyko.providers import build_provider, is_configured

    assert is_configured("ollama") is True
    provider = build_provider("ollama", {})
    assert provider.local is True


# ----------------------------------------------------------------- CLI paths
def _with_fake(monkeypatch):
    fake = FakeProvider(script=["fake answer"])
    monkeypatch.setattr("zyko.cli.commands.configured_providers", lambda *_a, **_k: {"fake": fake})
    return fake


def test_cmd_models_table_and_unknown_provider(monkeypatch, capsys):
    from zyko.cli import main

    _with_fake(monkeypatch)
    assert main(["models"]) == 0
    assert "fake/fake-small" in capsys.readouterr().out
    # `models` takes the provider as a positional arg; main() converts the
    # ConfigError into a [FAIL] line with a non-zero exit code.
    capsys.readouterr()
    assert main(["models", "nope"]) != 0
    assert "not configured" in capsys.readouterr().err


def test_cmd_route_json_and_prompt_estimate(monkeypatch, capsys):
    from zyko.cli import main

    _with_fake(monkeypatch)
    assert main(["route", "tell me about routing engines", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["strategy"] == "balanced"
    assert plan["est_input_tokens"] > 1


def test_cmd_ask_explain_and_receipt(monkeypatch, capsys, tmp_path):
    from zyko.cli import main

    _with_fake(monkeypatch)
    receipt_path = tmp_path / "receipt.json"
    assert main(["ask", "hello", "--explain", "--receipt", str(receipt_path)]) == 0
    out = capsys.readouterr().out
    assert "fake answer" in out and "routed via fake/" in out
    receipt = json.loads(receipt_path.read_text())
    assert receipt["attempts"][0]["outcome"] == "ok"


def test_cmd_serve_success_then_interrupt(monkeypatch, capsys):
    """Happy-path serve: prints the URL, shuts down cleanly on Ctrl+C."""
    from zyko.cli import main

    class DummyHTTPD:
        def __init__(self):
            self.server_address = ("127.0.0.1", 8787)
            self.shutdown_called = False

        def shutdown(self):
            self.shutdown_called = True

    dummy = DummyHTTPD()
    monkeypatch.setattr("zyko.gateway.server.serve", lambda *a, **k: dummy)
    monkeypatch.setattr(
        "zyko.cli.commands.time.sleep", lambda *_a: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    assert main(["serve", "--demo"]) == 0
    assert dummy.shutdown_called
    assert "gateway on http://" in capsys.readouterr().out


def test_sessions_clear_requires_yes_and_works(capsys):
    from zyko.agents.memory import MemoryStore
    from zyko.cli import main

    store = MemoryStore()
    sid = store.create_session()
    store.append(sid, Message.user("x"))
    # main() turns the ConfigError into a friendly [FAIL] line + non-zero exit
    assert main(["sessions", "clear"]) != 0
    assert "--yes" in capsys.readouterr().err
    assert main(["sessions", "clear", "--yes"]) == 0
    assert store.list_sessions() == []
    assert main(["sessions", "show", "missing-session"]) == 1


def test_sessions_rm_and_show(capsys):
    from zyko.agents.memory import MemoryStore
    from zyko.cli import main

    store = MemoryStore()
    sid = store.create_session()
    store.append(sid, Message.user("question"))
    store.append(sid, Message.assistant("answer", tool_calls=None))
    assert main(["sessions", "show", sid]) == 0
    assert "question" in capsys.readouterr().out
    assert main(["sessions", "rm", sid, "ghost"]) == 0
    assert MemoryStore().list_sessions() == []


def test_cost_report_from_audit_log(monkeypatch, capsys):
    from zyko.cli import main
    from zyko.platform.paths import audit_log

    now = time.time()
    path = audit_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        {
            "ts": now,
            "event": "usage",
            "cost": 0.01,
            "candidate": "openai/gpt-4o",
            "estimated": False,
        },
        {"ts": now, "event": "usage", "cost": 0.02, "candidate": "mock/mock", "estimated": True},
        {
            "ts": now - 30 * 86400,
            "event": "usage",
            "cost": 99.0,
            "candidate": "old/entry",
            "estimated": False,
        },
        {"ts": now, "event": "deny", "rule": "tools.shell"},
        {"ts": now, "event": "allow", "redactions": 1},
        "not-json-at-all\n",
    ]
    path.write_text(
        "\n".join(json.dumps(e) if isinstance(e, dict) else e for e in entries), encoding="utf-8"
    )

    assert main(["cost", "--days", "1"]) == 0
    human = capsys.readouterr().out
    assert "$0.030000" in human and "vendor=1, estimated=1" in human

    assert main(["cost", "--days", "1", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_spend_usd"] == 0.03
    assert report["events"] == {"usage": 2, "deny": 1, "allow": 1}
    assert report["denied_by_rule"] == {"tools.shell": 1}
    assert report["redaction_events"] == 1
    assert report["cost_accounting"] == {"vendor_reported": 1, "kernel_estimated": 1}


def test_policy_show_and_redact(monkeypatch, capsys):
    from zyko.cli import main

    assert main(["policy", "show"]) == 0
    out = capsys.readouterr().out
    assert "policy:" in out
    assert main(["policy", "redact", "contact bob@corp.com or +12345678901"]) == 0
    redacted = capsys.readouterr().out
    assert "bob@corp.com" not in redacted


# ------------------------------------------------------------------ benchmark
def test_build_suite_deterministic_and_hashed():
    a, b = build_suite(), build_suite()
    assert [t.tid for t in a] == [t.tid for t in b]
    assert suite_hash(a) == suite_hash(b) and len(suite_hash(a)) == 16
    assert len(a) == 24 and {t.category for t in a} == {
        "instruction_following",
        "extraction",
        "classification",
        "math",
        "summarization",
        "format",
    }


@pytest.mark.parametrize(
    ("grader", "answer", "expected", "want"),
    [
        ("exact", "  Nature \n", "nature", True),
        ("contains_all", "the river and market", "river||market", True),
        ("contains_all", "only river", "river||market", False),
        ("json", 'noise {"units": 3, "topic": "x"} trailing', "units,topic", True),
        ("json", '{"units": 3}', "units,topic", False),
        ("json", "no json here", "units,topic", False),
        ("numeric", "value is 1,234 units", "1234", True),
        ("numeric", "no digits", "5", False),
        ("regex", "ID[river:07]", r"ID\[river:07\]", True),
        ("regex", "ID[river:7]", r"ID\[river:07\]", False),
    ],
)
def test_graders_matrix(grader, answer, expected, want):
    assert GRADERS[grader](answer, expected, {}) is want


async def test_run_candidate_reports_and_error_path():
    router = Router(
        {"fake": FakeProvider(script=["river-market", "10"], fail_first=1, name="fake")}
    )
    tasks = build_suite()[:3]
    report = await _run_candidate(router, "fake", "fake-small", tasks, concurrency=2)
    assert report["candidate"] == "fake/fake-small"
    assert set(report["categories"]) == {t.category for t in tasks}
    assert report["token_usage"]["input"] > 0
    failing = Router({"fake": FakeProvider(fail_first=99, name="fake")})
    broken = await _run_candidate(failing, "fake", "fake-small", tasks[:1], concurrency=1)
    assert broken["tasks"][0]["ok"] is False and "error" in broken["tasks"][0]


def test_run_bench_demo_updates_ledger(monkeypatch, capsys, tmp_path):

    ledger_path = tmp_path / "l.json"
    args = SimpleNamespace(
        demo=True,
        json_out=str(tmp_path / "report.json"),
        ledger=str(ledger_path),
        concurrency=4,
        repeats=1,
        update_ledger=True,
    )
    from zyko.benchmarks.routing_bench import run_bench

    assert run_bench(args) == 0
    out = capsys.readouterr().out
    assert "best overall" in out and "ledger updated" in out
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["seed"] == 42 and len(report["results"]) == 2
    ledger = QualityLedger.load(ledger_path)
    assert set(ledger.known_models()) == {"mock/mock-mini", "mock/mock-large"}


# ------------------------------------------------------------- core/events
async def test_accumulate_stream_merges_tool_deltas_and_usage():
    async def gen():
        yield StreamEvent("text", {"text": "hel"})
        yield StreamEvent("tool_call", {"index": 1, "id": "a", "name": "f", "args_delta": '{"x":'})
        yield StreamEvent("tool_call", {"index": 1, "args_delta": "1}"})
        yield StreamEvent("usage", {"usage": {"input_tokens": 2, "output_tokens": 3}})

    text, tools, usage = await accumulate_stream(gen())
    assert text == "hel"
    assert tools == [{"id": "a", "name": "f", "arguments": '{"x":1}'}]
    assert usage == {"input_tokens": 2, "output_tokens": 3}


async def test_sse_data_events_partial_lines_and_done():
    async def gen():
        yield b'data: {"a":'
        yield b'1}\ndata: not json\n\n: keep-alive\ndata: [DONE]\ndata: {"after": true}\n'

    out = [ev async for ev in sse_data_events(gen())]
    assert out == [{"a": 1}]


# ------------------------------------------------------------------- cli/ui
def test_ui_table_bullets_error(capsys):
    from zyko.cli import ui

    ui.table(["h1", "h2"], [["a", 1], ["longer", "x"]])
    ui.bullets(["one", "two"])
    ui.error(ZykoError("line1\nline2"))
    cap = capsys.readouterr()
    out = cap.out + cap.err
    assert "h1" in out and "longer" in out and "one" in out and "line2" in out


# ------------------------------------------------------- core response/models
def test_usage_merge_cost_and_request_helpers():
    base = Usage(10, 5)
    assert base.merged(Usage(1, 1)) == Usage(11, 6)
    assert base.merged(None) == base
    info = ModelInfo("p", "m", 1000, 100, True, False, 1.0, 3.0, [])
    assert base.cost_usd(info) == pytest.approx((10 * 1.0 + 5 * 3.0) / 1_000_000)
    assert base.cost_usd(None) is None
    assert ModelInfo("p", "m", 1, 1, True, False, None, None, []).cost_usd(10, 10) is None

    request = ChatRequest(
        messages=[Message.system("sys"), Message.user("hello")], metadata={"k": 1}
    )
    assert request.text == "sys\nhello"
    pinned = request.with_model("p/m")
    assert pinned.model == "p/m" and pinned.metadata == {"k": 1}


# -------------------------------------------------------- agents/memory meta
def test_memory_history_survives_corrupted_tool_meta(tmp_path):
    from zyko.agents.memory import MemoryStore

    store = MemoryStore()
    sid = store.create_session()
    store.append(
        sid, Message.assistant("ok", tool_calls=[ToolCall(id="t", name="f", arguments={"a": 1})])
    )
    history = store.history(sid)
    assert history[0].tool_calls[0].arguments == {"a": 1}

    db = sqlite3.connect(store.path)
    db.execute("UPDATE messages SET meta = 'not-json' WHERE session_id = ?", (sid,))
    db.commit()
    db.close()
    fresh = MemoryStore().history(sid)
    assert fresh[0].tool_calls is None
