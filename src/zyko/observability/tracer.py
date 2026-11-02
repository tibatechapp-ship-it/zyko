"""Built-in tracing: every routed call leaves an inspectable span.

Competitors ship observability as a paid hosted add-on (LangSmith, Langfuse,
AgentOps) or a third-party SDK wiring session. ZYKO ships the same core idea —
OpenTelemetry-style spans with trace/parent ids, durations, statuses and
attributes — as a **zero-dependency, local-first** layer: JSON lines you own,
on disk you control, inspectable with the same CLI that produced them.

Design rules (all enforced by tests):

* Tracing must **never** break the request path — sink failures are logged
  once and swallowed.
* Zero new required dependencies (stdlib ``json``/``time``/``uuid`` only).
* Parent/child linking via :class:`contextvars.ContextVar`, so wrapping a
  call in your own ``tracer.span("rag")`` automatically nests the router span
  under it — no propagation headers, no extra wiring.
* Rotation keeps the JSONL file bounded (``max_bytes`` → one ``.1`` backup),
  so a long-lived gateway cannot fill the disk with trace lines.

::

    from zyko import Zyko

    zk = Zyko()
    with zk.tracer.span("my-rag", corpus="support-docs"):
        zk.ask("why is my invoice late?")

    # later:
    #   zyko traces --last 20        human table
    #   zyko traces --json           machine feed
    #   zyko traces --trace <id>     every span of one request
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from zyko.log import get_logger

log = get_logger("observability")

_CURRENT: ContextVar["TraceSpan | None"] = ContextVar("zyko_current_span", default=None)


@dataclass
class TraceSpan:
    """One timed operation with structured attributes.

    ``trace_id`` groups all spans of a single logical request (router call,
    structured answer, user RAG wrapper). ``parent_id`` points at the span
    that was current when this one started.
    """

    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    started_at: float
    duration_ms: float | None = None
    status: str = "ok"  # "ok" | "error" | "cancelled"
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemorySink:
    """Keeps the last ``maxlen`` spans — ideal for tests and live introspection."""

    def __init__(self, maxlen: int = 256) -> None:
        self.maxlen = maxlen
        self._spans: list[TraceSpan] = []
        self._lock = threading.Lock()

    def write(self, span: TraceSpan) -> None:
        with self._lock:
            self._spans.append(span)
            if len(self._spans) > self.maxlen:
                del self._spans[: len(self._spans) - self.maxlen]

    def spans(self) -> list[TraceSpan]:
        with self._lock:
            return list(self._spans)


class JsonlSink:
    """Append one JSON object per span to a file you own.

    * parent directories are created on demand;
    * write failures never propagate — tracing degrades to a log line;
    * when the file exceeds ``max_bytes`` it rotates with a bounded shift
      (current → ``.1``, old ``.1`` → ``.2``, ``.2`` dropped), so a long-lived
      gateway never exceeds ~3×``max_bytes`` of trace data on disk.
    """

    def __init__(self, path: str | Path, max_bytes: int = 5_000_000) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._warned = False

    def write(self, span: TraceSpan) -> None:
        line = json.dumps(span.to_dict(), ensure_ascii=False, default=str)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size + len(line) > self.max_bytes:
                    # Bounded shift rotation — keep two backups, drop the third:
                    # disk stays <= ~3*max_bytes forever, newest spans stay live.
                    backup1 = self.path.with_suffix(self.path.suffix + ".1")
                    backup2 = self.path.with_suffix(self.path.suffix + ".2")
                    if backup2.exists():
                        backup2.unlink()
                    if backup1.exists():
                        backup1.replace(backup2)
                    self.path.replace(backup1)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError as exc:
            if not self._warned:
                self._warned = True
                log.warning("trace sink %s unavailable (%s) — tracing disabled", self.path, exc)


class Tracer:
    """Creates spans and fans them out to sinks.

    ``enabled=False`` turns every method into a cheap no-op while keeping the
    public surface identical, so call sites never need ``if tracer``.
    """

    def __init__(self, sinks: list[Any] | None = None, *, enabled: bool = True) -> None:
        self.sinks: list[Any] = list(sinks or [])
        self.enabled = enabled

    # ------------------------------------------------------------- context API
    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[TraceSpan]:
        """Run a block as a span; exceptions mark the span ``error`` and re-raise."""
        sp = self.start_span(name, **attributes)
        try:
            yield sp
        except BaseException as exc:  # noqa: BLE001 - status must reflect any exit
            sp.status = (
                "cancelled" if isinstance(exc, (KeyboardInterrupt, GeneratorExit)) else "error"
            )
            first = str(exc).splitlines()
            if first:
                sp.attributes.setdefault("error", first[0][:300])
            self.end_span(sp)
            raise
        else:
            self.end_span(sp)

    # ------------------------------------------------------------- manual API
    def start_span(self, name: str, **attributes: Any) -> TraceSpan:
        parent = _CURRENT.get() if self.enabled else None
        sp = TraceSpan(
            trace_id=parent.trace_id if parent else uuid.uuid4().hex[:12],
            span_id=uuid.uuid4().hex[:8],
            parent_id=parent.span_id if parent else None,
            name=name,
            started_at=time.time(),
            attributes=dict(attributes),
        )
        if self.enabled:
            # Becoming the current span is what makes *nested* start_span calls
            # (router span inside a user RAG span) inherit trace/parent ids.
            # The token is reset by end_span, so nesting must stay LIFO — the
            # same contract every OpenTelemetry-style tracer has.
            sp._ctx_token = _CURRENT.set(sp)  # noqa: SLF001 - attribute, not a private class
        return sp

    def end_span(self, sp: TraceSpan) -> None:
        sp.duration_ms = round((time.time() - sp.started_at) * 1000.0, 2)
        token = getattr(sp, "_ctx_token", None)
        if token is not None:
            _CURRENT.reset(token)
            sp._ctx_token = None
        if not self.enabled:
            return
        for sink in self.sinks:
            try:
                sink.write(sp)
            except Exception as exc:  # noqa: BLE001 - tracing never breaks requests
                log.debug("trace sink %r failed: %s", sink, exc)

    def emit(self, name: str, *, status: str = "ok", **attributes: Any) -> None:
        """One-shot span for flows without a clean bracketing block."""
        if not self.enabled:
            return
        sp = self.start_span(name, **attributes)
        sp.status = status
        self.end_span(sp)


def load_tracer(settings: Any) -> Tracer:
    """Build the process tracer from settings (``tracing.*``) + env overrides.

    Settings::

        tracing:
          enabled: true          # ZYKO_TRACING=0 to force off
          file: null             # default: <data dir>/traces.jsonl
          otlp:
            endpoint: null       # ZYKO_OTLP_ENDPOINT — any OTLP/HTTP-JSON backend
            headers: {}          # e.g. authorization for Langfuse cloud
            timeout_s: 5.0
            service_name: zyko
            batch_size: 64
            queue_size: 4096

    ``enabled=False`` yields a no-op tracer sharing the same API — callers
    never branch on it. When an OTLP endpoint is configured (settings key
    ``tracing.otlp.endpoint`` or the ``ZYKO_OTLP_ENDPOINT`` env var, which
    wins), an :class:`~zyko.observability.OtlpSink` fans the same spans out
    to the configured backend in addition to the local JSONL log.
    """
    enabled = bool(settings.get("tracing.enabled", True))
    env = os.environ.get("ZYKO_TRACING")
    if env is not None:
        enabled = env.strip().lower() not in {"0", "false", "off", "no"}
    if not enabled:
        return Tracer(enabled=False)
    path = settings.get("tracing.file") or str(_default_trace_path())
    sinks: list[Any] = [JsonlSink(path), InMemorySink()]
    endpoint = os.environ.get("ZYKO_OTLP_ENDPOINT") or settings.get("tracing.otlp.endpoint")
    if endpoint and str(endpoint).strip():
        from zyko.observability.otlp import OtlpSink

        raw_headers = settings.get("tracing.otlp.headers") or {}
        sinks.append(
            OtlpSink(
                str(endpoint).strip(),
                headers={str(k): str(v) for k, v in dict(raw_headers).items()},
                timeout_s=float(settings.get("tracing.otlp.timeout_s") or 5.0),
                service_name=str(settings.get("tracing.otlp.service_name") or "zyko"),
                batch_size=int(settings.get("tracing.otlp.batch_size") or 64),
                queue_size=int(settings.get("tracing.otlp.queue_size") or 4096),
            )
        )
    return Tracer(sinks=sinks)


def _default_trace_path() -> Path:
    from zyko.platform.paths import trace_log

    return trace_log()
