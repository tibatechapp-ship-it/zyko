"""The ZYKO routing engine.

Four pillars live here:

1. **Verifiable routing** — every decision is scored from explicit components
   (quality, cost, latency) with published weights, and every route produces
   a *receipt*: a self-contained JSON document ranking all candidates with
   their score breakdowns. ``zyko route --explain`` shows it; tests replay it.
2. **Policy-aware** — candidates and requests pass through the Policy-as-Code
   engine before any vendor call is made.
3. **Resilient** — automatic fallback down the ranked list with circuit
   breakers and latency EWMA per candidate.
4. **Honest quality** — quality scores come only from the reproducible
   benchmark ledger, never from vendor claims.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from zyko import kernel
from zyko.core.events import StreamEvent, done_event
from zyko.core.response import ChatRequest, ChatResponse
from zyko.exceptions import ProviderError
from zyko.log import get_logger
from zyko.policy.engine import PolicyEngine
from zyko.providers.base import BaseProvider
from zyko.router.health import HealthTracker
from zyko.router.quality import QualityLedger
from zyko.version import __version__

log = get_logger("router")

# strategy -> (quality, cost, latency) weights
STRATEGY_WEIGHTS: dict[str, tuple[float, float, float]] = {
    "quality": (1.0, 0.0, 0.0),
    "cost": (0.2, 1.0, 0.0),
    "latency": (0.2, 0.0, 1.0),
    "balanced": (0.5, 0.25, 0.25),
}

DEFAULT_EST_IN = 800
DEFAULT_EST_OUT = 400


@dataclass
class RouteCandidate:
    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass
class ScoreBreakdown:
    quality: float
    cost_score: float
    latency_score: float
    total: float
    weights: tuple[float, float, float]
    estimated_cost_usd: float | None
    measured_latency_ms: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "quality": round(self.quality, 4),
            "cost_score": round(self.cost_score, 4),
            "latency_score": round(self.latency_score, 4),
            "total": round(self.total, 4),
            "weights": {"quality": self.weights[0], "cost": self.weights[1], "latency": self.weights[2]},
            "estimated_cost_usd": None if self.estimated_cost_usd is None else round(self.estimated_cost_usd, 8),
            "measured_latency_ms": None if self.measured_latency_ms is None else round(self.measured_latency_ms, 1),
        }


@dataclass
class RouteAttempt:
    candidate: str
    outcome: str  # "ok" | "error" | "skipped-breaker" | "skipped-policy"
    detail: str = ""
    latency_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "outcome": self.outcome,
            "detail": self.detail,
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class RouteResult:
    response: ChatResponse | None
    candidate: str | None
    attempts: list[RouteAttempt] = field(default_factory=list)
    receipt: dict[str, Any] = field(default_factory=dict)


class Router:
    """Rank, verify, execute — with policy and fallback built in."""

    def __init__(
        self,
        providers: dict[str, BaseProvider],
        *,
        ledger: QualityLedger | None = None,
        policy: PolicyEngine | None = None,
        strategy: str = "balanced",
        max_fallbacks: int = 3,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
    ) -> None:
        if not providers:
            raise ProviderError(
                "no providers configured",
                hint="export at least one provider API key (e.g. OPENAI_API_KEY), "
                "or run Ollama locally for a keyless setup",
            )
        if strategy not in STRATEGY_WEIGHTS:
            raise ProviderError(
                f"unknown routing strategy '{strategy}'",
                hint=f"choose one of: {', '.join(STRATEGY_WEIGHTS)}",
            )
        self.providers = providers
        self.ledger = ledger or QualityLedger.empty()
        self.policy = policy
        self.strategy = strategy
        self.max_fallbacks = max_fallbacks
        self.health = HealthTracker(breaker_threshold, breaker_cooldown_s)

    # ------------------------------------------------------------- scoring
    def candidates(self) -> list[RouteCandidate]:
        out: list[RouteCandidate] = []
        for provider_name, provider in sorted(self.providers.items()):
            for info in provider.catalog():
                if self.policy and not self.policy.allows_model(provider_name, info.id):
                    continue
                out.append(RouteCandidate(provider_name, info.id))
        return out

    def _board_snapshot(self) -> tuple[list[float], list[float]]:
        """Candidate price/latency ranges, computed once per scoring pass.

        Normalisation ranges depend on the whole candidate board, so they are
        collected a single time instead of once per candidate — this keeps
        ``rank()`` O(n) instead of O(n²), which matters on phones (Termux)
        where routing overhead is part of the latency budget.
        """
        cands = self.candidates()
        prices = [
            c
            for c in (
                self._cost_of(other, DEFAULT_EST_IN, DEFAULT_EST_OUT)
                for other in cands
            )
            if c is not None
        ]
        latencies = [
            value
            for value in (self.health.latency(other.key) for other in cands)
            if value is not None
        ]
        return prices, latencies

    def score_candidate(
        self,
        candidate: RouteCandidate,
        *,
        est_input_tokens: int = DEFAULT_EST_IN,
        est_output_tokens: int = DEFAULT_EST_OUT,
        snapshot: tuple[list[float], list[float]] | None = None,
    ) -> ScoreBreakdown:
        provider = self.providers[candidate.provider]
        info = provider.find_model(candidate.model)
        mscore = self.ledger.score(candidate.provider, candidate.model)

        est_cost: float | None = None
        if info is not None:
            est_cost = info.cost_usd(est_input_tokens, est_output_tokens)
        prices, latencies = snapshot if snapshot is not None else self._board_snapshot()
        cost_score = self._normalize_cost(est_cost, prices)

        measured = self.health.latency(candidate.key)
        latency_score = self._normalize_latency(measured, latencies)

        wq, wc, wl = STRATEGY_WEIGHTS[self.strategy]
        total = wq * mscore.quality + wc * cost_score + wl * latency_score
        return ScoreBreakdown(
            quality=mscore.quality,
            cost_score=cost_score,
            latency_score=latency_score,
            total=total,
            weights=(wq, wc, wl),
            estimated_cost_usd=est_cost,
            measured_latency_ms=measured,
        )

    def _cost_of(self, candidate: RouteCandidate, est_in: int, est_out: int) -> float | None:
        info = self.providers[candidate.provider].find_model(candidate.model)
        return info.cost_usd(est_in, est_out) if info else None

    def _normalize_cost(self, est_cost: float | None, prices: list[float]) -> float:
        """Cheapest candidate on the board → 1.0, priciest → ~0.0."""
        if est_cost is None or not prices:
            return 0.5
        lo, hi = min(prices), max(prices)
        if hi <= lo:
            return 1.0
        return max(0.0, (hi - est_cost) / (hi - lo))

    def _normalize_latency(self, measured: float | None, latencies: list[float]) -> float:
        if measured is None or not latencies:
            return 0.5
        lo, hi = min(latencies), max(latencies)
        if hi <= lo:
            return 1.0
        return max(0.0, (hi - measured) / (hi - lo))

    def rank(
        self,
        *,
        est_input_tokens: int = DEFAULT_EST_IN,
        est_output_tokens: int = DEFAULT_EST_OUT,
    ) -> list[tuple[RouteCandidate, ScoreBreakdown]]:
        snapshot = self._board_snapshot()
        ranked = [
            (
                cand,
                self.score_candidate(
                    cand,
                    est_input_tokens=est_input_tokens,
                    est_output_tokens=est_output_tokens,
                    snapshot=snapshot,
                ),
            )
            for cand in self.candidates()
        ]
        ranked.sort(key=lambda pair: pair[1].total, reverse=True)
        return ranked

    def explain(
        self,
        *,
        est_input_tokens: int = DEFAULT_EST_IN,
        est_output_tokens: int = DEFAULT_EST_OUT,
    ) -> dict[str, Any]:
        ranking = [
            {"candidate": cand.key, **breakdown.as_dict()}
            for cand, breakdown in self.rank(
                est_input_tokens=est_input_tokens, est_output_tokens=est_output_tokens
            )
        ]
        return {
            "strategy": self.strategy,
            "ledger_backend": self.ledger.path.name if self.ledger.path else None,
            "est_input_tokens": est_input_tokens,
            "est_output_tokens": est_output_tokens,
            "ranking": ranking,
        }

    # ------------------------------------------------------------ execution
    async def aroute(self, request: ChatRequest) -> RouteResult:
        est_in = max(kernel.messages_tokens(request.messages), 1)
        est_out = request.max_tokens or DEFAULT_EST_OUT
        ranking = self.rank(est_input_tokens=est_in, est_output_tokens=est_out)
        attempts: list[RouteAttempt] = []

        for candidate, breakdown in ranking[: max(1, self.max_fallbacks)]:
            if not self.health.available(candidate.key):
                attempts.append(RouteAttempt(candidate.key, "skipped-breaker", "circuit open"))
                continue

            if self.policy:
                decision = self.policy.check_request(request, candidate)
                if not decision.allowed:
                    attempts.append(RouteAttempt(candidate.key, "skipped-policy", decision.reason))
                    continue
                request = decision.request

            provider = self.providers[candidate.provider]
            started = time.perf_counter()
            try:
                response = await provider.acomplete(request.with_model(candidate.model))
                latency = (time.perf_counter() - started) * 1000.0
                self.health.record(candidate.key, latency_ms=latency, ok=True)
                if self.policy:
                    info = provider.find_model(candidate.model)
                    cost = response.usage.cost_usd(info)
                    self.policy.record_cost(cost, candidate)
                attempts.append(RouteAttempt(candidate.key, "ok", latency_ms=latency))
                receipt = self._receipt(request, candidate, breakdown, attempts, ranking, est_in, est_out)
                receipt["usage"] = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }
                return RouteResult(response, candidate.key, attempts, receipt)
            except ProviderError as exc:
                latency = (time.perf_counter() - started) * 1000.0
                self.health.record(candidate.key, latency_ms=latency, ok=False)
                attempts.append(RouteAttempt(candidate.key, "error", str(exc).splitlines()[0][:200], latency))
                log.warning("route %s failed: %s", candidate.key, exc)

        raise _all_failed(attempts)

    async def astream_route(
        self, request: ChatRequest
    ) -> AsyncIterator[StreamEvent]:
        """Streaming route: falls back only *before* the first token arrives."""
        est_in = max(kernel.messages_tokens(request.messages), 1)
        est_out = request.max_tokens or DEFAULT_EST_OUT
        ranking = self.rank(est_input_tokens=est_in, est_output_tokens=est_out)
        attempts: list[RouteAttempt] = []

        for candidate, breakdown in ranking[: max(1, self.max_fallbacks)]:
            if not self.health.available(candidate.key):
                attempts.append(RouteAttempt(candidate.key, "skipped-breaker", "circuit open"))
                continue
            if self.policy:
                decision = self.policy.check_request(request, candidate)
                if not decision.allowed:
                    attempts.append(RouteAttempt(candidate.key, "skipped-policy", decision.reason))
                    continue
                request = decision.request

            provider = self.providers[candidate.provider]
            started = time.perf_counter()
            emitted = False
            try:
                async for event in provider.astream(request.with_model(candidate.model)):
                    if not emitted:
                        latency = (time.perf_counter() - started) * 1000.0
                        self.health.record(candidate.key, latency_ms=latency, ok=True)
                        if self.policy:
                            self.policy.record_stream_open(candidate)
                        attempts.append(RouteAttempt(candidate.key, "ok", latency_ms=latency))
                        emitted = True
                        yield StreamEvent(
                            "meta",
                            {"candidate": candidate.key, "receipt": self._receipt(
                                request, candidate, breakdown, attempts, ranking, est_in, est_out
                            )},
                        )
                    yield event
                if not emitted:
                    raise ProviderError(f"{candidate.key}: empty stream", provider=candidate.provider)
                yield done_event()
                return
            except ProviderError as exc:
                latency = (time.perf_counter() - started) * 1000.0
                if not emitted:
                    self.health.record(candidate.key, latency_ms=latency, ok=False)
                    attempts.append(RouteAttempt(candidate.key, "error", str(exc).splitlines()[0][:200], latency))
                    log.warning("stream route %s failed pre-token: %s", candidate.key, exc)
                    continue
                self.health.record(candidate.key, latency_ms=latency, ok=False)
                raise

        raise _all_failed(attempts)

    # -------------------------------------------------------------- receipt
    def _receipt(
        self,
        request: ChatRequest,
        chosen: RouteCandidate,
        breakdown: ScoreBreakdown,
        attempts: list[RouteAttempt],
        ranking: list[tuple[RouteCandidate, ScoreBreakdown]],
        est_in: int,
        est_out: int,
    ) -> dict[str, Any]:
        return {
            "receipt_version": 1,
            "zyko_version": __version__,
            "created": time.time(),
            "strategy": self.strategy,
            "chosen": chosen.key,
            "est_input_tokens": est_in,
            "est_output_tokens": est_out,
            "score_components": breakdown.as_dict(),
            "ranking": [
                {"candidate": cand.key, **bd.as_dict()} for cand, bd in ranking[:10]
            ],
            "attempts": [a.as_dict() for a in attempts],
            "policy": self.policy.snapshot() if self.policy else None,
            "ledger_updated": self.ledger.meta.get("updated"),
        }

    # ------------------------------------------------------------- helpers
    def route(self, request: ChatRequest) -> RouteResult:
        from zyko.utils.loop import run_sync

        return run_sync(self.aroute(request))

    def stream_route(self, request: ChatRequest) -> Any:
        from zyko.utils.loop import SHARED_LOOP

        return SHARED_LOOP.iterate(self.astream_route(request))


def _all_failed(attempts: list[RouteAttempt]) -> ProviderError:
    details = "; ".join(f"{a.candidate}: {a.outcome} {a.detail}".strip() for a in attempts)
    return ProviderError(
        f"all routing candidates failed ({details})",
        hint="run `zyko doctor` to check keys/connectivity, or add Ollama as a local fallback",
    )
