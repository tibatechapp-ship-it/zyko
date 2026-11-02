"""OtlpSink (v0.4.2): the OTLP/HTTP-JSON bridge and its never-breaks contract.

Contract highlights under test:
* wire format: resource/scope/span structure, spec-length ids derived
  deterministically from the short ZYKO ids, originals preserved as
  ``zyko.*`` attributes, OTLP/JSON int64-as-string timing values;
* status mapping: ok → STATUS_CODE_OK, error/cancelled → STATUS_CODE_ERROR
  with the reason as status message;
* attribute value typing: str/int/float/bool/list/dict/None round-trips;
* end-to-end POST against a real local HTTP server (127.0.0.1 only);
* batch cap, queue overflow drops (counted, never raises), endpoint failures
  degrade to a warning while the request path keeps flowing;
* close() drains pending spans and is safe to call twice;
* load_tracer wires the sink from settings and ZYKO_OTLP_ENDPOINT env.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from zyko.config.settings import DEFAULTS, Settings
from zyko.observability import InMemorySink, OtlpSink, Tracer, TraceSpan
from zyko.observability.otlp import _otlp_span_id, _otlp_trace_id, span_to_otlp
from zyko.observability.tracer import load_tracer


def _span(**kw) -> TraceSpan:
    base = dict(
        trace_id="abc123def456",
        span_id="span0001",
        parent_id=None,
        name="router.route",
        started_at=time.time(),
        duration_ms=12.5,
        status="ok",
        attributes={"provider": "openai"},
    )
    base.update(kw)
    return TraceSpan(**base)


# ------------------------------------------------------------------ OTLP server
class _Collector(BaseHTTPRequestHandler):
    """Minimal OTLP receiver: records requests, replies 200."""

    server_version = "zyko-test-collector/1.0"

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length)
        self.server.requests.append(  # type: ignore[attr-defined]
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        self.send_response(200)
        self.send_header("content-length", "0")
        self.end_headers()

    def log_message(self, *args):  # silence per-request stderr noise
        return


@pytest.fixture()
def collector():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Collector)
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _bodies(server) -> list[dict]:
    return [json.loads(r["body"]) for r in server.requests]


# --------------------------------------------------------------- unit: encoding
def test_otlp_ids_are_spec_length_and_deterministic():
    tr = _otlp_trace_id("abc123def456")
    sp = _otlp_span_id("span0001")
    assert len(tr) == 32 and len(sp) == 16
    assert all(c in "0123456789abcdef" for c in tr + sp)
    assert tr == _otlp_trace_id("abc123def456")
    assert sp == _otlp_span_id("span0001")
    # different inputs never collapse onto one id
    assert _otlp_span_id("a") != _otlp_span_id("b")


def test_span_to_otlp_maps_ids_parent_and_timing():
    sp = _span(parent_id="parent42")
    out = span_to_otlp(sp)
    assert out["traceId"] == _otlp_trace_id("abc123def456")
    assert out["spanId"] == _otlp_span_id("span0001")
    assert out["parentSpanId"] == _otlp_span_id("parent42")
    assert len(out["startTimeUnixNano"]) >= 18 and out["startTimeUnixNano"].isdigit()
    assert int(out["endTimeUnixNano"]) > int(out["startTimeUnixNano"])
    # originals preserved for drill-down joins with `zyko traces`
    attrs = {a["key"]: a["value"] for a in out["attributes"]}
    assert attrs["zyko.trace_id"]["stringValue"] == "abc123def456"
    assert attrs["zyko.span_id"]["stringValue"] == "span0001"
    assert attrs["zyko.parent_id"]["stringValue"] == "parent42"
    assert attrs["zyko.status"]["stringValue"] == "ok"
    assert out["status"]["code"] == "STATUS_CODE_OK"
    assert "message" not in out["status"]


def test_span_to_otlp_status_error_and_cancelled():
    err = span_to_otlp(_span(status="error", attributes={"error": "boom"}))
    assert err["status"]["code"] == "STATUS_CODE_ERROR"
    assert err["status"]["message"] == "boom"
    cancelled = span_to_otlp(_span(status="cancelled"))
    assert cancelled["status"]["code"] == "STATUS_CODE_ERROR"
    assert cancelled["status"]["message"] == "cancelled"


def test_span_to_otlp_attribute_typing():
    sp = _span(
        attributes={
            "s": "text",
            "i": 7,
            "f": 1.5,
            "b": True,
            "none": None,
            "list": ["a", 2],
            "dict": {"k": "v"},
        }
    )
    attrs = {a["key"]: a["value"] for a in span_to_otlp(sp)["attributes"]}
    assert attrs["s"] == {"stringValue": "text"}
    assert attrs["i"] == {"intValue": "7"}  # OTLP/JSON: 64-bit ints as strings
    assert attrs["f"] == {"doubleValue": 1.5}
    assert attrs["b"] == {"boolValue": True}
    assert attrs["none"] == {}
    assert attrs["list"] == {"arrayValue": {"values": [{"stringValue": "a"}, {"intValue": "2"}]}}
    assert attrs["dict"] == {
        "kvlistValue": {"values": [{"key": "k", "value": {"stringValue": "v"}}]}
    }


# ------------------------------------------------------------------- end-to-end
def test_sink_posts_spec_payload_to_local_collector(collector):
    sink = OtlpSink(
        f"http://127.0.0.1:{collector.server_address[1]}/v1/traces", service_name="zyko-test"
    )
    with Tracer(sinks=[sink]).span("outer") as outer:
        outer.attributes["stage"] = "test"
        with Tracer(sinks=[sink]).span("inner"):
            pass  # separate Tracer instance, same sink — _CURRENT contextvar still nests it
    sink.close(timeout=10)
    sink.close()  # double close is safe
    assert len(collector.requests) == 1  # batched into one POST
    req = collector.requests[0]
    assert req["path"] == "/v1/traces"
    assert req["headers"].get("content-type") == "application/json"
    body = json.loads(req["body"])
    rs = body["resourceSpans"][0]
    resource = {a["key"]: a["value"] for a in rs["resource"]["attributes"]}
    assert resource["service.name"]["stringValue"] == "zyko-test"
    scope = rs["scopeSpans"][0]["scope"]
    assert scope["name"] == "zyko.observability"
    spans = rs["scopeSpans"][0]["spans"]
    assert [s["name"] for s in spans] == ["inner", "outer"]  # ended first, lands first
    # parent link survives the id mapping (inner nested under outer via contextvar)
    assert spans[0]["parentSpanId"] == spans[1]["spanId"]


def test_batch_size_caps_spans_per_post(collector):
    sink = OtlpSink(f"http://127.0.0.1:{collector.server_address[1]}/v1/traces", batch_size=2)
    for i in range(5):
        sink.write(_span(span_id=f"s{i}"))
    sink.close(timeout=15)
    sizes = [
        len(json.loads(r["body"])["resourceSpans"][0]["scopeSpans"][0]["spans"])
        for r in collector.requests
    ]
    assert sizes == [2, 2, 1]


def test_close_drains_pending_spans(collector):
    sink = OtlpSink(f"http://127.0.0.1:{collector.server_address[1]}/v1/traces")
    sink.write(_span(span_id="drain-me"))
    sink.close(timeout=10)  # close() joins the worker *after* it posts the batch
    assert len(collector.requests) == 1


def test_queue_overflow_drops_and_never_raises(collector):
    class Slow(_Collector):
        def do_POST(self):  # make the endpoint the bottleneck
            time.sleep(0.25)
            super().do_POST()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    server.requests = []  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sink = OtlpSink(
            f"http://127.0.0.1:{server.server_address[1]}/v1/traces",
            batch_size=1,
            queue_size=2,
            timeout_s=5.0,
        )
        for i in range(30):
            sink.write(_span(span_id=f"d{i}"))  # must never raise
        sink.close(timeout=15)
        assert sink.dropped > 0
        delivered = sum(
            len(json.loads(r["body"])["resourceSpans"][0]["scopeSpans"][0]["spans"])
            for r in server.requests
        )
        assert delivered + sink.dropped == 30
    finally:
        server.shutdown()
        server.server_close()


def test_endpoint_failure_never_breaks_the_request_path():
    sink = OtlpSink("http://127.0.0.1:1/v1/traces", timeout_s=0.2)  # nothing listens there
    tracer = Tracer(sinks=[sink, InMemorySink()])
    with tracer.span("must-still-work", token="x") as sp:
        pass
    assert sp.status == "ok" and sp.duration_ms is not None
    sink.close(timeout=5)


# ---------------------------------------------------------------- integration
def test_load_tracer_wires_otlp_from_settings(monkeypatch):
    settings = Settings({"tracing": {"otlp": {"endpoint": "http://collector.internal/v1/traces"}}})
    tracer = load_tracer(settings)
    otlp = [s for s in tracer.sinks if isinstance(s, OtlpSink)]
    assert len(otlp) == 1 and otlp[0].endpoint == "http://collector.internal/v1/traces"


def test_load_tracer_env_endpoint_wins(monkeypatch):
    monkeypatch.setenv("ZYKO_OTLP_ENDPOINT", "  http://env-endpoint/v1/traces  ")
    tracer = load_tracer(Settings({}))
    otlp = [s for s in tracer.sinks if isinstance(s, OtlpSink)]
    assert len(otlp) == 1 and otlp[0].endpoint == "http://env-endpoint/v1/traces"
    for s in tracer.sinks:
        if isinstance(s, OtlpSink):
            s.close(timeout=2)


def test_load_tracer_without_otlp_has_no_sink(monkeypatch):
    monkeypatch.delenv("ZYKO_OTLP_ENDPOINT", raising=False)
    tracer = load_tracer(Settings({}))
    assert not any(isinstance(s, OtlpSink) for s in tracer.sinks)


def test_defaults_carry_otlp_section():
    assert DEFAULTS["tracing"]["otlp"]["endpoint"] is None
    assert DEFAULTS["tracing"]["otlp"]["batch_size"] == 64
