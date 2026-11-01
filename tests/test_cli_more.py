"""Deeper CLI coverage: chat loop, gateway serve, mcp tools, run --trace, bench."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import httpx

from tests.fakes import FakeProvider
from zyko.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "echo_server.py"


def _with_fake_router(monkeypatch):
    fake = FakeProvider(script=["chat answer"])
    monkeypatch.setattr(
        "zyko.cli.commands.configured_providers", lambda *_a, **_k: {"fake": fake}
    )
    return fake


# ------------------------------------------------------------------ chat loop
def test_chat_loop_scripted_session(monkeypatch, capsys):
    """Feed stdin lines through the interactive loop; memory records both sides."""
    fake = _with_fake_router(monkeypatch)
    lines = iter(["hello there", "/model fake/fake-large", "/session", "/new", "again", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    assert main(["chat"]) == 0
    out = capsys.readouterr().out
    assert "chat answer" in out
    assert "via fake/" in out
    assert "model → fake/fake-large" in out
    assert fake.calls >= 2  # /new + second question
    # memory persisted both user turns and both assistant answers
    from zyko.agents.memory import MemoryStore

    store = MemoryStore()
    sessions = store.list_sessions()
    assert len(sessions) == 2
    fresh = None
    for s in sessions:
        h = store.history(s["id"])
        if h and h[0].content == "again":
            fresh = h
    assert fresh is not None
    assert fresh[0].role.value == "user"
    assert fresh[1].content == "chat answer"


def test_chat_loop_survives_provider_error(monkeypatch, capsys):
    """A failing provider logs a failure line and keeps the loop alive."""
    # fail_first=2 exhausts both fake models in one route → route() raises;
    # the next turn succeeds after the outage clears.
    fake = FakeProvider(script=["second try"], fail_first=2, name="fake")
    monkeypatch.setattr(
        "zyko.cli.commands.configured_providers", lambda *_a, **_k: {"fake": fake}
    )
    lines = iter(["first question", "second question", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(lines))
    assert main(["chat"]) == 0
    out = capsys.readouterr().out
    assert "simulated outage" in out
    assert "second try" in out


# ------------------------------------------------------------- gateway serve
def test_cmd_serve_starts_and_stops(monkeypatch, capsys):
    """cmd_serve binds, prints the URL, and shuts down on Ctrl+C."""
    from zyko.gateway import server as gw

    fake = _with_fake_router(monkeypatch)
    started = {}

    class DummyServer:
        def shutdown(self):
            started["shutdown"] = True

    def fake_serve(router, host="127.0.0.1", port=8787, api_key=None):
        started["router"] = router
        started["host"] = host
        return DummyServer()

    monkeypatch.setattr(gw, "serve", fake_serve)
    monkeypatch.setattr("zyko.cli.commands.time.sleep", lambda _s: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert main(["serve", "--port", "9999"]) == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:9999/v1" in out
    assert started["router"].providers["fake"] is fake
    assert started["shutdown"] is True


def test_gateway_real_http_roundtrip():
    """Real socket test: gateway serve() + OpenAI-style POST + auth rejection."""
    from zyko.gateway.server import serve
    from zyko.router.engine import Router

    fake = FakeProvider(script=["http answer"])
    httpd = serve(Router({"fake": fake}), host="127.0.0.1", port=0, api_key="sekrit")
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}/v1/chat/completions"
        with httpx.Client(timeout=10.0) as client:
            denied = client.post(
                base, json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]}
            )
            assert denied.status_code == 401
            ok = client.post(
                base,
                headers={"Authorization": "Bearer sekrit"},
                json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            )
            assert ok.status_code == 200
            body = ok.json()
            assert body["choices"][0]["message"]["content"] == "http answer"
            assert body["zyko"]["receipt"]["chosen"].startswith("fake/")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# ------------------------------------------------------------------ mcp tools
def test_mcp_tools_lists_fixture_server(capsys):
    assert main(["mcp", "tools", "--", sys.executable, str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "echo" in out


def test_mcp_tools_requires_command(capsys):
    assert main(["mcp", "tools"]) == 1
    captured = capsys.readouterr()
    err = captured.err + captured.out
    assert "usage" in err.lower()


# ------------------------------------------------------------------- run
def test_run_agent_with_trace(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    _with_fake_router(monkeypatch)
    agent_file = tmp_path / "mini.yaml"
    agent_file.write_text(
        "name: mini\n"
        "system: answer directly\n"
        "max_steps: 3\n"
        "tools: []\n",
        encoding="utf-8",
    )
    assert main(["run", str(agent_file), "say hi", "--trace"]) == 0
    out = capsys.readouterr().out
    assert "agent 'mini'" in out
    assert "chat answer" in out
    assert "step" in out and "routed via" in out


# ------------------------------------------------------------------- bench
def test_bench_demo_runs_and_writes_json(tmp_path, capsys):
    out_path = tmp_path / "bench.json"
    assert main(["bench", "--demo", "--json-out", str(out_path)]) == 0
    payload = json.loads(out_path.read_text())
    assert payload["results"], "benchmark must produce results"
    out = capsys.readouterr().out
    assert "mock" in out.lower() or "bench" in out.lower()


# ------------------------------------------------------------------ version
def test_python_dash_m_zyko_entry():
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    proc = subprocess.run(
        [sys.executable, "-m", "zyko", "--version"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert proc.returncode == 0
    assert "zyko" in proc.stdout
