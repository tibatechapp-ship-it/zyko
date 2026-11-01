"""The `Zyko()` high-level facade: full-stack wiring with fake providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeProvider


@pytest.fixture()
def fake_router(monkeypatch):
    fake = FakeProvider(script=["facade answer"])
    monkeypatch.setattr(
        "zyko.client.configured_providers", lambda *_a, **_k: {"fake": fake}
    )
    return fake


def test_ask_returns_routed_result(fake_router, tmp_path):
    from zyko import Zyko

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    outcome = zk.ask("hello facade")
    assert outcome.response.text == "facade answer"
    assert outcome.candidate.startswith("fake/")
    assert outcome.receipt["chosen"] == outcome.candidate
    assert outcome.receipt["score_components"]["weights"]


def test_ask_model_override(fake_router, tmp_path):
    from zyko import Zyko

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    outcome = zk.ask("hello", model="fake/fake-large")
    assert outcome.candidate == "fake/fake-large"


def test_ask_with_system_prompt(fake_router, tmp_path):
    from zyko import Zyko

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    outcome = zk.ask("hello", system="You are terse.")
    messages = outcome.receipt  # receipt carries no transcript; check response only
    assert outcome.response.text == "facade answer"
    assert messages["chosen"]


def test_chat_with_explicit_messages(fake_router, tmp_path):
    from zyko import Zyko
    from zyko.core.messages import Message

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    outcome = zk.chat([Message.user("hi"), Message.assistant("hello"), Message.user("bye")])
    assert outcome.response.text == "facade answer"
    assert outcome.receipt["chosen"]


def test_ask_async_variant(fake_router, tmp_path):
    import asyncio

    from zyko import Zyko

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    outcome = asyncio.run(zk.aask("async path"))
    assert outcome.response.text == "facade answer"


def test_explain_ranking_and_note(fake_router, tmp_path):
    from zyko import Zyko

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    explanation = zk.explain()
    assert explanation["ranking"]
    assert explanation["ranking"][0]["total"] >= explanation["ranking"][-1]["total"]
    assert "receipt" in zk.receipt_schema_note


def test_agent_factory_via_facade(fake_router, tmp_path, monkeypatch):
    from zyko import Zyko

    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    agent = zk.agent("math-agent")
    assert agent.name == "math-agent"
    assert agent.builtin_tools  # calculator resolved from the repo examples dir


def test_facade_with_policy_object(fake_router, tmp_path):
    from zyko import Zyko
    from zyko.policy.engine import PolicyEngine, builtin_default_policy

    engine = PolicyEngine(builtin_default_policy())
    zk = Zyko(policy=engine, ledger_path=tmp_path / "ledger.json")
    assert zk.policy is engine
    outcome = zk.ask("governed hello")
    assert outcome.receipt["policy"]["policy"] == "default"


def test_facade_with_strategy_override(fake_router, tmp_path):
    from zyko import Zyko

    zk = Zyko(strategy="quality", ledger_path=tmp_path / "ledger.json")
    assert zk.router.strategy == "quality"
    assert zk.ask("x").receipt["strategy"] == "quality"
