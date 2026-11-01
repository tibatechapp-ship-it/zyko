"""Evaluation round 3: last-mile edge paths.

Covers the remaining untested branches found by the coverage audit:
- gateway: malformed Content-Length, unexpected internal error (500), client
  disconnect mid-stream
- MCP server: unexpected exception surfaced as isError, zyko_chat round-trip,
  default_policy wiring in _ensure_router, `python -m zyko.mcp.server` entry
- router: degenerate cost/latency normalisation, circuit-breaker and policy
  skips inside astream_route
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import subprocess
import sys
import time
import urllib.request

import pytest

from tests.fakes import FakeProvider
from tests.test_mcp_server_more import _serve
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import ProviderError
from zyko.gateway.server import serve
from zyko.mcp.server import ZykoMCPServer
from zyko.policy.engine import PolicyEngine
from zyko.router.engine import Router


def _req(text: str = "hello") -> ChatRequest:
    return ChatRequest(messages=[Message.user(text)])


# --------------------------------------------------------------------- gateway


def _httpd(router: Router):
    return serve(router, host="127.0.0.1", port=0)


def test_gateway_malformed_content_length_returns_400():
    """A lying Content-Length must not crash the handler (400, not a traceback)."""
    httpd = _httpd(Router({"fake": FakeProvider(script=["x"])}))
    port = httpd.server_address[1]
    try:
        payload = json.dumps({"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
        raw = (
            "POST /v1/chat/completions HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 5\r\n"
            "Connection: close\r\n\r\n" + payload
        ).encode()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(raw)
            data = sock.recv(65536).decode(errors="replace")
        assert data.startswith("HTTP/1.")
        assert " 400 " in data.split("\r\n")[0]
        # server is still alive afterwards
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
            assert resp.status == 200
    finally:
        httpd.shutdown()


def test_gateway_internal_error_returns_500():
    """A non-ZykoError escaping the router maps to a clean 500, never a hang."""
    router = Router({"fake": FakeProvider(script=["x"])})

    async def boom(request: ChatRequest):
        raise RuntimeError("kaboom")

    router.aroute = boom  # type: ignore[method-assign]
    httpd = _httpd(router)
    port = httpd.server_address[1]
    try:
        payload = json.dumps({"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=payload.encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("expected HTTP 500")
        except urllib.error.HTTPError as exc:
            assert exc.code == 500
            body = json.loads(exc.read())
            assert "internal error" in body["error"]["message"]
            assert "kaboom" in body["error"]["message"]
    finally:
        httpd.shutdown()


def test_gateway_stream_client_disconnect_is_silent():
    """Client vanishing mid-stream must not crash the worker (EPIPE is expected)."""

    class SlowFake(FakeProvider):
        async def astream(self, request):
            async for event in super().astream(request):
                await asyncio.sleep(0.05)
                yield event

    httpd = _httpd(Router({"fake": SlowFake(script=["one two three four five"])}))
    port = httpd.server_address[1]
    try:
        payload = json.dumps(
            {"model": "auto", "messages": [{"role": "user", "content": "hi"}], "stream": True}
        )
        raw = (
            "POST /v1/chat/completions HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(payload.encode())}\r\n\r\n" + payload
        ).encode()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.settimeout(5)
            sock.sendall(raw)
            assert sock.recv(4096)  # response headers (and maybe first chunk)
            # force an RST close so the very next server write hits EPIPE
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        time.sleep(0.3)  # give the worker time to hit and swallow the error
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as resp:
            assert resp.status == 200
    finally:
        httpd.shutdown()


# ------------------------------------------------------------------- mcp server


def test_mcp_unexpected_exception_surfaced_as_iserror():
    """A broken router must yield an isError result, never crash the serve loop."""
    server = ZykoMCPServer(router=object())
    responses = _serve(
        server,
        [
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "zyko_route", "arguments": {"prompt": "hi"}},
            }
        ],
    )
    result = responses[0]["result"]
    assert result["isError"] is True
    assert "internal error" in result["content"][0]["text"]


def test_mcp_zyko_chat_round_trip():
    router = Router({"fake": FakeProvider(script=["chat answer"])})
    server = ZykoMCPServer(router=router)
    responses = _serve(
        server,
        [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "zyko_chat", "arguments": {"prompt": "say hi"}},
            }
        ],
    )
    result = responses[0]["result"]
    assert result["isError"] is False
    text = result["content"][0]["text"]
    assert "chat answer" in text
    assert "routed via fake/fake-" in text
    assert "strategy=" in text


def test_mcp_ensure_router_uses_default_policy(monkeypatch):
    """default_policy from settings is loaded and attached to the router."""

    class FakeSettings:
        provider_settings: dict = {}

        def get(self, key: str, default=None):
            return {"default_policy": "p1"}.get(key, default)

    import zyko.config.settings as settings_mod
    import zyko.policy.engine as policy_mod

    monkeypatch.setattr(settings_mod.Settings, "load", staticmethod(lambda: FakeSettings()))
    sentinel = PolicyEngine({"version": 1, "name": "t", "providers": {"allow": ["ollama"]}})
    monkeypatch.setattr(policy_mod, "load_policy", lambda name: sentinel)

    server = ZykoMCPServer()  # no router injected -> _ensure_router builds one
    router = server._ensure_router()
    assert router.policy is sentinel
    # second call must return the same instance (built exactly once)
    assert server._ensure_router() is router


def test_mcp_main_entrypoint_exit_zero():
    """`python -m zyko.mcp.server` boots and exits 0 on immediate EOF (stdin)."""
    proc = subprocess.run(
        [sys.executable, "-m", "zyko.mcp.server"],
        input="",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


# ----------------------------------------------------------------------- router


def test_router_normalize_degenerate_inputs():
    router = Router({"fake": FakeProvider(script=["x"])})
    # no measurement / empty board -> neutral 0.5
    assert router._normalize_cost(None, [1.0, 2.0]) == 0.5
    assert router._normalize_cost(1.0, []) == 0.5
    assert router._normalize_latency(None, [1.0, 2.0]) == 0.5
    assert router._normalize_latency(1.0, []) == 0.5
    # degenerate board (all-equal prices) -> best score
    assert router._normalize_cost(2.0, [2.0, 2.0]) == 1.0
    assert router._normalize_latency(2.0, [2.0, 2.0]) == 1.0


async def test_astream_route_skips_open_breaker():
    router = Router({"fake": FakeProvider(script=["x"])}, breaker_threshold=1)
    for key in ("fake/fake-small", "fake/fake-large"):
        router.health.record(key, latency_ms=1.0, ok=False)
    with pytest.raises(ProviderError) as exc_info:
        async for _ in router.astream_route(_req()):
            pass
    assert "skipped-breaker" in str(exc_info.value)


async def test_astream_route_skips_policy_denied():
    policy = PolicyEngine({"version": 1, "name": "t", "providers": {"allow": ["ollama"]}})
    router = Router({"fake": FakeProvider(script=["x"])}, policy=policy)
    with pytest.raises(ProviderError) as exc_info:
        async for _ in router.astream_route(_req()):
            pass
    assert "skipped-policy" in str(exc_info.value)
