"""Router: scoring, ranking, fallback, breakers, receipts, ledger."""

from __future__ import annotations

import pytest

from tests.fakes import FakeProvider
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import ProviderError
from zyko.policy.engine import PolicyEngine
from zyko.router.engine import RouteCandidate, Router
from zyko.router.quality import QualityLedger


def _req(text: str = "hello", model: str | None = None) -> ChatRequest:
    return ChatRequest(messages=[Message.user(text)], model=model)


def _router(*providers, **kw) -> Router:
    return Router({p.name: p for p in providers}, **kw)


# --------------------------------------------------------------------- rank
def test_rank_prefers_cheap_under_cost_strategy():
    cheap = FakeProvider(name="cheap", input_price=0.1, output_price=0.1)
    dear = FakeProvider(name="dear", input_price=10.0, output_price=10.0)
    router = _router(cheap, dear, strategy="cost")
    ranking = router.rank()
    assert ranking[0][0].provider == "cheap"
    assert ranking[0][1].total > ranking[-1][1].total


def test_quality_strategy_uses_ledger():
    a = FakeProvider(name="a")
    b = FakeProvider(name="b")
    ledger = QualityLedger.empty()
    ledger.update("b", "fake-small", quality=0.95, samples=10)
    router = Router({"a": a, "b": b}, ledger=ledger, strategy="quality")
    top = router.rank()[0][0]
    assert top.provider == "b"


def test_explain_returns_full_ranking():
    router = _router(FakeProvider(), strategy="balanced")
    explanation = router.explain()
    assert explanation["strategy"] == "balanced"
    totals = [e["total"] for e in explanation["ranking"]]
    assert totals == sorted(totals, reverse=True)
    assert len(totals) == 2  # fake-small + fake-large


# ------------------------------------------------------------------ fallback
def _async_marker():
    pass


async def test_fallback_to_healthy_provider():
    broken = FakeProvider(name="broken", fail_first=99)
    healthy = FakeProvider(name="healthy", script=["all good"])
    router = _router(broken, healthy, strategy="cost")
    result = await router.aroute(_req())
    assert result.response.text == "all good"
    assert result.candidate.startswith("healthy/")
    outcomes = {a.candidate.split("/")[0]: a.outcome for a in result.attempts}
    assert outcomes["broken"] == "error"
    assert outcomes["healthy"] == "ok"


def _async_marker():
    pass


async def test_receipt_is_verifiable_shape():
    router = _router(FakeProvider(script=["hi"]))
    result = await router.aroute(_req())
    receipt = result.receipt
    assert receipt["receipt_version"] == 1
    assert receipt["chosen"].startswith("fake/")
    assert receipt["ranking"] and "score_components" in receipt
    assert receipt["attempts"][0]["outcome"] == "ok"
    assert "est_input_tokens" in receipt


def _async_marker():
    pass


async def test_all_candidates_failed_error_lists_attempts():
    broken = FakeProvider(name="broken", fail_first=99)
    router = _router(broken)
    with pytest.raises(ProviderError) as excinfo:
        await router.aroute(_req())
    assert "broken" in str(excinfo.value)


# ------------------------------------------------------------------- breaker
def _async_marker():
    pass


async def test_circuit_breaker_opens_and_half_opens():
    flaky = FakeProvider(name="flaky", fail_first=99)
    router = _router(flaky, breaker_threshold=2, breaker_cooldown_s=0.0)
    for _ in range(2):
        with pytest.raises(ProviderError):
            await router.aroute(_req())
    assert router.health.available("flaky/fake-small") is True  # cooldown 0 → half-open


def test_health_latency_ewma():
    from zyko.router.health import HealthTracker

    tracker = HealthTracker()
    tracker.record("x", latency_ms=100.0, ok=True)
    tracker.record("x", latency_ms=200.0, ok=True)
    assert tracker.latency("x") == pytest.approx(100 * 0.7 + 200 * 0.3)
    assert tracker.snapshot()["x"]["total_calls"] == 2


# -------------------------------------------------------------------- policy
def _async_marker():
    pass


async def test_policy_filters_candidates_and_requests():
    policy = PolicyEngine(
        {"version": 1, "name": "p", "models": {"allow": ["fake/*"], "deny": ["fake/fake-large"]}}
    )
    router = _router(FakeProvider(), policy=policy)
    keys = [c.key for c in router.candidates()]
    assert "fake/fake-small" in keys
    assert "fake/fake-large" not in keys


# -------------------------------------------------------------------- ledger
def test_ledger_roundtrip_and_neutrality(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = QualityLedger.empty(path)
    assert ledger.score("fake", "fake-small").quality == 0.5  # neutral default
    ledger.update("fake", "fake-small", quality=0.8, samples=4, categories={"math": 0.9})
    ledger.save()
    loaded = QualityLedger.load(path)
    assert loaded.score("fake", "fake-small").quality == pytest.approx(0.8)
    assert loaded.score("fake", "fake-small").categories["math"] == pytest.approx(0.9)
    assert loaded.known_models() == ["fake/fake-small"]


def test_ledger_rejects_garbage(tmp_path):
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    from zyko.exceptions import ConfigError

    with pytest.raises(ConfigError):
        QualityLedger.load(tmp_path / "bad.json")


# ----------------------------------------------------------------- candidate
def test_candidate_key_format():
    cand = RouteCandidate("openai", "gpt-4o")
    assert cand.key == "openai/gpt-4o"
