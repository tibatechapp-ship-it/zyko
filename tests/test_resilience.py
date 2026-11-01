"""v0.2.0 hardening round: big-project parity patterns.

Covers:
- HTTP 429 ``Retry-After`` parsing + honoring in the retry loop (LiteLLM pattern)
- streaming cost accounting (``stream_options.include_usage`` + policy budget)
- ``zyko version`` command and ``zyko bench --repeats``
"""

from __future__ import annotations

import json

import httpx
import pytest

from zyko import kernel
from zyko.core.messages import Message
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse
from zyko.exceptions import RateLimitError
from zyko.providers.base import BaseProvider, _retry_after_seconds
from zyko.providers.openai_compat import OpenAICompatProvider
from zyko.router.engine import Router
from zyko.router.quality import QualityLedger


# --------------------------------------------------------------------- stubs
class _OpenAIStub(OpenAICompatProvider):
    """OpenAI adapter pinned to a mock transport (no network)."""

    CATALOG = [
        ModelInfo("openai", "gpt-4o-mini", 128_000, 16_384, True, True, 0.15, 0.60, ["cheap"])
    ]

    def __init__(self, handler) -> None:
        super().__init__(api_key="test-key", transport=httpx.MockTransport(handler))


def _sse(chunks: list[dict]) -> bytes:
    body = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks)
    return body + b"data: [DONE]\n\n"


# ------------------------------------------------------------- Retry-After
def test_429_parses_retry_after_seconds():
    resp = httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")
    assert _retry_after_seconds(resp) == 7.0


def test_429_parses_retry_after_http_date():
    resp = httpx.Response(
        429, headers={"Retry-After": "Fri, 01 Jan 2038 00:00:00 GMT"}, text="busy"
    )
    value = _retry_after_seconds(resp)
    assert value is not None and value > 0


def test_429_without_header_returns_none():
    assert _retry_after_seconds(httpx.Response(429, text="busy")) is None


def test_raise_for_status_attaches_retry_after():
    provider = OpenAICompatProvider(api_key="k")
    with pytest.raises(RateLimitError) as excinfo:
        provider._raise_for_status(httpx.Response(429, headers={"Retry-After": "3"}, text="busy"))
    assert excinfo.value.retry_after == 3.0
    assert excinfo.value.retryable


async def test_retry_loop_honors_retry_after(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("zyko.providers.base.asyncio.sleep", fake_sleep)

    class _RetryStub(BaseProvider):
        name = "stub"

        def _build(self, request, *, stream):
            return "http://unit/test", {"model": "m", "messages": []}, {}

        def _parse_response(self, data, request):
            return ChatResponse(id="x", provider=self.name, model="m", content="done")

    provider = _RetryStub()
    calls = {"n": 0}

    async def flaky_send(request, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError("limited", provider="stub", retry_after=2.5)
        return ChatResponse(id="ok", provider="stub", model="m", content="done")

    monkeypatch.setattr(provider, "_send", flaky_send)
    response = await provider.acomplete(ChatRequest(messages=[Message.user("hi")]))
    assert response.content == "done"
    assert calls["n"] == 2
    assert delays and delays[0] == 2.5  # vendor instruction wins over the backoff curve


# -------------------------------------------------- streaming cost accounting
async def test_stream_cost_recorded_from_vendor_usage(tmp_path):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            content=_sse(
                [
                    {"choices": [{"delta": {"content": "hello"}}]},
                    {
                        "choices": [{"delta": {}}],
                        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
                    },
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ]
            ),
        )

    from zyko.policy.engine import PolicyEngine

    provider = _OpenAIStub(handler)
    policy = PolicyEngine(
        {"version": 1, "name": "t", "defaults": {"budget_usd_per_day": 1.0}}, state_dir=tmp_path
    )
    router = Router({"openai": provider}, ledger=QualityLedger.empty(), policy=policy)

    events = [ev async for ev in router.astream_route(ChatRequest(messages=[Message.user("hi")]))]
    assert any(e.type == "text" and e.data.get("text") == "hello" for e in events)
    assert any(e.type == "done" for e in events)
    # the request asked the vendor to report usage
    assert captured["payload"]["stream_options"] == {"include_usage": True}
    # budget charged from the *real* vendor usage: (1000*0.15 + 500*0.60) / 1e6
    expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000.0
    assert policy.budget.spent_today() == pytest.approx(expected, rel=1e-6)


async def test_stream_cost_estimated_without_vendor_usage(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                [
                    {"choices": [{"delta": {"content": "hi there"}}]},
                    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                ]
            ),
        )

    from zyko.policy.engine import PolicyEngine

    provider = _OpenAIStub(handler)
    policy = PolicyEngine(
        {"version": 1, "name": "t", "defaults": {"budget_usd_per_day": 1.0}}, state_dir=tmp_path
    )
    router = Router({"openai": provider}, ledger=QualityLedger.empty(), policy=policy)

    events = [ev async for ev in router.astream_route(ChatRequest(messages=[Message.user("hi")]))]
    assert any(e.type == "text" for e in events)
    est_in = max(kernel.messages_tokens([Message.user("hi")]), 1)
    expected = (est_in * 0.15 + 400 * 0.60) / 1_000_000.0  # DEFAULT_EST_OUT = 400
    assert policy.budget.spent_today() == pytest.approx(expected, rel=1e-6)


async def test_stream_without_policy_still_works():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse([{"choices": [{"delta": {"content": "x"}}]}]))

    provider = _OpenAIStub(handler)
    router = Router({"openai": provider}, ledger=QualityLedger.empty(), policy=None)
    events = [ev async for ev in router.astream_route(ChatRequest(messages=[Message.user("hi")]))]
    assert any(e.type == "done" for e in events)


# ------------------------------------------------------------------ CLI bits
def test_version_command(capsys):
    from zyko.cli import main

    assert main(["version"]) == 0
    out = capsys.readouterr().out
    from zyko.version import __version__

    assert __version__ in out
    assert "MCP protocol" in out
    assert "MCP" in out


def test_python_dash_m_entrypoint(capsys):
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "zyko", "version"], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0
    assert "zyko" in proc.stdout


def test_bench_repeats_demo(tmp_path):
    from zyko.cli import main

    out_file = tmp_path / "bench.json"
    assert main(["bench", "--demo", "--repeats", "2", "--json-out", str(out_file)]) == 0
    report = json.loads(out_file.read_text())
    assert report["repeats"] == 2
    for candidate in report["results"]:
        assert len(candidate["tasks"]) == 48  # 24 tasks × 2 repeats
