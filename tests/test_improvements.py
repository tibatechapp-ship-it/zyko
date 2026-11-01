"""Review-hardening tests: demo mode, router snapshot parity, policy
schema warnings, prompt-aware route planning, usage-based bench cost."""

from __future__ import annotations

import json

import pytest
import yaml

from tests.fakes import FakeProvider
from zyko import kernel
from zyko.cli import main
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.policy.engine import PolicyEngine
from zyko.providers.mock import MockProvider, demo_enabled
from zyko.router.engine import DEFAULT_EST_IN, DEFAULT_EST_OUT, Router


# ------------------------------------------------------------------- mock
@pytest.mark.asyncio
async def test_mock_provider_deterministic_and_offline():
    provider = MockProvider()
    request = ChatRequest(messages=[Message.user("hello world")])
    first = await provider.acomplete(request)
    second = await provider.acomplete(request)
    assert first.text == second.text
    assert "hello world"[:20] in first.text
    assert first.provider == "mock"
    assert first.usage.input_tokens > 0
    events = [event async for event in provider.astream(request)]
    kinds = [e.type for e in events]
    assert kinds[0] == "text" and kinds[-1] == "done"


@pytest.mark.asyncio
async def test_mock_provider_forced_tool_call():
    provider = MockProvider()
    request = ChatRequest(
        messages=[Message.user("do it")],
        metadata={"force_tool": "search", "tool_args": {"q": "zyko"}},
    )
    response = await provider.acomplete(request)
    assert response.tool_calls and response.tool_calls[0].name == "search"
    assert response.tool_calls[0].arguments == {"q": "zyko"}


def test_demo_enabled_env_and_config(monkeypatch):
    monkeypatch.delenv("ZYKO_DEMO", raising=False)
    assert demo_enabled() is False

    class _S:
        def get(self, _k, default=None):
            return True

    assert demo_enabled(_S()) is True
    monkeypatch.setenv("ZYKO_DEMO", "1")
    assert demo_enabled() is True


# ------------------------------------------------------- demo CLI (keyless)
def test_cli_ask_demo_works_without_keys(capsys, monkeypatch):
    monkeypatch.delenv("ZYKO_DEMO", raising=False)
    assert main(["ask", "hello ZYKO", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "[zyko-mock/" in out


def test_cli_route_demo_and_prompt_aware_tokens(capsys, monkeypatch):
    monkeypatch.delenv("ZYKO_DEMO", raising=False)
    prompt = "estimate tokens for this prompt " * 12
    assert main(["route", prompt, "--demo", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["est_input_tokens"] == max(kernel.estimate_tokens(prompt), 1)
    assert any(e["candidate"].startswith("mock/") for e in payload["ranking"])


def test_cli_route_demo_table(capsys, monkeypatch):
    monkeypatch.delenv("ZYKO_DEMO", raising=False)
    assert main(["route", "plan me", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "routing plan" in out and "mock/mock-mini" in out


def test_cli_bench_demo_json_report(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ZYKO_DEMO", raising=False)
    out_path = tmp_path / "bench.json"
    assert (
        main(["bench", "--demo", "--json-out", str(out_path), "--ledger", str(tmp_path / "l.json")])
        == 0
    )
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["seed"] == 42 and report["suite_hash"]
    mock_result = report["results"][0]
    assert mock_result["candidate"] == "mock/mock-mini"
    assert mock_result["token_usage"]["input"] > 0
    assert len(mock_result["tasks"]) == 24


# ------------------------------------------------- router snapshot parity
def test_rank_matches_score_candidate_exactly():
    cheap = FakeProvider(name="cheap", input_price=0.1, output_price=0.1)
    dear = FakeProvider(name="dear", input_price=10.0, output_price=10.0)
    router = Router({"cheap": cheap, "dear": dear}, strategy="balanced")
    for cand, breakdown in router.rank():
        solo = router.score_candidate(
            cand, est_input_tokens=DEFAULT_EST_IN, est_output_tokens=DEFAULT_EST_OUT
        )
        assert breakdown.total == pytest.approx(solo.total)


def test_rank_is_stable_across_calls():
    a = FakeProvider(name="a", input_price=1.0, output_price=2.0)
    b = FakeProvider(name="b", input_price=0.5, output_price=1.0)
    router = Router({"a": a, "b": b}, strategy="cost")
    first = [c.key for c, _ in router.rank()]
    second = [c.key for c, _ in router.rank()]
    assert first == second
    # b's small model is cheapest, then a's small, then the large pair.
    assert first == ["b/fake-small", "a/fake-small", "b/fake-large", "a/fake-large"]


# ------------------------------------------------- policy schema warnings
def test_policy_warns_on_unknown_keys():
    engine = PolicyEngine(
        {
            "version": 1,
            "name": "typo",
            "privcy": {"redact": ["email"]},  # typo'd top-level key
            "defaults": {"budget_per_day": 5.0},  # typo'd defaults key
        }
    )
    assert any("privcy" in w for w in engine.warnings)
    assert any("budget_per_day" in w for w in engine.warnings)
    assert "warnings" in engine.snapshot()


def test_policy_no_warnings_for_clean_doc():
    engine = PolicyEngine(
        {
            "version": 1,
            "name": "clean",
            "defaults": {"budget_usd_per_day": 5.0},
            "privacy": {"redact": ["email"]},
        }
    )
    assert engine.warnings == []


def test_cli_policy_check_prints_warnings(tmp_path, capsys):
    path = tmp_path / "typo.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "name": "typo-check",
                "modelz": {"allow": ["*"]},
            }
        ),
        encoding="utf-8",
    )
    assert main(["policy", "check", str(path)]) == 0
    out = capsys.readouterr().out
    assert "modelz" in out and "warning" in out


# -------------------------------------------------- mcp honors governance
def test_mcp_router_honors_demo_and_policy(monkeypatch):
    import asyncio

    from zyko.mcp.server import ZykoMCPServer

    monkeypatch.setenv("ZYKO_DEMO", "1")
    server = ZykoMCPServer()
    router = server._ensure_router()
    assert "mock" in router.providers

    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "zyko_chat", "arguments": {"prompt": "hi"}},
            }
        )
    )
    assert response["result"]["isError"] is False
    assert "[zyko-mock/" in response["result"]["content"][0]["text"]
