"""OTLP export: your spans flow to any OpenTelemetry backend — still zero deps.

The 0.4.2 bridge from the roadmap in ``docs/STRATEGY.md``: LangChain sells
observability as LangSmith; ZYKO's spans already live on your disk (0.4.1) —
now they can also flow into the observability stack your team already runs.
:class:`OtlpSink` speaks **OTLP/HTTP with JSON encoding** (the standard wire
protocol of the OpenTelemetry Collector) over ``httpx`` — which ZYKO already
requires — so an OTel Collector, Langfuse, Grafana Tempo, Jaeger, Honeycomb,
New Relic or Datadog all work with **zero new dependencies** and **zero
vendor lock-in**. One environment variable turns the bridge on::

    ZYKO_OTLP_ENDPOINT=http://localhost:4318/v1/traces

Wire format (OTLP/JSON, ``POST {endpoint}``, ``content-type: application/json``)::

    {"resourceSpans": [{"resource": {"attributes": [...]},
                        "scopeSpans": [{"scope": {...}, "spans": [...]}]}]}

Identifier mapping: OTLP demands 16-byte trace ids and 8-byte span ids, while
ZYKO spans carry shorter human-scale ids (12/8 hex chars). The sink derives
spec-length ids **deterministically** (``sha256`` of a tagged id, first N hex
chars), so the same ZYKO id always maps to the same OTLP id, parent links
survive the mapping, and the originals ride along as ``zyko.trace_id`` /
``zyko.span_id`` / ``zyko.parent_id`` attributes — drill-down with
``zyko traces --trace <id>`` stays lossless.

Design rules (all enforced by tests):

* Observability must **never** slow or break the request path: ``write()``
  only enqueues; a full queue **drops** (and counts) instead of blocking;
  endpoint failures degrade to one warning line per outage.
* A single daemon worker batches up to ``batch_size`` spans per POST, so a
  busy gateway pays one request per batch — not one per span.
* ``close()`` drains pending spans, then stops the worker; safe to call twice.

::

    from zyko.observability import OtlpSink

    sink = OtlpSink(
        "https://cloud.langfuse.com/api/public/otel/v1/traces",
        headers={"authorization": "Basic " + b64("pk:sk")},
    )
    zk = Zyko(tracer=Tracer(sinks=[JsonlSink(path), sink]))
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
from typing import Any

import httpx

from zyko.log import get_logger
from zyko.version import __version__

log = get_logger("observability.otlp")


# ------------------------------------------------------------------ id mapping
def _otlp_trace_id(zyko_id: str) -> str:
    """Deterministic 32-hex OTLP trace id derived from a ZYKO trace id."""
    return hashlib.sha256(("zyko-trace:" + zyko_id).encode()).hexdigest()[:32]


def _otlp_span_id(zyko_id: str) -> str:
    """Deterministic 16-hex OTLP span id derived from a ZYKO span id."""
    return hashlib.sha256(("zyko-span:" + zyko_id).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- OTLP encoding
def _value(v: Any) -> dict[str, Any]:
    """Map a Python value to an OTLP AnyValue (spec: 64-bit ints as strings)."""
    if v is None:
        return {}
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, dict):
        return {"kvlistValue": {"values": [_kv(str(k), x) for k, x in v.items()]}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_value(x) for x in v]}}
    return {"stringValue": str(v)}


def _kv(key: str, v: Any) -> dict[str, Any]:
    return {"key": key, "value": _value(v)}


def span_to_otlp(span: Any) -> dict[str, Any]:
    """Map a :class:`~zyko.observability.TraceSpan` to one OTLP/JSON span dict.

    Status mapping: ``ok`` → ``STATUS_CODE_OK``; ``error``/``cancelled`` →
    ``STATUS_CODE_ERROR`` with the failure reason as the status message (OTLP
    has no "cancelled" status — the honest signal plus the ``zyko.status``
    attribute tells the full story).
    """
    start_ns = int(span.started_at * 1e9)
    duration_ms = span.duration_ms if span.duration_ms is not None else 0.0
    end_ns = start_ns + int(duration_ms * 1e6)
    attrs: dict[str, Any] = dict(span.attributes)
    attrs["zyko.trace_id"] = span.trace_id
    attrs["zyko.span_id"] = span.span_id
    attrs["zyko.status"] = span.status
    if span.parent_id:
        attrs["zyko.parent_id"] = span.parent_id
    failed = span.status in {"error", "cancelled"}
    out: dict[str, Any] = {
        "traceId": _otlp_trace_id(span.trace_id),
        "spanId": _otlp_span_id(span.span_id),
        "name": span.name,
        "kind": "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": [_kv(str(k), v) for k, v in sorted(attrs.items())],
        "status": {"code": "STATUS_CODE_ERROR" if failed else "STATUS_CODE_OK"},
    }
    if failed:
        reason = attrs.get("error") or ("cancelled" if span.status == "cancelled" else "error")
        out["status"]["message"] = str(reason)
    if span.parent_id:
        out["parentSpanId"] = _otlp_span_id(span.parent_id)
    return out


def _payload(spans: list[Any], service_name: str) -> bytes:
    body = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _kv("service.name", service_name),
                        _kv("telemetry.sdk.name", "zyko"),
                        _kv("telemetry.sdk.language", "python"),
                        _kv("telemetry.sdk.version", __version__),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "zyko.observability", "version": __version__},
                        "spans": [span_to_otlp(s) for s in spans],
                    }
                ],
            }
        ]
    }
    return json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")


# ----------------------------------------------------------------------- sink
class OtlpSink:
    """Ship spans to any OTLP/HTTP-JSON endpoint — without ever blocking.

    ``write()`` enqueues and returns immediately (the caller's request path
    is never touched by network latency). One daemon worker drains the queue
    in batches of up to ``batch_size`` spans per POST. Overflow **drops**
    spans (counted in ``.dropped``) rather than slowing producers; export
    failures log one warning per outage and then stay quiet at debug level.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_s: float = 5.0,
        service_name: str = "zyko",
        batch_size: int = 64,
        queue_size: int = 4096,
    ) -> None:
        self.endpoint = endpoint
        self.headers = {"content-type": "application/json", **dict(headers or {})}
        self.timeout_s = timeout_s
        self.service_name = service_name
        self.batch_size = max(1, int(batch_size))
        self.dropped = 0
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._warned_post = False
        self._warned_drop = False
        self._worker = threading.Thread(target=self._run, name="zyko-otlp", daemon=True)
        self._worker.start()

    # ---------------------------------------------------------------- sink API
    def write(self, span: Any) -> None:
        """Enqueue one span — never blocks, never raises (drops on overflow)."""
        try:
            self._queue.put_nowait(span)
        except queue.Full:
            with self._lock:
                self.dropped += 1
                if not self._warned_drop:
                    self._warned_drop = True
                    log.warning(
                        "otlp queue full — dropping spans (%d dropped so far); "
                        "the local JSONL trace log still has everything",
                        self.dropped,
                    )

    def close(self, timeout: float = 10.0) -> None:
        """Drain pending spans, then stop the worker. Safe to call twice."""
        self._stop.set()
        self._worker.join(timeout=timeout)

    # ---------------------------------------------------------------- worker
    def _run(self) -> None:
        client = httpx.Client(timeout=self.timeout_s, headers=self.headers)
        try:
            while True:
                batch = self._drain()
                if batch is None:
                    break
                if batch:
                    self._post(client, batch)
        finally:
            client.close()

    def _drain(self) -> list[Any] | None:
        """Block for work; a batch, or ``None`` once stopped and fully drained."""
        while True:
            if self._stop.is_set() and self._queue.empty():
                return None
            try:
                first = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            batch = [first]
            while len(batch) < self.batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            return batch

    def _post(self, client: httpx.Client, batch: list[Any]) -> None:
        body = _payload(batch, self.service_name)
        try:
            resp = client.post(self.endpoint, content=body)
            if resp.status_code >= 300:
                raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001 - tracing never breaks requests
            with self._lock:
                first_failure = not self._warned_post
                self._warned_post = True
            if first_failure:
                log.warning(
                    "otlp export to %s failed (%s) — spans stay in the local JSONL trace log",
                    self.endpoint,
                    exc,
                )
            else:
                log.debug("otlp export to %s failed again: %s", self.endpoint, exc)
        else:
            with self._lock:
                self._warned_post = False  # recovered — a new outage warns again
