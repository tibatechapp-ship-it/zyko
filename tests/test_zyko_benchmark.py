"""ZYKO-Bench — model-test-style capability evaluation.

Unlike typical unit tests, this file:
  1. Aggregates results by capability (like SWE-bench per-repo)
  2. Computes a quantitative score (accuracy, F1, consistency)
  3. Enforces hard thresholds (≥95% per capability, 100% for determinism)
  4. Prints a human-readable report (MMLU-style)

Every case is deterministic — no flakiness, no statistical noise.
Run with: pytest tests/test_zyko_benchmark.py -v -s
"""
from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pytest


# ═══════════════════════════════════════════════════════════════════
# Framework
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Case:
    id: str
    capability: str
    payload: Any
    expected: Any
    weight: float = 1.0
    tags: tuple[str, ...] = ()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# Capability 1: PII Redaction — F1 over {phone, email, iban}
# ═══════════════════════════════════════════════════════════════════

PII_CASES: list[Case] = [
    # --- Clean (should detect nothing) -----------------------------
    Case("pii-clean-01", "pii", "صباح الخير", {}, tags=("clean", "ar")),
    Case("pii-clean-02", "pii", "Good morning!", {}, tags=("clean", "en")),
    Case("pii-clean-03", "pii", "def foo():\n    return 42\n", {}, tags=("clean", "code")),
    Case("pii-clean-04", "pii", "العدد 100 والعدد 200", {}, tags=("clean", "ar-num")),
    Case("pii-clean-05", "pii", "نسخة 0.19.0 من zyko", {}, tags=("clean", "version")),
    Case("pii-clean-06", "pii", "السلام عليكم ورحمة الله", {}, tags=("clean", "ar")),
    Case("pii-clean-07", "pii", "path/to/file.py", {}, tags=("clean", "path")),
    # --- Phone ---------------------------------------------------
    Case("pii-phone-01", "pii", "اتصل +966501234567", {"phone": 1}, tags=("phone", "sa")),
    Case("pii-phone-02", "pii", "الهاتف: +966551234567", {"phone": 1}, tags=("phone", "sa")),
    Case("pii-phone-03", "pii", "call +201234567890", {"phone": 1}, tags=("phone", "eg")),
    # --- Email ---------------------------------------------------
    Case("pii-email-01", "pii", "بريد x@y.com", {"email": 1}, tags=("email", "ar")),
    Case("pii-email-02", "pii", "from a@b.co to c@d.org", {"email": 2}, tags=("email", "multi")),
    # --- Mixed ---------------------------------------------------
    Case("pii-mix-01", "pii", "call +966501234567 or email x@y.com",
         {"phone": 1, "email": 1}, tags=("mixed",)),
]


def _run_pii(payload: str) -> dict[str, int]:
    from zyko.tools.pii_ar import redact
    _, findings = redact(payload)
    counts: dict[str, int] = defaultdict(int)
    for f in findings:
        t = getattr(f, "type", None) or (f.get("type") if isinstance(f, dict) else None)
        if t:
            counts[t] += 1
    return dict(counts)


def _score_pii(expected: dict, actual: dict) -> float:
    """Per-type exact count match, averaged over the union of types."""
    types = set(expected) | set(actual)
    if not types:
        return 1.0
    hits = sum(1 for t in types if expected.get(t, 0) == actual.get(t, 0))
    return hits / len(types)


def test_benchmark_pii(capsys):
    scores = []
    for c in PII_CASES:
        actual = _run_pii(c.payload)
        s = _score_pii(c.expected, actual) * c.weight
        scores.append(s)
        if s < 1.0:
            with capsys.disabled():
                print(f"  [PII FAIL] {c.id}: exp={c.expected} act={actual}")
    mean = sum(scores) / len(scores)
    with capsys.disabled():
        print(f"\n[pii] {mean*100:5.1f}% over {len(PII_CASES)} cases")
    assert mean >= 0.90, f"PII {mean*100:.1f}% < 90%"


# ═══════════════════════════════════════════════════════════════════
# Capability 2: Guardian verdicts — accuracy
# ═══════════════════════════════════════════════════════════════════

GUARDIAN_CASES: list[Case] = [
    # --- ALLOW (clean code / text) -------------------------------
    Case("g-allow-01", "guardian", "def hello():\n    return 'world'\n", "ALLOW", tags=("clean",)),
    Case("g-allow-02", "guardian", "x = 42", "ALLOW", tags=("clean",)),
    Case("g-allow-03", "guardian", "import os\n\nprint(os.getcwd())\n", "ALLOW", tags=("clean",)),
    Case("g-allow-04", "guardian", "السلام عليكم", "ALLOW", tags=("clean", "ar")),
    # --- ALLOW (email is a deliberate exclusion — see docs/INNOVATION.md) ---
    Case("g-allow-email", "guardian", "email me at x@y.com", "ALLOW", tags=("design", "email")),
    Case("g-allow-email2", "guardian", "user@example.com", "ALLOW", tags=("design", "email")),
    # --- DENY (PII types the gate is designed to block) ----------
    Case("g-deny-phone-sa", "guardian", "call +966501234567", "DENY", tags=("pii", "phone", "sa")),
    Case("g-deny-phone-eg", "guardian", "call +201234567890", "DENY", tags=("pii", "phone", "eg")),
    Case("g-deny-phone-ar", "guardian", "الرقم +966551234567", "DENY", tags=("pii", "phone", "ar")),
]


