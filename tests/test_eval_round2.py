"""Evaluation round 2 (v0.3.2): router streaming governance, policy engine,
gateway error surfaces, MCP lifecycle edges, platform detection, kernel math."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import pytest

from tests.fakes import FakeProvider
from zyko.core.events import StreamEvent, done_event, text_event
from zyko.core.messages import Message, ToolCall
from zyko.core.response import ChatRequest
from zyko.exceptions import ConfigError, ProviderError, ToolError
from zyko.gateway.server import serve
from zyko.policy.engine import PolicyEngine, Redactor
from zyko.providers.ollama import OllamaProvider
from zyko.providers.openai_compat import OpenAICompatProvider, OpenRouterProvider
from zyko.router.engine import Router
from zyko.router.health import HealthTracker


def _req(**kw: Any) -> ChatRequest:
    return ChatRequest(messages=[Message.user("hi")], **kw)


# --------------------------------------------------------------- router engine
def test_router_rejects_empty_and_unknown_strategy():
    with pytest.raises(ProviderError, match="no providers configured"):
        Router({})
    with pytest.raises(ProviderError, match="unknown routing strategy"):
        Router({"fake": FakeProvider()}, strategy="bogus")


async def test_router_breaker_skip_after_open_circuit():
    router = Router(
        {"fake": FakeProvider(fail_first=99, name="fake")},
        breaker_threshold=1,
        breaker_cooldown_s=60.0,
        max_fallbacks=3,
    )
    with pytest.raises(ProviderError, match="all routing candidates failed"):
        await router.aroute(_req())
    with pytest.raises(ProviderError, match="skipped-breaker"):
        await router.aroute(_req())  # circuit now open → skip without calling


async def test_router_model_deny_hides_candidate_and_provider_allow_denies():
    # 1. models.deny filters the candidate board entirely — the denied model
    #    never appears in the ranking (deny = invisible, not an attempt).
    policy = PolicyEngine({"version": 1, "name": "p", "models": {"deny": ["fake/fake-small"]}})
    router = Router({"fake": FakeProvider(script=["ok"])}, policy=policy, max_fallbacks=3)
    outcome = await router.aroute(_req())
    assert outcome.candidate == "fake/fake-large"
    assert all(a.candidate != "fake/fake-small" for a in outcome.attempts)
    assert all(e["candidate"] != "fake/fake-small" for e in outcome.receipt["ranking"])

    # 2. providers.allow denies at request-check time → skipped-policy attempts.
    strict = PolicyEngine({"version": 1, "providers": {"allow": ["openai"]}})
    router2 = Router({"fake": FakeProvider(script=["ok"])}, policy=strict, max_fallbacks=3)
    with pytest.raises(ProviderError, match="skipped-policy"):
        await router2.aroute(_req())


class _EmptyStreamProvider(FakeProvider):
    async def astream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        return
        yield  # pragma: no cover - makes this an async generator


async def test_stream_route_falls_back_past_empty_stream():
    router = Router(
        {
            "empty": _EmptyStreamProvider(name="empty"),
            "fake": FakeProvider(script=["streamed"], name="fake"),
        },
        max_fallbacks=3,
    )
    events = [ev async for ev in router.astream_route(_req())]
    types = [ev.type for ev in events]
    assert "meta" in types and "done" in types
    assert any(ev.type == "text" and "streamed" in ev.data["text"] for ev in events)


async def test_stream_route_records_vendor_usage_with_policy(tmp_path):
    policy = PolicyEngine(
        {"version": 1, "name": "p", "audit": {"enabled": True}},
        state_dir=tmp_path,
    )
    router = Router(
        {"fake": FakeProvider(script=["hi"], input_price=2.0, output_price=4.0)},
        policy=policy,
    )
    events = [ev async for ev in router.astream_route(_req())]
    assert events[-1].type == "done"
    # vendor-reported usage (20 in / 10 out at $2/$4 per Mtok) was charged
    from zyko.platform.paths import audit_log

    audit = audit_log()
    assert audit.exists()
    entries = [json.loads(line) for line in audit.read_text().splitlines()]
    usage = [e for e in entries if e.get("event") == "usage"]
    assert usage and usage[0]["estimated"] is False
    assert usage[0]["cost"] == pytest.approx((20 * 2.0 + 10 * 4.0) / 1e6)


async def test_stream_route_all_failed_raises():
    router = Router(
        {"empty": _EmptyStreamProvider(name="empty")}, breaker_threshold=50, max_fallbacks=1
    )
    with pytest.raises(ProviderError, match="all routing candidates failed"):
        [ev async for ev in router.astream_route(_req())]


# ------------------------------------------------------------------- gateway
def test_gateway_upstream_failure_returns_502():
    router = Router({"fake": FakeProvider(fail_first=99, name="fake")})
    httpd = serve(router, host="127.0.0.1", port=0)
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                base + "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["type"] == "zyko_upstream_error"
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------- mcp client
def _exit_after_init_server(tmp_path: Path) -> Path:
    """MCP fixture that shuts its stdout down right after initialize."""
    script = tmp_path / "die_server.py"
    script.write_text(
        "import json,sys\n"
        "for raw in sys.stdin:\n"
        "    raw=raw.strip()\n"
        "    if not raw: continue\n"
        "    msg=json.loads(raw)\n"
        "    if msg.get('id') is None: continue\n"
        "    result={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'die','version':'1'}}\n"
        "    sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result})+chr(10)); sys.stdout.flush()\n"
        "    break\n",
        encoding="utf-8",
    )
    return script


async def test_mcp_list_tools_cached_second_call(tmp_path):
    from zyko.mcp.client import MCPClient

    fixture = Path(__file__).parent / "fixtures" / "echo_server.py"
    client = MCPClient("echo", [sys.executable, str(fixture)])
    await client.start()
    first = await client.list_tools()
    second = await client.list_tools()
    assert first == second
    await client.aclose()


async def test_mcp_closed_stream_fails_pending_request(tmp_path):
    from zyko.exceptions import MCPError
    from zyko.mcp.client import MCPClient

    client = MCPClient("die", [sys.executable, str(_exit_after_init_server(tmp_path))])
    await client.start()
    with pytest.raises(MCPError, match="closed the stream"):
        await client._request("tools/list")
    await client.aclose()


# ------------------------------------------------------------- platform detect
def test_detect_windows_macos_android(monkeypatch):
    from zyko.platform.detect import OSKind, detect_os, is_android, is_termux

    monkeypatch.setattr(sys, "platform", "win32")
    assert detect_os() is OSKind.WINDOWS
    monkeypatch.setattr(sys, "platform", "darwin")
    assert detect_os() is OSKind.MACOS
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("os.path.exists", lambda p: p == "/system/build.prop")
    assert is_android() is True
    assert detect_os() is OSKind.ANDROID
    monkeypatch.undo()
    monkeypatch.setattr(sys, "prefix", "/data/data/com.termux/files/usr")
    assert is_termux() is True


# -------------------------------------------------------- providers odds+ends
def test_openrouter_default_headers():
    provider = OpenRouterProvider(api_key="k")
    assert provider._default_headers["HTTP-Referer"].startswith("https://github.com/")
    assert provider._default_headers["X-Title"] == "ZYKO"


def test_ollama_build_with_tools_and_temperature():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")
    request = ChatRequest(
        messages=[Message.user("hi")],
        temperature=0.2,
        max_tokens=64,
        tools=[
            {"name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}
        ],
    )
    _url, payload, headers = provider._build(request, stream=False)
    assert payload["options"] == {"temperature": 0.2, "num_predict": 64}
    assert payload["tools"][0]["function"]["name"] == "f"
    assert headers == {}


def test_registry_key_resolution_paths(monkeypatch):
    from zyko.providers import _resolve_key, build_provider, configured_providers

    for env in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)
    cls = OpenAICompatProvider
    assert _resolve_key(cls, {"api_key": "sk-inline"}) == "sk-inline"
    assert _resolve_key(cls, {}) is None
    monkeypatch.setenv("GEMINI_API_KEY", "g1")
    from zyko.providers.google import GoogleProvider

    assert _resolve_key(GoogleProvider, {}) == "g1"
    # inline key wins over the environment
    built = build_provider("openai", {"api_key": "sk-inline"})
    assert built.api_key == "sk-inline"
    # unknown provider section inside configured_providers is skipped quietly
    monkeypatch.delenv("GEMINI_API_KEY")
    assert configured_providers({"ghost-provider": {}}) == {}


def test_configured_providers_skips_unreachable_local(monkeypatch):
    from zyko.providers import configured_providers

    monkeypatch.setattr(OllamaProvider, "probe", lambda self: False)
    assert configured_providers({"ollama": {}}) == {}


def test_client_accepts_policy_engine_instance(tmp_path, monkeypatch):
    from zyko.client import Zyko

    policy = PolicyEngine({"version": 1, "name": "p"}, state_dir=tmp_path)
    zyko = Zyko(
        providers={"fake": FakeProvider(script=["hi"])},
        policy=policy,
        ledger_path=tmp_path / "l.json",
    )
    assert zyko.policy is policy


# ----------------------------------------------------------------- resilience
def test_health_tracker_half_open_after_cooldown():
    tracker = HealthTracker(breaker_threshold=1, breaker_cooldown_s=0.05)
    tracker.record("p/m", latency_ms=1.0, ok=False)
    assert tracker.available("p/m") is False
    time.sleep(0.06)
    assert tracker.available("p/m") is True  # half-open probe allowed
    assert tracker.available("p/m") is True  # and the breaker stays open-reset


# ------------------------------------------------------------- core primitives
def test_event_helpers():
    assert text_event("x").data == {"text": "x"}
    assert done_event("length").data == {"finish_reason": "length"}


async def test_sse_trailing_line_variants():
    from zyko.core.events import sse_data_events

    async def gen():
        yield b'data: {"a": 1}'  # no trailing newline → flushed at EOF
        yield b""

    assert [ev async for ev in sse_data_events(gen())] == [{"a": 1}]

    async def gen2():
        yield b"data: oops-no-json"  # trailing garbage swallowed

    assert [ev async for ev in sse_data_events(gen2())] == []


def test_toolcall_from_openai_bad_args_and_message_hoisting():
    call = ToolCall.from_openai({"id": "1", "function": {"name": "f", "arguments": "{bad"}})
    assert call.arguments == {"_raw": "{bad"}
    call2 = ToolCall.from_openai({"function": {"name": "g", "arguments": {"a": 1}}})
    assert call2.arguments == {"a": 1}

    system = Message.system("be nice")
    hoisted = system.to_anthropic()
    assert hoisted == {"role": "user", "content": "be nice"}


def test_kernel_python_impl_edges():
    from zyko.kernel import python_impl

    assert python_impl.cosine_similarity([], []) == 0.0
    assert python_impl.cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert python_impl.moving_average([1.0, 2.0, 3.0], 0) == [1.0, 2.0, 3.0]
    assert python_impl.top_k([0.1, 0.9, 0.5], 2) == [1, 2]


# ----------------------------------------------------------- builtin http_get
async def test_http_get_rejects_non_http_scheme():
    from zyko.agents.tools_builtin import _http_get

    with pytest.raises(ToolError, match="only http"):
        await _http_get("ftp://example.com")


async def test_http_get_truncates_and_requires_ok(monkeypatch):
    from zyko.agents import tools_builtin

    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _url):
            return FakeResponse("x" * 100)

    monkeypatch.setattr(tools_builtin, "_http_get", tools_builtin._http_get)
    import httpx as _httpx

    monkeypatch.setattr(_httpx, "AsyncClient", FakeClient)
    body = await tools_builtin._http_get("https://example.com", max_bytes=10)
    assert body == "x" * 10

    class RaisingClient(FakeClient):
        async def get(self, _url):
            class Resp:
                def raise_for_status(self):
                    raise _httpx.HTTPStatusError(
                        "404 Not Found",
                        request=_httpx.Request("GET", "https://example.com"),
                        response=_httpx.Response(404),
                    )

            return Resp()

    monkeypatch.setattr(_httpx, "AsyncClient", RaisingClient)
    with pytest.raises(Exception):
        await tools_builtin._http_get("https://example.com")


# ---------------------------------------------------------------- policy engine
def test_redactor_luhn_and_unknown_pattern():
    redactor = Redactor.from_doc({"redact": ["credit_card", "email"]})
    hit, labels = redactor.apply("pay with 4111 1111 1111 1111 please")
    assert labels == ["credit_card"] and "4111" not in hit
    # luhn-invalid digit runs look like order numbers → kept intact
    kept, labels2 = redactor.apply("order 4111 1111 1111 1112 shipped")
    assert "4111 1111 1111 1112" in kept and labels2 == []
    with pytest.raises(ConfigError, match="unknown builtin redaction pattern"):
        Redactor.from_doc({"redact": ["no-such-pattern"]})


def test_redactor_invalid_custom_regex():
    with pytest.raises(ConfigError, match="invalid custom redaction rule"):
        Redactor.from_doc({"custom": [{"pattern": "(["}]})


def test_policy_document_validation_errors():
    with pytest.raises(ConfigError, match="must be a mapping"):
        PolicyEngine(["not", "a", "mapping"])
    with pytest.raises(ConfigError, match="unsupported policy schema version"):
        PolicyEngine({"version": 99})
    engine = PolicyEngine({"version": 1, "defaults": "oops", "privacy": "oops"})
    assert any("'defaults' must be a mapping" in w for w in engine.warnings)
    assert any("'privacy' must be a mapping" in w for w in engine.warnings)


def test_policy_provider_allow_and_max_tokens_rewrite(tmp_path):
    policy = PolicyEngine(
        {
            "version": 1,
            "providers": {"allow": ["openai"]},
            "defaults": {"max_tokens_per_request": 50},
        },
        state_dir=tmp_path,
    )
    candidate = type("C", (), {"provider": "fake", "model": "fake-small"})()
    decision = policy.check_request(_req(max_tokens=500), candidate)
    assert decision.allowed is False and decision.reason.startswith("provider 'fake'")

    candidate2 = type("C", (), {"provider": "openai", "model": "gpt-4o"})()
    decision2 = policy.check_request(_req(max_tokens=500), candidate2)
    assert decision2.allowed is True and decision2.request.max_tokens == 50


def test_policy_redaction_rewrites_request(tmp_path):
    policy = PolicyEngine({"version": 1, "privacy": {"redact": ["email"]}}, state_dir=tmp_path)
    candidate = type("C", (), {"provider": "openai", "model": "gpt-4o"})()
    request = _req()
    request.messages[0] = Message.user("write to bob@corp.com now")
    decision = policy.check_request(request, candidate)
    assert decision.allowed is True
    assert "bob@corp.com" not in (decision.request.messages[0].content or "")
    assert decision.redactions == ["email"]


def test_load_policy_invalid_yaml(tmp_path, monkeypatch):
    from zyko.policy.engine import load_policy

    monkeypatch.chdir(tmp_path)
    (tmp_path / "broken.yaml").write_text("models: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid policy file"):
        load_policy("broken")


# ------------------------------------------------------------------- CLI bits
def test_cli_keyboard_interrupt_and_broken_pipe_subprocess():
    """POSIX exit codes, verified in a subprocess (main() dup2s real stdout)."""
    driver = (
        "import os, sys\n"
        "from zyko.cli import main\n"
        "from zyko.cli import commands\n"
        "mode = sys.argv[1]\n"
        "if mode == 'interrupt':\n"
        "    commands.cmd_version = lambda a: (_ for _ in ()).throw(KeyboardInterrupt())\n"
        "elif mode == 'pipe':\n"
        "    commands.cmd_version = lambda a: (_ for _ in ()).throw(BrokenPipeError())\n"
        "elif mode == 'pipe-no-dup2':\n"
        "    commands.cmd_version = lambda a: (_ for _ in ()).throw(BrokenPipeError())\n"
        "    os.dup2 = lambda *a, **k: (_ for _ in ()).throw(OSError('no fd'))\n"
        "sys.exit(main(['version']))\n"
    )
    for mode, expected in [("interrupt", 130), ("pipe", 141), ("pipe-no-dup2", 141)]:
        proc = subprocess.run(
            [sys.executable, "-c", driver, mode],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == expected, (mode, proc.stderr)


def test_cli_guard_output_encoding_tolerates_failures(monkeypatch, capsys):
    from zyko.cli import main

    def boom(*_a, **_k):
        raise ValueError("no reconfigure in tests")

    monkeypatch.setattr(sys.stdout, "reconfigure", boom)
    monkeypatch.setattr("sys.stderr.reconfigure", boom)
    assert main(["version"]) == 0
    assert "zyko 0." in capsys.readouterr().out


def test_sessions_show_renders_tool_calls(capsys):
    from zyko.agents.memory import MemoryStore
    from zyko.cli import main

    store = MemoryStore()
    sid = store.create_session()
    store.append(
        sid,
        Message.assistant(
            None, tool_calls=[ToolCall(id="t1", name="calculator", arguments={"expression": "1+1"})]
        ),
    )
    store.append(sid, Message.user("thanks"))
    assert main(["sessions", "show", sid]) == 0
    out = capsys.readouterr().out
    assert "calculator" in out and '{"expression": "1+1"}' in out


def test_doctor_renders_termux_and_ollama_ok(monkeypatch, capsys):
    from types import SimpleNamespace

    from zyko.cli import main

    fake_platform = SimpleNamespace(
        os=SimpleNamespace(value="termux"), describe=lambda: "Termux aarch64"
    )
    monkeypatch.setattr("zyko.cli.commands.platform_info", lambda: fake_platform)
    import httpx as _httpx

    class Resp:
        def json(self):
            return {"models": [{"name": "qwen2.5:3b"}]}

    monkeypatch.setattr(_httpx, "get", lambda *a, **k: Resp())
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "mobile" in out and "ollama reachable" in out and "qwen2.5:3b" in out


def test_agent_tool_type_error_is_caught():
    from zyko.agents.agent import Agent

    router = Router({"fake": FakeProvider(script=["done"])})
    agent = Agent(router, name="t")
    call = ToolCall(id="c1", name="calculator", arguments={"expression__bogus": "1+1"})
    result = asyncio.run(agent._execute(call))
    assert result.startswith("error: bad arguments for 'calculator'")
