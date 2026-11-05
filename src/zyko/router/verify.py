"""Offline verification of routing receipts.

Every routed call can emit a *receipt* — a self-contained JSON document with
the chosen candidate, the score components of every ranked candidate and the
strategy weights that combined them. A receipt is only worth something if a
third party can check it later, without ZYKO's runtime state, without network
access and without trusting the process that wrote it. That is what this
module does:

* **Arithmetic** — every ``total`` is recomputed from the weights and the
  component scores recorded next to it. A hand-edited score or weight is
  caught here.
* **Policy of the strategy** — the weights must be exactly the published
  ``STRATEGY_WEIGHTS[strategy]``; a receipt cannot invent its own weights.
* **Ledger integrity** — when the quality ledger that produced the receipt is
  supplied, each recorded quality score must match the ledger's score for
  that model, and the ledger's ``updated`` stamp must match the one the
  receipt recorded.
* **Internal consistency** — components stay inside ``[0, 1]`` and the
  ranking is sorted by descending total.

``zyko verify receipt.json`` is the CLI wrapper; this module is the reusable
core so embedders can verify receipts in their own pipelines.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.exceptions import ConfigError
from zyko.router.engine import STRATEGY_WEIGHTS
from zyko.router.quality import QualityLedger

SUPPORTED_RECEIPT_VERSIONS = frozenset({1})
# Receipts round components and totals to 4 decimals (see ScoreBreakdown.as_dict),
# so recomputing from the rounded values can drift by ~2e-4. Anything larger is
# tampering, not rounding.
DEFAULT_TOLERANCE = 5e-4

# The receipt stores at most this many ranked candidates (see Router._receipt).
RANKING_LIMIT = 10


@dataclass
class VerifyIssue:
    """One failed check. ``code`` is stable for scripts, ``message`` is for humans."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class VerifyReport:
    ok: bool
    receipt_version: int | None = None
    strategy: str | None = None
    chosen: str | None = None
    created: float | None = None
    total: float | None = None
    checks: int = 0
    issues: list[VerifyIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "receipt_version": self.receipt_version,
            "strategy": self.strategy,
            "chosen": self.chosen,
            "created": self.created,
            "total": self.total,
            "checks": self.checks,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def load_receipt(path: str | Path) -> dict[str, Any]:
    """Read a receipt file, raising ``ConfigError`` with a usable hint."""
    file = Path(path)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            f"receipt {file} does not exist",
            hint="write one with `zyko ask 'hello' --demo --receipt receipt.json`",
        ) from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"receipt {file} is not readable JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"receipt {file} must contain a JSON object")
    return raw


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _recompute_total(entry: dict[str, Any]) -> float | None:
    weights = entry.get("weights") or {}
    wq = _as_float(weights.get("quality"))
    wc = _as_float(weights.get("cost"))
    wl = _as_float(weights.get("latency"))
    quality = _as_float(entry.get("quality"))
    cost = _as_float(entry.get("cost_score"))
    latency = _as_float(entry.get("latency_score"))
    if None in (wq, wc, wl, quality, cost, latency):
        return None
    return wq * quality + wc * cost + wl * latency


def _check_components(
    label: str, entry: dict[str, Any], issues: list[VerifyIssue], tolerance: float
) -> None:
    """Arithmetic + range checks shared by the chosen block and each ranking row."""
    for key in ("quality", "cost_score", "latency_score"):
        value = _as_float(entry.get(key))
        if value is None:
            issues.append(VerifyIssue("malformed", f"{label}: missing numeric '{key}'"))
            return
        if not (0.0 - tolerance <= value <= 1.0 + tolerance):
            issues.append(
                VerifyIssue("component-out-of-range", f"{label}: {key}={value} is outside [0, 1]")
            )
    expected = _recompute_total(entry)
    if expected is None:
        issues.append(VerifyIssue("malformed", f"{label}: weights are missing or not numeric"))
        return
    recorded = _as_float(entry.get("total"))
    if recorded is None:
        issues.append(VerifyIssue("malformed", f"{label}: missing numeric 'total'"))
        return
    if abs(expected - recorded) > tolerance:
        issues.append(
            VerifyIssue(
                "total-mismatch",
                f"{label}: recorded total={recorded:.6f} but weights x components={expected:.6f}",
            )
        )


def _check_weights(
    strategy: str, entry: dict[str, Any], issues: list[VerifyIssue], tolerance: float
) -> None:
    published = STRATEGY_WEIGHTS[strategy]
    weights = entry.get("weights") or {}
    actual = (
        _as_float(weights.get("quality")),
        _as_float(weights.get("cost")),
        _as_float(weights.get("latency")),
    )
    if None in actual:
        issues.append(VerifyIssue("malformed", "score_components.weights is missing"))
        return
    for name, got, want in zip(("quality", "cost", "latency"), actual, published):
        if abs(got - want) > tolerance:  # type: ignore[operator]
            issues.append(
                VerifyIssue(
                    "weights-mismatch",
                    f"strategy '{strategy}' publishes {name} weight {want}, receipt claims {got}",
                )
            )
            return


