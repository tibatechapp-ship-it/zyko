"""Response cache: keys, TTL, LRU, policy gating, router integration, CLI."""

from __future__ import annotations

import threading

import pytest

from tests.fakes import FakeProvider
from zyko.cache import ResponseCache
from zyko.core.messages import Message, ToolCall
from zyko.core.response import ChatRequest, ChatResponse, Usage
from zyko.policy.engine import PolicyEngine
from zyko.router.engine import Router


def _req(text: str = "hello", **kw) -> ChatRequest:
    return ChatRequest(messages=[Message.user(text)], **kw)


def _resp(
    text: str = "hi there", provider: str = "fake", model: str = "fake-small"
) -> ChatResponse:
    return ChatResponse(id="r1", provider=provider, model=model, content=text, usage=Usage(20, 10))


# ------------------------------------------------------------------ unit: keys
def test_key_is_stable_and_sensitive():
    a = ResponseCache.key_for(_req("hello"), provider="fake", model="fake-small")
    b = ResponseCache.key_for(_req("hello"), provider="fake", model="fake-small")
    assert a == b and len(a) == 64

    assert a != ResponseCache.key_for(_req("hello"), provider="fake", model="fake-large")
    assert a != ResponseCache.key_for(_req("hello"), provider="other", model="fake-small")
    assert a != ResponseCache.key_for(
        _req("hello", temperature=0.7), provider="fake", model="fake-small"
    )
    assert a != ResponseCache.key_for(
        _req("hello", max_tokens=99), provider="fake", model="fake-small"
    )
    assert a != ResponseCache.key_for(_req("hello there"), provider="fake", model="fake-small")
    # system prompts and role order are part of the outbound payload
    with_system = ChatRequest(messages=[Message.system("be terse"), Message.user("hello")])
    assert a != ResponseCache.key_for(with_system, provider="fake", model="fake-small")


def test_cache_mode_from_metadata():
    assert ResponseCache.cache_mode(_req()) == "read/write"
    assert ResponseCache.cache_mode(_req(metadata={"cache": "bypass"})) == "bypass"
    assert ResponseCache.cache_mode(_req(metadata={"cache": "refresh"})) == "refresh"
    assert ResponseCache.cache_mode(_req(metadata={"cache": "FORCE"})) == "refresh"
    assert ResponseCache.cache_mode(_req(metadata={})) == "read/write"


# ------------------------------------------------------------------ unit: store
def test_roundtrip_and_stats():
    cache = ResponseCache()
    key = ResponseCache.key_for(_req(), provider="fake", model="fake-small")
    assert cache.get(key) is None
    cache.set(key, _resp())
    assert cache.get(key).text == "hi there"
    snap = cache.snapshot()
    assert snap["hits"] == 1 and snap["misses"] == 1 and snap["stores"] == 1
    assert snap["entries"] == 1 and snap["hit_rate"] == 0.5
    assert cache.size() == 1


def test_ttl_expiry(monkeypatch):
    import time as _time

    with pytest.raises(ValueError):
        ResponseCache(ttl_s=0)
    with pytest.raises(ValueError):
        ResponseCache(max_entries=0)
    cache = ResponseCache(ttl_s=0.05)
    key = ResponseCache.key_for(_req(), provider="fake", model="fake-small")
    cache.set(key, _resp())
    assert cache.get(key) is not None
    _time.sleep(0.08)
    assert cache.get(key) is None
    snap = cache.snapshot()
    assert snap["expiries"] == 1 and snap["entries"] == 0


def test_lru_eviction():
    cache = ResponseCache(max_entries=2)
    keys = [
        ResponseCache.key_for(_req(text=t), provider="fake", model="fake-small")
        for t in ("one", "two", "three")
    ]
    for i, key in enumerate(keys):
        cache.set(key, _resp(text=f"answer-{i}"))
    assert cache.size() == 2
    assert cache.get(keys[0]) is None  # evicted (oldest)
    assert cache.get(keys[2]).text == "answer-2"
    assert cache.snapshot()["evictions"] == 1


