"""Policy-as-Code engine: redaction, allowlists, budget, rate limit, tools."""

from __future__ import annotations

import pytest

from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import BudgetExceededError, ConfigError, LocalRateLimitError
from zyko.policy.engine import PolicyEngine, Redactor, builtin_default_policy, load_policy
from zyko.router.engine import RouteCandidate


def _request(text: str = "hello", max_tokens: int | None = None) -> ChatRequest:
    return ChatRequest(messages=[Message.user(text)], max_tokens=max_tokens)


def _cand(provider: str = "fake", model: str = "fake-small") -> RouteCandidate:
    return RouteCandidate(provider, model)


# ------------------------------------------------------------------ redaction
def test_redactor_builtin_patterns():
    red = Redactor.from_doc({"redact": ["email", "ssn"]})
    text, applied = red.apply("contact a@b.com or 123-45-6789 today")
    assert "[EMAIL]" in text and "[SSN]" in text
    assert set(applied) == {"email", "ssn"}


def test_redactor_credit_card_luhn():
    red = Redactor.from_doc({"redact": ["credit_card"]})
    out, _ = red.apply("card 4111 1111 1111 1111 ok")  # valid Luhn
    assert "[CREDIT_CARD]" in out
    out2, _ = red.apply("on 2024-10-09 and 12345 in 2023")  # not a card
    assert "2024-10-09" in out2


def test_redactor_custom_regex():
    red = Redactor.from_doc({"custom": [{"pattern": "SECRET-[A-Z0-9]+", "replace": "[TOK]"}]})
    out, applied = red.apply("token SECRET-AB12 leaked")
    assert "[TOK]" in out and applied == ["custom"]


# ------------------------------------------------------------------- models
def test_model_allow_and_deny():
    engine = PolicyEngine(
        {"version": 1, "name": "t", "models": {"allow": ["fake/*"], "deny": ["fake/fake-large"]}}
    )
    assert engine.allows_model("fake", "fake-small") is True
    assert engine.allows_model("fake", "fake-large") is False
    assert engine.allows_model("openai", "gpt-4o") is False


def test_provider_allowlist():
    engine = PolicyEngine({"version": 1, "name": "t", "providers": {"allow": ["ollama"]}})
    assert engine.allows_provider("ollama") is True
    assert engine.allows_provider("openai") is False


def test_tool_rules_and_danger_gate():
    engine = PolicyEngine({"version": 1, "name": "t", "tools": {"allow": ["*"], "deny": ["shell"]}})
    assert engine.allows_tool("calculator") is True
    assert engine.allows_tool("shell") is False
    assert engine.explicitly_allows_tool("shell") is False  # wildcard never unlocks danger tools
    strict = PolicyEngine({"version": 1, "name": "t", "tools": {"allow": ["shell", "calculator"]}})
    assert strict.explicitly_allows_tool("shell") is True


# ------------------------------------------------------------------- budget
def test_budget_exhaustion(tmp_path):
    engine = PolicyEngine(
        {"version": 1, "name": "t", "defaults": {"budget_usd_per_day": 1.0}},
        state_dir=tmp_path,
    )
    engine.budget.add(1.0)
    with pytest.raises(BudgetExceededError):
        engine.check_request(_request(), _cand())


def test_budget_tracking(tmp_path):
    engine = PolicyEngine(
        {"version": 1, "name": "t", "defaults": {"budget_usd_per_day": 5.0}},
        state_dir=tmp_path,
    )
    engine.record_cost(0.25, _cand())
    assert engine.budget.spent_today() == pytest.approx(0.25)
    assert engine.budget.remaining() == pytest.approx(4.75)
    assert engine.snapshot()["budget_remaining_usd"] == pytest.approx(4.75)


# --------------------------------------------------------------- rate limit
def test_local_rate_limit(tmp_path):
    engine = PolicyEngine(
        {"version": 1, "name": "t", "rate_limit": {"requests_per_minute": 2}},
        state_dir=tmp_path,
    )
    engine.check_request(_request(), _cand())
    engine.check_request(_request(), _cand())
    with pytest.raises(LocalRateLimitError):
        engine.check_request(_request(), _cand())


# ---------------------------------------------------------------- max tokens
def test_max_tokens_cap(tmp_path):
    engine = PolicyEngine(
        {"version": 1, "name": "t", "defaults": {"max_tokens_per_request": 10}},
        state_dir=tmp_path,
    )
    decision = engine.check_request(_request(max_tokens=500), _cand())
    assert decision.allowed is True
    assert decision.request.max_tokens == 10


def test_redaction_in_check_request(tmp_path):
    engine = PolicyEngine(
        {"version": 1, "name": "t", "privacy": {"redact": ["email"]}},
        state_dir=tmp_path,
    )
    decision = engine.check_request(_request("write to a@b.com now"), _cand())
    assert decision.allowed is True
    assert "[EMAIL]" in decision.request.messages[0].content
    assert "a@b.com" not in decision.request.messages[0].content


def test_deny_decision_reason(tmp_path):
    engine = PolicyEngine(
        {"version": 1, "name": "t", "models": {"allow": ["fake/*"], "deny": ["fake/fake-large"]}},
        state_dir=tmp_path,
    )
    decision = engine.check_request(_request(), _cand(model="fake-large"))
    assert decision.allowed is False
    assert "fake-large" in decision.reason


# ------------------------------------------------------------------- loading
def test_load_policy_from_file(tmp_path):
    import yaml

    doc = {"version": 1, "name": "mine", "defaults": {"budget_usd_per_day": 2.0}}
    path = tmp_path / "mine.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    engine = load_policy(str(path))
    assert engine.name == "mine"
    assert engine.budget.cap == 2.0


def test_load_policy_missing(tmp_path):
    with pytest.raises(ConfigError):
        load_policy(str(tmp_path / "nope.yaml"))


def test_builtin_default_policy_shape():
    engine = PolicyEngine(builtin_default_policy())
    assert engine.name == "default"
    assert engine.snapshot()["policy"] == "default"


def test_unknown_schema_version():
    with pytest.raises(ConfigError):
        PolicyEngine({"version": 99})
