"""Explicit model pinning: `--model provider/name` must actually pin the route."""

from __future__ import annotations

import pytest

from tests.fakes import FakeProvider
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import ProviderError
from zyko.router.engine import Router


def _router() -> Router:
    return Router({"fake": FakeProvider()})


def _req(model: str | None = None) -> ChatRequest:
    return ChatRequest(messages=[Message.user("hi")], model=model)


def test_model_pin_routes_to_requested_model():
    router = _router()
    import asyncio

    outcome = asyncio.run(router.aroute(_req("fake/fake-large")))
    assert outcome.candidate == "fake/fake-large"
    assert outcome.response.model == "fake-large"
    assert outcome.receipt["requested_model"] == "fake/fake-large"


def test_model_pin_bare_name_matches_any_provider():
    router = _router()
    pool = router.candidates_for(_req("fake-large"))
    assert [c.key for c in pool] == ["fake/fake-large"]


def test_model_pin_provider_wildcard():
    router = _router()
    pool = router.candidates_for(_req("fake/*"))
    assert {c.key for c in pool} == {"fake/fake-small", "fake/fake-large"}


def test_auto_and_empty_rank_everything():
    router = _router()
    assert len(router.candidates_for(_req("auto"))) == 2
    assert len(router.candidates_for(_req(None))) == 2


def test_unknown_pin_fails_with_hint():
    router = _router()
    with pytest.raises(ProviderError) as excinfo:
        router.candidates_for(_req("fake/does-not-exist"))
    assert "not available" in str(excinfo.value)
    assert "zyko models" in str(excinfo.value)


def test_unknown_provider_pin_fails():
    router = _router()
    with pytest.raises(ProviderError):
        router.candidates_for(_req("anthropic/*"))


def test_pin_with_policy_still_applies():
    from zyko.policy.engine import PolicyEngine

    doc = {
        "name": "pin-policy",
        "models": {"allow": ["fake/fake-small"]},
    }
    router = Router({"fake": FakeProvider()}, policy=PolicyEngine(doc))
    pool = router.candidates_for(_req("fake/*"))
    assert [c.key for c in pool] == ["fake/fake-small"]


def test_pinned_fallback_stays_within_pin():
    """When a pinned model fails, fallback cannot silently escape the pin."""

    import asyncio

    provider = FakeProvider(fail_first=2)  # both fake models fail
    router = Router({"fake": provider})
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(router.aroute(_req("fake/fake-large")))
    assert "all routing candidates failed" in str(excinfo.value)
    # every attempt stayed on the pinned model
    assert "fake/fake-large" in str(excinfo.value)
    assert "fake/fake-small" not in str(excinfo.value)