def test_lru_touch_protects_recent_entries():
    cache = ResponseCache(max_entries=2)
    k1 = ResponseCache.key_for(_req("a"), provider="fake", model="fake-small")
    k2 = ResponseCache.key_for(_req("b"), provider="fake", model="fake-small")
    k3 = ResponseCache.key_for(_req("c"), provider="fake", model="fake-small")
    cache.set(k1, _resp("1"))
    cache.set(k2, _resp("2"))
    assert cache.get(k1) is not None  # touch k1 → k2 becomes the LRU victim
    cache.set(k3, _resp("3"))
    assert cache.get(k1).text == "1"
    assert cache.get(k2) is None


def test_clear_and_thread_safety():
    cache = ResponseCache(max_entries=1000)

    def worker(n: int) -> None:
        for i in range(50):
            key = ResponseCache.key_for(
                ChatRequest(messages=[Message.user(f"x{i % 10}")]), provider="fake", model="m"
            )
            cache.set(key, _resp(f"v{i}"))
            cache.get(key)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cache.size() <= cache.max_entries
    assert cache.clear() >= 0
    assert cache.size() == 0


# ------------------------------------------------------------- policy gating
def test_policy_without_cache_section_has_no_cache():
    engine = PolicyEngine({"version": 1, "name": "p"})
    assert engine.cache is None
    assert engine.snapshot()["cache"] is None


def test_policy_cache_section_builds_cache_and_warns_on_typos():
    engine = PolicyEngine(
        {
            "version": 1,
            "name": "p",
            "cache": {"enabled": True, "ttl_s": 60, "max_entries": 8, "tll_s": 5},
        }
    )
    assert engine.cache is not None
    assert engine.cache.ttl_s == 60
    assert engine.cache.max_entries == 8
    assert any("cache.tll_s" in w for w in engine.warnings)
    snap = engine.snapshot()
    assert snap["cache"]["enabled"] is True and snap["cache"]["max_entries"] == 8


def test_policy_invalid_cache_values_raise_configerror():
    from zyko.exceptions import ConfigError

    with pytest.raises(ConfigError):
        PolicyEngine({"version": 1, "name": "p", "cache": {"enabled": True, "ttl_s": 0}})
    with pytest.raises(ConfigError):
        PolicyEngine({"version": 1, "name": "p", "cache": {"enabled": True, "max_entries": -1}})


def test_policy_malformed_cache_section_degrades_to_warning():
    engine = PolicyEngine({"version": 1, "name": "p", "cache": "yes-please"})
    assert engine.cache is None
    assert "'cache' must be a mapping" in engine.warnings


# --------------------------------------------------------- router integration
def _router(*providers, **kw) -> Router:
    return Router({p.name: p for p in providers}, **kw)


async def test_router_cache_hit_second_call():
    provider = FakeProvider(name="fake", script=["first answer", "second answer"])
    cache = ResponseCache()
    router = _router(provider, cache=cache)
    request = _req("hello")

    first = await router.aroute(request)
    assert first.response.text == "first answer"
    assert first.receipt["cached"] is False
    assert provider.calls == 1

    second = await router.aroute(request)
    assert second.response.text == "first answer"  # served from cache
    assert second.receipt["cached"] is True
    assert second.attempts[-1].outcome == "cache-hit"
    assert provider.calls == 1  # vendor never billed again
    assert cache.snapshot()["hits"] == 1


async def test_router_without_cache_calls_provider_every_time():
    provider = FakeProvider(name="fake", script=["a", "b"])
    router = _router(provider)
    await router.aroute(_req("hello"))
    await router.aroute(_req("hello"))
    assert provider.calls == 2