def verify_receipt(
    receipt: dict[str, Any],
    *,
    ledger: QualityLedger | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> VerifyReport:
    """Recompute a receipt offline and report every drift found."""
    issues: list[VerifyIssue] = []
    report = VerifyReport(ok=False)

    version = receipt.get("receipt_version")
    if version not in SUPPORTED_RECEIPT_VERSIONS:
        issues.append(
            VerifyIssue(
                "unsupported-version",
                f"receipt_version={version!r} is not supported "
                f"(supported: {sorted(SUPPORTED_RECEIPT_VERSIONS)})",
            )
        )
        report.issues = issues
        report.checks = 1
        return report
    report.receipt_version = int(version)
    report.checks += 1

    strategy = receipt.get("strategy")
    if strategy not in STRATEGY_WEIGHTS:
        issues.append(VerifyIssue("unknown-strategy", f"unknown routing strategy {strategy!r}"))
        report.issues = issues
        return report
    report.strategy = strategy
    report.checks += 1

    report.chosen = receipt.get("chosen")
    report.created = _as_float(receipt.get("created"))

    components = receipt.get("score_components")
    if not isinstance(components, dict):
        issues.append(VerifyIssue("malformed", "score_components is missing or not an object"))
        report.issues = issues
        return report
    report.total = _as_float(components.get("total"))

    _check_weights(strategy, components, issues, tolerance)
    report.checks += 1
    _check_components("score_components", components, issues, tolerance)
    report.checks += 1

    ranking = receipt.get("ranking")
    if not isinstance(ranking, list) or not ranking:
        issues.append(VerifyIssue("malformed", "ranking is missing or empty"))
        report.issues = issues
        return report

    totals: list[float] = []
    for index, entry in enumerate(ranking):
        if not isinstance(entry, dict) or not entry.get("candidate"):
            issues.append(VerifyIssue("malformed", f"ranking[{index}] is not a candidate entry"))
            continue
        _check_components(f"ranking[{index}] ({entry['candidate']})", entry, issues, tolerance)
        value = _as_float(entry.get("total"))
        if value is not None:
            totals.append(value)
    report.checks += 1

    if totals != sorted(totals, reverse=True):
        issues.append(
            VerifyIssue("ranking-order", "ranking is not sorted by descending total score")
        )
    report.checks += 1

    if report.chosen and report.chosen not in {e.get("candidate") for e in ranking}:
        # The receipt keeps only the top 10 rows; a fallback may legitimately
        # pick a candidate below the cut. Only flag it when the list is complete.
        if len(ranking) < RANKING_LIMIT:
            issues.append(
                VerifyIssue(
                    "chosen-not-ranked",
                    f"chosen candidate {report.chosen!r} is absent from ranking",
                )
            )
    report.checks += 1

    if ledger is not None:
        report.checks += 1
        for entry in ranking:
            if not isinstance(entry, dict) or "/" not in str(entry.get("candidate", "")):
                continue
            provider, _, model = str(entry["candidate"]).partition("/")
            recorded = _as_float(entry.get("quality"))
            expected = ledger.score(provider, model).quality
            if recorded is not None and abs(recorded - expected) > tolerance:
                issues.append(
                    VerifyIssue(
                        "quality-drift",
                        f"{entry['candidate']}: receipt quality={recorded:.6f}, "
                        f"ledger quality={expected:.6f}",
                    )
                )
        if report.chosen and "/" in report.chosen:
            provider, _, model = report.chosen.partition("/")
            recorded = _as_float(components.get("quality"))
            expected = ledger.score(provider, model).quality
            if recorded is not None and abs(recorded - expected) > tolerance:
                issues.append(
                    VerifyIssue(
                        "quality-drift",
                        f"score_components ({report.chosen}): receipt quality={recorded:.6f}, "
                        f"ledger quality={expected:.6f}",
                    )
                )
        claimed = _as_float(receipt.get("ledger_updated"))
        actual = _as_float(ledger.meta.get("updated"))
        if claimed is not None and actual is not None and abs(claimed - actual) > tolerance:
            issues.append(
                VerifyIssue(
                    "ledger-mismatch",
                    f"receipt was produced by a ledger updated at {claimed}, "
                    f"supplied ledger updated at {actual}",
                )
            )

    report.issues = issues
    report.ok = not issues
    return report