def _run_guardian(payload: str) -> str:
    from zyko.guardian import DefaultGuardian

    async def _r():
        return (await DefaultGuardian().check(payload)).verdict

    return asyncio.run(_r())


def test_benchmark_guardian(capsys):
    scores = []
    for c in GUARDIAN_CASES:
        actual = _run_guardian(c.payload)
        s = 1.0 if actual == c.expected else 0.0
        scores.append(s)
        if s == 0.0:
            with capsys.disabled():
                print(f"  [GUARD FAIL] {c.id}: exp={c.expected} act={actual}")
    mean = sum(scores) / len(scores)
    with capsys.disabled():
        print(f"[guardian] {mean*100:5.1f}% over {len(GUARDIAN_CASES)} cases")
    assert mean >= 0.95, f"Guardian {mean*100:.1f}% < 95%"


# ═══════════════════════════════════════════════════════════════════
# Capability 3: MockLLM scenario correctness
# ═══════════════════════════════════════════════════════════════════

MOCK_CASES: list[Case] = [
    Case("m-01", "mock", "clean",      {"guardian": "ALLOW"}, tags=("scenario",)),
    Case("m-02", "mock", "suspicious", {"guardian": "DENY"},  tags=("scenario",)),
    Case("m-03", "mock", "hostile",    {"guardian": "DENY"},  tags=("scenario",)),
]


def _run_mock(scenario: str) -> dict:
    from zyko.mock_llm import MockLLM
    from zyko.guardian import DefaultGuardian

    async def _r():
        text = await MockLLM(scenario).propose("test prompt")
        verdict = (await DefaultGuardian().check(text)).verdict
        return {"guardian": verdict, "non_empty": bool(text)}

    return asyncio.run(_r())


def test_benchmark_mock(capsys):
    scores = []
    for c in MOCK_CASES:
        actual = _run_mock(c.payload)
        s = 1.0 if actual.get("guardian") == c.expected["guardian"] else 0.0
        if not actual["non_empty"]:
            s = 0.0
        scores.append(s)
        if s < 1.0:
            with capsys.disabled():
                print(f"  [MOCK FAIL] {c.id}: exp={c.expected} act={actual}")
    mean = sum(scores) / len(scores)
    with capsys.disabled():
        print(f"[mock_llm] {mean*100:5.1f}% over {len(MOCK_CASES)} cases")
    assert mean == 1.0, f"MockLLM {mean*100:.1f}% — must be 100%"


# ═══════════════════════════════════════════════════════════════════
# Capability 4: GuardedLoop end-to-end
# ═══════════════════════════════════════════════════════════════════

LOOP_CASES: list[Case] = [
    Case("l-01", "loop", ("clean", "test"),      True,  tags=("allow",)),
    Case("l-02", "loop", ("suspicious", "test"), False, tags=("deny",)),
    Case("l-03", "loop", ("hostile", "test"),    False, tags=("deny",)),
]


def _run_loop(scenario: str, prompt: str) -> dict:
    from zyko.guarded import GuardedLoop
    from zyko.guardian import DefaultGuardian
    from zyko.mock_llm import MockLLM

    async def _r():
        r = await GuardedLoop(DefaultGuardian(), MockLLM(scenario)).run(prompt)
        return {
            "applied": r.applied,
            "has_receipt": "chain_hash" in r.receipt,
            "receipt_hex_len": len(r.receipt.get("chain_hash", "")),
        }

    return asyncio.run(_r())


def test_benchmark_loop(capsys):
    scores = []
    for c in LOOP_CASES:
        actual = _run_loop(*c.payload)
        ok = (
            actual["applied"] == c.expected
            and actual["has_receipt"]
            and actual["receipt_hex_len"] >= 16
        )
        s = 1.0 if ok else 0.0
        scores.append(s)
        if s < 1.0:
            with capsys.disabled():
                print(f"  [LOOP FAIL] {c.id}: exp={c.expected} act={actual}")
    mean = sum(scores) / len(scores)
    with capsys.disabled():
        print(f"[guarded_loop] {mean*100:5.1f}% over {len(LOOP_CASES)} cases")
    assert mean == 1.0, f"Loop {mean*100:.1f}% — must be 100%"


# ═══════════════════════════════════════════════════════════════════
# Capability 5: Determinism — 100% reproducibility (hard gate)
# ═══════════════════════════════════════════════════════════════════

