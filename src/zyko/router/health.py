"""Per-candidate health: latency EWMA + circuit breaker.

The breaker opens after N consecutive failures and half-opens after a
cooldown, so a flaky provider is skipped without being permanently
blacklisted. State is in-process by design: a phone restarting the CLI
should start with a clean slate, and gateway deployments are single-
process today (multi-process sharding is on the roadmap).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

ALPHA = 0.3  # EWMA smoothing for latency


@dataclass
class _State:
    latency_ms: float | None = None
    failures: int = 0
    opened_at: float | None = None
    total_calls: int = 0
    total_failures: int = 0


@dataclass
class HealthTracker:
    breaker_threshold: int = 3
    breaker_cooldown_s: float = 30.0
    _states: dict[str, _State] = field(default_factory=dict)

    def _state(self, key: str) -> _State:
        return self._states.setdefault(key, _State())

    def record(self, key: str, *, latency_ms: float, ok: bool) -> None:
        state = self._state(key)
        state.total_calls += 1
        if ok:
            state.failures = 0
            state.opened_at = None
            state.latency_ms = (
                latency_ms if state.latency_ms is None else state.latency_ms * (1 - ALPHA) + latency_ms * ALPHA
            )
        else:
            state.total_failures += 1
            state.failures += 1
            if state.failures >= self.breaker_threshold:
                state.opened_at = time.time()

    def available(self, key: str) -> bool:
        state = self._states.get(key)
        if state is None or state.opened_at is None:
            return True
        if time.time() - state.opened_at >= self.breaker_cooldown_s:
            state.opened_at = None  # half-open: allow one probe
            state.failures = self.breaker_threshold - 1
            return True
        return False

    def latency(self, key: str) -> float | None:
        return self._states.get(key).latency_ms if key in self._states else None

    def snapshot(self) -> dict[str, dict]:
        return {
            key: {
                "latency_ms": state.latency_ms,
                "failures": state.failures,
                "open": state.opened_at is not None,
                "total_calls": state.total_calls,
                "total_failures": state.total_failures,
            }
            for key, state in self._states.items()
        }
