"""Reproducible quality ledger for routing.

Every score in the ledger originates from a committed, seeded benchmark run
(``zyko bench``) — never from vendor marketing tables. No data yet means the
neutral score 0.5 for everyone, and the router leans on cost/latency until
real measurements exist. This honesty is what makes ZYKO's routing
*verifiable*: any receipt can be replayed against the ledger that produced it.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from zyko.exceptions import ConfigError
from zyko.log import get_logger

log = get_logger("router.quality")

NEUTRAL_SCORE = 0.5


@dataclass
class ModelScore:
    quality: float = NEUTRAL_SCORE
    win_rate: float = NEUTRAL_SCORE
    samples: int = 0
    updated: float | None = None
    categories: dict[str, float] = field(default_factory=dict)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class QualityLedger:
    """``{provider/model: ModelScore}`` persisted as JSON."""

    SCHEMA_VERSION = 1

    def __init__(self, data: dict[str, dict] | None = None, path: Path | None = None) -> None:
        self.path = path
        self._scores: dict[str, ModelScore] = {}
        self.meta: dict = {"schema_version": self.SCHEMA_VERSION, "updated": None}
        if data:
            self._ingest(data)

    def _ingest(self, data: dict) -> None:
        self.meta = {
            "schema_version": data.get("schema_version", self.SCHEMA_VERSION),
            "updated": data.get("updated"),
        }
        for key, raw in (data.get("scores") or {}).items():
            try:
                self._scores[key] = ModelScore(
                    quality=_clamp01(raw.get("quality", NEUTRAL_SCORE)),
                    win_rate=_clamp01(raw.get("win_rate", NEUTRAL_SCORE)),
                    samples=int(raw.get("samples", 0)),
                    updated=raw.get("updated"),
                    categories={k: _clamp01(v) for k, v in (raw.get("categories") or {}).items()},
                )
            except (TypeError, ValueError) as exc:
                log.warning("ledger: skipping malformed entry %s: %s", key, exc)

    @classmethod
    def load(cls, path: Path) -> "QualityLedger":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls({}, path=path)
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"quality ledger {path} is unreadable: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"quality ledger {path} must contain a JSON object")
        return cls(raw, path=path)

    @classmethod
    def empty(cls, path: Path | None = None) -> "QualityLedger":
        return cls({}, path=path)

    # ------------------------------------------------------------------
    def score(self, provider: str, model: str) -> ModelScore:
        return self._scores.get(f"{provider}/{model}", ModelScore())

    def known_models(self) -> list[str]:
        return sorted(self._scores)

    def update(
        self,
        provider: str,
        model: str,
        *,
        quality: float,
        win_rate: float | None = None,
        samples: int = 1,
        categories: dict[str, float] | None = None,
    ) -> None:
        key = f"{provider}/{model}"
        current = self._scores.get(key, ModelScore())
        # EWMA merge so later runs adjust, not erase, earlier measurements.
        weight = min(samples, 50) / (current.samples + min(samples, 50))
        merged_quality = current.quality * (1 - weight) + _clamp01(quality) * weight
        merged_win = current.win_rate
        if win_rate is not None:
            merged_win = current.win_rate * (1 - weight) + _clamp01(win_rate) * weight
        merged_categories = dict(current.categories)
        for cat, value in (categories or {}).items():
            old = merged_categories.get(cat, _clamp01(value))
            merged_categories[cat] = old * (1 - weight) + _clamp01(value) * weight
        self._scores[key] = ModelScore(
            quality=merged_quality,
            win_rate=merged_win,
            samples=current.samples + samples,
            updated=time.time(),
            categories=merged_categories,
        )
        self.meta["updated"] = time.time()

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ConfigError("quality ledger has no output path")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "updated": self.meta.get("updated") or time.time(),
            "scores": {key: asdict(score) for key, score in sorted(self._scores.items())},
        }
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
        return target

    # ------------------------------------------------------------------
    def to_table(self) -> str:
        if not self._scores:
            return "(ledger empty — run `zyko bench` with provider keys to populate)"
        header = f"{'model':44} {'quality':>8} {'win':>6} {'samples':>8}"
        rows = [header, "-" * len(header)]
        for key, score in sorted(self._scores.items(), key=lambda kv: -kv[1].quality):
            rows.append(f"{key:44} {score.quality:8.3f} {score.win_rate:6.3f} {score.samples:8d}")
        return "\n".join(rows)
