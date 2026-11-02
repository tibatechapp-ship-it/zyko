"""Built-in tracing (v0.4.1): spans, sinks, rotation, router+CLI integration.

Contract highlights under test:
* tracing never breaks the request path (sink I/O failures are swallowed);
* parent/child linking via ContextVar (user span wraps router span);
* JsonlSink writes valid JSON lines, rotates at max_bytes, degrades quietly;
* ZYKO_TRACING=0 / settings disable it while keeping the same API;
* router emits `router.route` (ask) and `router.stream` (streaming) spans with
  provider/usage/attempts/cached attributes and error status on failure;
* `zyko traces` reads the log — table, --json machine contract, --trace drill,
  --clear; missing file yields valid JSON under --json (cost/cache contract).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.fakes import FakeProvider
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.observability import InMemorySink, JsonlSink, Tracer, TraceSpan
from zyko.observability.tracer import load_tracer
from zyko.router.engine import Router


def _req(text: str = "hello", **kw) -> ChatRequest:
    return ChatRequest(messages=[Message.user(text)], **kw)


# ------------------------------------------------------------------ unit: spans
def test_span_records_duration_and_attributes():
    mem = InMemorySink()
    t = Tracer(sinks=[mem])
    with t.span("job", kind="test") as sp:
        sp.attributes["extra"] = 1
    out = mem.spans()
    assert len(out) == 1
    s = out[0]
    assert s.name == "job" and s.status == "ok"
    assert s.duration_ms is not None and s.duration_ms >= 0
    assert s.attributes == {"kind": "test", "extra": 1}
    assert s.trace_id and s.span_id and s.parent_id is None


def test_nested_spans_share_trace_and_parent_link():
    mem = InMemorySink()
    t = Tracer(sinks=[mem])
    with t.span("outer"):
        with t.span("inner"):
            pass
    # spans are appended at *end*, so the inner span lands first
    inner, outer = mem.spans()
    assert outer.parent_id is None
    assert inner.parent_id == outer.span_id
    assert inner.trace_id == outer.trace_id


def test_span_marks_error_and_reraises():
    mem = InMemorySink()
    t = Tracer(sinks=[mem])
    with pytest.raises(ValueError, match="boom"):
        with t.span("failing"):
            raise ValueError("boom")
    s = mem.spans()[0]
    assert s.status == "error"
    assert "boom" in s.attributes["error"]


def test_disabled_tracer_is_a_noop_with_same_api():
    t = Tracer(enabled=False)
    with t.span("nothing"):
        pass
    t.emit("also-nothing")
    assert t.sinks == []  # nothing written, nothing raised


def test_emit_writes_one_shot_span():
    mem = InMemorySink()
    Tracer(sinks=[mem]).emit("cache.hit", cached=True)
    s = mem.spans()[0]
    assert s.name == "cache.hit" and s.status == "ok" and s.attributes == {"cached": True}


# ------------------------------------------------------------------ unit: sinks
def test_jsonl_sink_writes_valid_json_and_creates_dirs(tmp_path: Path):
    path = tmp_path / "deep" / "nested" / "traces.jsonl"
    sink = JsonlSink(path)
    t = Tracer(sinks=[sink])
    with t.span("a", provider="fake/fake-small"):
        pass
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["name"] == "a" and obj["attributes"]["provider"] == "fake/fake-small"
    assert obj["status"] == "ok" and obj["duration_ms"] is not None


def test_jsonl_sink_rotates_at_max_bytes(tmp_path: Path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path, max_bytes=300)
    t = Tracer(sinks=[sink])
    for i in range(8):
        with t.span("wide", filler="x" * 80, i=i):
            pass
    live = path.read_text().splitlines()
    b1 = path.with_suffix(path.suffix + ".1")
    b2 = path.with_suffix(path.suffix + ".2")
    # bounded shift rotation: live + at most two backups, nothing newer lost
    assert b1.exists() and b2.exists()
    kept = len(live) + len(b1.read_text().splitlines()) + len(b2.read_text().splitlines())
    assert 3 <= kept <= 8
    assert json.loads(live[-1])["attributes"]["i"] == 7  # newest span always live
    total_disk = path.stat().st_size + b1.stat().st_size + b2.stat().st_size
    assert total_disk <= 3 * 300 + 200  # bounded forever, with line-length slack


def test_jsonl_sink_swallows_io_failure_and_keeps_requests_alive(tmp_path: Path):
    # a directory where a file must go: open() raises IsADirectoryError (OSError)
    bad = tmp_path / "traces.jsonl"
    bad.mkdir()
    sink = JsonlSink(bad)
    t = Tracer(sinks=[sink])
    with t.span("still-works"):
        pass  # must not raise


def test_corrupt_jsonl_lines_are_skipped_by_reader(tmp_path: Path):
    path = tmp_path / "traces.jsonl"
    good = {
        "trace_id": "t1",
        "span_id": "s1",
        "parent_id": None,
        "name": "ok",
        "started_at": 1.0,
        "duration_ms": 2.0,
        "status": "ok",
        "attributes": {},
    }
    path.write_text(json.dumps(good) + "\n{ torn line\n", encoding="utf-8")
    spans = _read_spans(path)
    assert [s.name for s in spans] == ["ok"]


def _read_spans(path: Path) -> list[TraceSpan]:
    spans = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            spans.append(TraceSpan(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return spans


# ------------------------------------------------------------------ settings
def test_load_tracer_defaults_to_data_dir(tmp_path: Path, monkeypatch):
    from zyko.config.settings import Settings

    s = Settings.load()
    t = load_tracer(s)
    assert t.enabled and len(t.sinks) == 2
    assert isinstance(t.sinks[0], JsonlSink)


def test_load_tracer_respects_enabled_setting(tmp_path: Path, monkeypatch):
    from zyko.config.settings import Settings

    monkeypatch.setenv("ZYKO_TRACING", "0")
    t = load_tracer(Settings.load())
    assert not t.enabled
    with t.span("off"):
        pass  # no sinks, no writes, no error


def test_load_tracer_env_off_beats_setting(tmp_path: Path, monkeypatch):
    from zyko.config.settings import Settings

    monkeypatch.setenv("ZYKO_TRACING", "false")
    t = load_tracer(Settings.load())
    assert not t.enabled


# ------------------------------------------------------------------ router
def _router(tracer, providers=None) -> Router:
    provs = providers or {"fake": FakeProvider()}
    return Router(provs, tracer=tracer)


def test_router_success_span_carries_provider_usage_attempts():
    mem = InMemorySink()
    r = _router(Tracer(sinks=[mem]))
    result = asyncio.run(r.aroute(_req("hi")))
    spans = mem.spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "router.route" and s.status == "ok"
    assert s.attributes["provider"] == result.candidate == "fake/fake-small"
    assert s.attributes["cached"] is False
    assert s.attributes["input_tokens"] == 20 and s.attributes["output_tokens"] == 10
    assert s.attributes["attempts"][0]["outcome"] == "ok"


def test_router_failure_span_is_error_and_reraises():
    mem = InMemorySink()
    r = _router(Tracer(sinks=[mem]), providers={"fake": FakeProvider(fail_first=99)})
    with pytest.raises(Exception):
        asyncio.run(r.aroute(_req("hi")))
    s = mem.spans()[0]
    assert s.name == "router.route" and s.status == "error"
    assert s.attributes.get("error")  # failure reason recorded, request never masked


def test_router_cache_hit_recorded_in_span():
    from zyko.cache import ResponseCache

    mem = InMemorySink()
    cache = ResponseCache()
    r = Router({"fake": FakeProvider()}, cache=cache, tracer=Tracer(sinks=[mem]))
    asyncio.run(r.aroute(_req("hi")))
    asyncio.run(r.aroute(_req("hi")))
    statuses = [s.attributes["cached"] for s in mem.spans()]
    assert statuses == [False, True]


def test_router_without_tracer_still_works():
    r = _router(None)
    result = asyncio.run(r.aroute(_req("hi")))
    assert result.response is not None


def test_stream_route_emits_span_even_when_abandoned():
    mem = InMemorySink()
    r = _router(Tracer(sinks=[mem]))

    async def consume_one():
        gen = r.astream_route(_req("hi"))
        await gen.__anext__()  # first event only, then abandon
        await gen.aclose()  # GeneratorExit inside the generator

    asyncio.run(consume_one())
    spans = mem.spans()
    assert len(spans) == 1 and spans[0].name == "router.stream"
    assert spans[0].duration_ms is not None


def test_stream_route_error_span():
    mem = InMemorySink()
    r = _router(Tracer(sinks=[mem]), providers={"fake": FakeProvider(fail_first=99)})

    async def drain():
        async for _ in r.astream_route(_req("hi")):
            pass

    with pytest.raises(Exception):
        asyncio.run(drain())
    s = mem.spans()[0]
    assert s.status == "error" and s.attributes["error"]


def test_user_span_wraps_router_span_automatically():
    mem = InMemorySink()
    r = _router(Tracer(sinks=[mem]))
    t = r.tracer

    async def flow():
        with t.span("my-rag", corpus="docs"):
            await r.aroute(_req("hi"))

    asyncio.run(flow())
    # router span ends (and is written) first; the user span wraps it
    inner, outer = mem.spans()
    assert outer.name == "my-rag"
    assert inner.name == "router.route"
    assert inner.parent_id == outer.span_id
    assert inner.trace_id == outer.trace_id


# ------------------------------------------------------------------ end-to-end: Zyko
def test_zyko_client_traces_file_default(tmp_path: Path, monkeypatch):
    from zyko.client import Zyko
    from zyko.platform.paths import trace_log

    zk = Zyko(providers={"fake": FakeProvider()})
    zk.ask("hi")
    path = trace_log()
    assert path.is_file()
    spans = _read_spans(path)
    assert any(s.name == "router.route" and s.attributes.get("provider") for s in spans)


def test_zyko_tracing_disabled_leaves_no_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZYKO_TRACING", "0")
    from zyko.client import Zyko
    from zyko.platform.paths import trace_log

    zk = Zyko(providers={"fake": FakeProvider()})
    zk.ask("hi")
    assert not trace_log().is_file()


def test_structured_answer_is_traced(tmp_path: Path):
    from zyko.client import Zyko
    from zyko.platform.paths import trace_log

    zk = Zyko(providers={"fake": FakeProvider(script=['{"n": 42}'])})
    zk.structured(
        "give 42",
        schema={"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
    )
    spans = _read_spans(trace_log())
    assert any(s.name == "router.route" and s.status == "ok" for s in spans)


# ------------------------------------------------------------------ CLI
def _args(**kw):
    class A:
        pass

    a = A()
    a.last = 20
    a.trace = None
    a.file = None
    a.clear = False
    a.json = False
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_cli_traces_missing_file_json_contract(tmp_path: Path, capsys):
    from zyko.cli.commands import cmd_traces

    rc = cmd_traces(_args(json=True, file=str(tmp_path / "none.jsonl")))
    out = capsys.readouterr().out
    assert rc == 0
    parsed = json.loads(out)
    assert parsed["spans"] == [] and parsed["traces"] == []


def test_cli_traces_table_and_drilldown(tmp_path: Path, capsys):
    from zyko.cli.commands import cmd_traces

    path = tmp_path / "traces.jsonl"
    t = Tracer(sinks=[JsonlSink(path)])
    with t.span("router.route", provider="fake/fake-small"):
        pass
    rc = cmd_traces(_args(file=str(path), last=10))
    out = capsys.readouterr().out
    assert rc == 0 and "router.route" in out

    capsys.readouterr()
    rc = cmd_traces(_args(json=True, file=str(path), trace="nope"))
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["spans"] == []


def test_cli_traces_clear(tmp_path: Path, capsys):
    from zyko.cli.commands import cmd_traces

    path = tmp_path / "traces.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    rc = cmd_traces(_args(file=str(path), clear=True))
    assert rc == 0 and not path.exists()