async def test_router_cache_bypass_and_refresh_metadata():
    provider = FakeProvider(name="fake", script=["a", "b", "c"])
    router = _router(provider, cache=ResponseCache())

    await router.aroute(_req("hello"))
    bypassed = await router.aroute(_req("hello", metadata={"cache": "bypass"}))
    assert bypassed.response.text == "b" and provider.calls == 2
    assert bypassed.receipt["cached"] is False

    refreshed = await router.aroute(_req("hello", metadata={"cache": "refresh"}))
    assert refreshed.response.text == "c" and provider.calls == 3
    assert refreshed.receipt["cached"] is False

    # the refresh revalidated the entry: the next plain call is a cache hit on "c"
    again = await router.aroute(_req("hello"))
    assert again.response.text == "c" and provider.calls == 3
    assert again.receipt["cached"] is True


async def test_router_tool_call_responses_not_cached():
    provider = FakeProvider(
        name="fake",
        script=[
            {"content": None, "tool_calls": [ToolCall(id="call_1", name="math", arguments={})]},
            {"content": None, "tool_calls": [ToolCall(id="call_2", name="math", arguments={})]},
        ],
    )
    router = _router(provider, cache=ResponseCache())
    await router.aroute(_req("hello"))
    await router.aroute(_req("hello"))
    assert provider.calls == 2  # never stored, never replayed


async def test_router_cache_respects_policy_redaction_in_key():
    """A redacted request and its plaintext twin must not collide... unless the
    policy rewrote BOTH into the same outbound payload — then they legitimately
    share one entry (the vendor only ever saw the redacted text)."""
    policy_doc = {
        "version": 1,
        "name": "p",
        "privacy": {"redact": ["email"]},
        "cache": {"enabled": True, "ttl_s": 60},
    }
    policy = PolicyEngine(policy_doc)
    provider = FakeProvider(name="fake", script=["only one vendor call"])
    router = _router(provider, policy=policy, cache=policy.cache)

    first = await router.aroute(_req("contact me at bob@example.com please"))
    second = await router.aroute(_req("contact me at bob@example.com please"))
    assert provider.calls == 1
    assert first.receipt["cached"] is False and second.receipt["cached"] is True
    # audit trail shows exactly one allow + zero extra vendor usage
    assert policy.stats["requests_allowed"] == 2


async def test_router_cache_survives_provider_failover_position():
    """Cache is per-candidate: a hit for the ranked-first candidate must not
    shadow a different candidate's entry."""
    cheap = FakeProvider(name="cheap", input_price=0.1, output_price=0.1, script=["cheap"])
    dear = FakeProvider(name="dear", input_price=10.0, output_price=10.0, script=["dear"])
    cache = ResponseCache()
    router = Router({"cheap": cheap, "dear": dear}, strategy="cost", cache=cache)
    await router.aroute(_req("hello"))  # cheap wins and caches "cheap"
    forced = await router.aroute(_req("hello", model="dear/fake-small"))
    assert forced.response.text == "dear"  # different key → real vendor call
    assert cheap.calls == 1 and dear.calls == 1


async def test_streaming_bypasses_cache():
    provider = FakeProvider(name="fake", script=["a", "b"])
    router = _router(provider, cache=ResponseCache())
    request = _req("hello")
    await router.aroute(request)  # populates the cache
    events = [ev async for ev in router.astream_route(request)]
    assert any(ev.type == "text" for ev in events)
    assert provider.calls == 2  # stream never read from the cache


# ---------------------------------------------------------------------- CLI
def test_cli_cache_disabled_hint(capsys):
    from zyko.cli import main

    assert main(["cache", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "cache is disabled" in out
    assert "enabled: true" in out  # actionable hint


def test_cli_cache_json_and_clear(capsys, tmp_path):
    from zyko.cli import main

    policy_file = tmp_path / "cachy.yaml"
    policy_file.write_text(
        "version: 1\nname: cachy\ncache:\n  enabled: true\n  ttl_s: 60\n  max_entries: 4\n",
        encoding="utf-8",
    )
    assert main(["cache", "--demo", "--policy", str(policy_file), "--json"]) == 0
    snap = __import__("json").loads(capsys.readouterr().out)
    assert snap["enabled"] is True and snap["max_entries"] == 4 and snap["entries"] == 0

    assert main(["cache", "--demo", "--policy", str(policy_file), "--clear"]) == 0
    assert "cleared" in capsys.readouterr().out