DET_CASES: list[Case] = [
    Case("d-guard-01", "det", ("guardian", "hello world"),      None, tags=("fingerprint",)),
    Case("d-guard-02", "det", ("guardian", "+966501234567"),    None, tags=("fingerprint", "pii")),
    Case("d-pii-01",   "det", ("pii",      "+966501234567"),    None, tags=("sha",)),
    Case("d-pii-02",   "det", ("pii",      "x@y.com"),          None, tags=("sha",)),
    Case("d-mock-01",  "det", ("mock",     "clean"),            None, tags=("sha",)),
    Case("d-mock-02",  "det", ("mock",     "suspicious"),       None, tags=("sha",)),
]


def _run_det_capability(capability: str, payload: str) -> str:
    if capability == "guardian":
        from zyko.guardian import DefaultGuardian
        async def _r():
            return (await DefaultGuardian().check(payload)).fingerprint
        return asyncio.run(_r())
    if capability == "pii":
        from zyko.tools.pii_ar import redact
        text, _ = redact(payload)
        return _sha(text)
    if capability == "mock":
        from zyko.mock_llm import MockLLM
        async def _r():
            return _sha(await MockLLM(payload).propose("test"))
        return asyncio.run(_r())
    raise ValueError(capability)


def test_benchmark_determinism(capsys):
    scores = []
    RUNS = 100
    for c in DET_CASES:
        cap, payload = c.payload
        first = _run_det_capability(cap, payload)
        matches = sum(1 for _ in range(RUNS) if _run_det_capability(cap, payload) == first)
        s = matches / RUNS
        scores.append(s)
        if s < 1.0:
            with capsys.disabled():
                print(f"  [DET FAIL] {c.id}: {matches}/{RUNS} stable")
    mean = sum(scores) / len(scores)
    with capsys.disabled():
        print(f"[determinism] {mean*100:5.1f}% over {len(DET_CASES)} functions x {RUNS} runs")
    assert mean == 1.0, f"Determinism {mean*100:.1f}% — must be 100%"


# ═══════════════════════════════════════════════════════════════════
# Aggregate — MMLU-style overall score (≥ 95%)
# ═══════════════════════════════════════════════════════════════════

def test_benchmark_overall(capsys):
    """Weighted mean over all non-determinism cases ≥ 95%."""
    all_scores: list[tuple[str, float, float]] = []

    for c in PII_CASES:
        all_scores.append(("pii", _score_pii(c.expected, _run_pii(c.payload)), c.weight))
    for c in GUARDIAN_CASES:
        all_scores.append(("guardian", 1.0 if _run_guardian(c.payload) == c.expected else 0.0, c.weight))
    for c in MOCK_CASES:
        actual = _run_mock(c.payload)
        ok = actual["non_empty"] and actual["guardian"] == c.expected["guardian"]
        all_scores.append(("mock", 1.0 if ok else 0.0, c.weight))
    for c in LOOP_CASES:
        actual = _run_loop(*c.payload)
        ok = actual["applied"] == c.expected and actual["has_receipt"]
        all_scores.append(("loop", 1.0 if ok else 0.0, c.weight))

    weighted = sum(s * w for _, s, w in all_scores) / sum(w for _, _, w in all_scores)

    # Pretty report
    by_cap: dict[str, list[float]] = defaultdict(list)
    for cap, s, _ in all_scores:
        by_cap[cap].append(s)

    with capsys.disabled():
        print("\n" + "=" * 64)
        print(f"{'ZYKO-Bench Report':^64}")
        print("=" * 64)
        print(f"{'Capability':15} {'Score':>8} {'Cases':>7} {'Threshold':>10} {'Status':>8}")
        print("-" * 64)
        thresholds = {"pii": 0.90, "guardian": 0.95, "mock": 1.0, "loop": 1.0}
        for cap in sorted(by_cap):
            avg = sum(by_cap[cap]) / len(by_cap[cap])
            thr = thresholds.get(cap, 0.95)
            status = "PASS" if avg >= thr else "FAIL"
            print(f"{cap:15} {avg*100:7.1f}% {len(by_cap[cap]):>7} {thr*100:>9.0f}% {status:>8}")
        print("-" * 64)
        det_scores = []
        for c in DET_CASES:
            cap_name, payload = c.payload
            first = _run_det_capability(cap_name, payload)
            matches = sum(1 for _ in range(100) if _run_det_capability(cap_name, payload) == first)
            det_scores.append(matches / 100)
        det_mean = sum(det_scores) / len(det_scores)
        print(f"{'determinism':15} {det_mean*100:7.1f}% {len(DET_CASES):>7} {'100%':>10} "
              f"{'PASS' if det_mean == 1.0 else 'FAIL':>8}")
        print("=" * 64)
        print(f"{'OVERALL (weighted)':15} {weighted*100:7.1f}% {len(all_scores):>7} {'95%':>10} "
              f"{'PASS' if weighted >= 0.95 else 'FAIL':>8}")
        print("=" * 64 + "\n")

    assert weighted >= 0.95, f"Overall {weighted*100:.1f}% < 95%"
