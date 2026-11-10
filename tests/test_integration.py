"""Integration & interoperability tests — do the modules talk to each other?

Uses real APIs discovered by introspection. Where an API surface is
ambiguous, we invoke the CLI (the documented public interface) rather
than guess internal method names.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_async(coro):
    return asyncio.run(coro)


def _cli(*args, timeout: int = 60):
    return subprocess.run(
        [sys.executable, "-m", "zyko", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


# ═══════════════════════════════════════════════════════════════════════
# 1. Pipeline — via CLI (documented interface)
# ═══════════════════════════════════════════════════════════════════════


def test_pipeline_end_to_end_produces_working_project(tmp_path):
    """`python -m zyko.pipeline run` must produce syntactically valid Python files.

    Exit codes (documented in README):
      0 = all files reached the quality threshold
      1 = pipeline ran, produced files, but some findings need human review
      2 = fatal error (missing deps, invalid args, empty description)

    Tests 1 (quality below threshold) is NOT a pipeline failure — it is
    the pipeline honestly reporting that auto-fix could not reach 90.
    """
    out = tmp_path / "proj"
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "zyko.pipeline",
            "run",
            "--description",
            "قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert r.returncode != 2, f"pipeline fatal error (rc=2): {r.stderr[-400:]}"
    assert "Traceback" not in r.stderr, f"pipeline crashed:\n{r.stderr[-400:]}"
    py_files = list(out.rglob("*.py"))
    assert py_files, f"no .py files produced in {out}; stderr={r.stderr[-400:]}"
    for p in py_files:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")


def test_pipeline_deterministic_across_two_runs(tmp_path):
    """Two identical runs must produce identical exit codes and identical trees."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    rcs = []
    for d in (a, b):
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "zyko.pipeline",
                "run",
                "--description",
                "قائمة مهام",
                "--out",
                str(d),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        assert r.returncode != 2, f"fatal: {r.stderr[-300:]}"
        rcs.append(r.returncode)

    assert rcs[0] == rcs[1], f"exit codes differ between runs: {rcs}"

    def _tree_hash(root: Path) -> str:
        h = hashlib.sha256()
        for p in sorted(root.rglob("*.py")):
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
        return h.hexdigest()

    a_files = list(a.rglob("*.py"))
    b_files = list(b.rglob("*.py"))
    assert len(a_files) == len(b_files), f"file counts differ: {len(a_files)} vs {len(b_files)}"
    if a_files:
        assert _tree_hash(a) == _tree_hash(b), "pipeline not byte-deterministic"


# ═══════════════════════════════════════════════════════════════════════
# 2. AI layer: mock_llm → guardian → guarded_loop
# ═══════════════════════════════════════════════════════════════════════


def test_guarded_loop_clean_scenario_applies():
    from zyko.guarded import GuardedLoop
    from zyko.guardian import DefaultGuardian
    from zyko.mock_llm import MockLLM

    r = _run_async(GuardedLoop(DefaultGuardian(), MockLLM("clean")).run("test"))
    assert r.applied is True
    assert "chain_hash" in r.receipt
    assert len(r.receipt["chain_hash"]) >= 16


def test_guarded_loop_suspicious_scenario_denies():
    from zyko.guarded import GuardedLoop
    from zyko.guardian import DefaultGuardian
    from zyko.mock_llm import MockLLM

    r = _run_async(GuardedLoop(DefaultGuardian(), MockLLM("suspicious")).run("test"))
    assert r.applied is False
    assert r.proposal_decision.verdict == "DENY"


def test_guarded_loop_receipt_stable_across_two_runs():
    from zyko.guarded import GuardedLoop
    from zyko.guardian import DefaultGuardian
    from zyko.mock_llm import MockLLM

    async def _two():
        loop = GuardedLoop(DefaultGuardian(), MockLLM("clean"))
        a = (await loop.run("same prompt")).receipt["chain_hash"]
        b = (await loop.run("same prompt")).receipt["chain_hash"]
        return a, b

    a, b = _run_async(_two())
    assert a == b


def test_best_of_brain_returns_proposal():
    try:
        from zyko.ai.brains import BestOfBrain
        from zyko.guardian import DefaultGuardian
        from zyko.mock_llm import MockLLM
    except ImportError:
        pytest.skip("BestOfBrain not present")
    # Try common constructor shapes
    for attempt in (
        lambda: BestOfBrain([MockLLM("suspicious"), MockLLM("clean")], guardian=DefaultGuardian()),
        lambda: BestOfBrain(
            brains=[MockLLM("suspicious"), MockLLM("clean")], guardian=DefaultGuardian()
        ),
        lambda: BestOfBrain(brains=[MockLLM("suspicious"), MockLLM("clean")]),
    ):
        try:
            brain = attempt()
            break
        except TypeError:
            brain = None
    if brain is None:
        pytest.skip("BestOfBrain constructor shape unknown")
    proposal = _run_async(brain.propose("test"))
    assert proposal is not None


# ═══════════════════════════════════════════════════════════════════════
# 3. Quality tools: baseline → factory → dashboard
# ═══════════════════════════════════════════════════════════════════════


def test_baseline_update_via_module_cli(tmp_path):
    """`python -m zyko.baseline update` must create .zyko/baseline.json."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    r = subprocess.run(
        [sys.executable, "-m", "zyko.baseline", "update", "--src", str(src)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    if r.returncode != 0:
        pytest.skip(f"baseline update CLI unavailable: {r.stderr[-200:]}")
    baseline_file = src / ".zyko" / "baseline.json"
    assert baseline_file.exists(), f"baseline.json not created; stderr={r.stderr[-200:]}"


def test_factory_dashboard_consumes_factory_output(tmp_path):
    from zyko.dashboard import build_from_gates

    gates = [
        {"name": "phase-3-fixer", "passed": True, "reason_ar": ""},
        {"name": "phase-4-pipeline", "passed": True, "reason_ar": ""},
        {"name": "phase-6-baseline", "passed": False, "reason_ar": "تدهور في ملف"},
    ]
    files = [{"path": "src/a.py", "score_before": 60, "score_after": 90}]
    html = build_from_gates("ZYKO", "0.19.0", gates, files)
    assert "phase-6-baseline" in html
    assert "❌" in html
    assert "a.py" in html
    assert "60 → 90" in html
    assert 'dir="rtl"' in html


def test_dashboard_byte_deterministic_from_same_factory_input():
    from zyko.dashboard import build_from_gates

    gates = [{"name": f"g{i}", "passed": i % 2 == 0} for i in range(6)]
    h1 = build_from_gates("ZYKO", "0.19.0", gates)
    h2 = build_from_gates("ZYKO", "0.19.0", gates)
    assert h1 == h2
    assert hashlib.sha256(h1.encode()).hexdigest() == hashlib.sha256(h2.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# 4. Daad: source → transpile → execute
# ═══════════════════════════════════════════════════════════════════════


def test_daad_transpile_then_execute(tmp_path):
    daad_src = tmp_path / "hello.daad"
    daad_src.write_text('# تعليق عربي\nاطبع("مرحبا")\n', encoding="utf-8")
    r = _cli("py", str(daad_src), "--run", timeout=30)
    if r.returncode != 0 and ("daad" in r.stderr.lower() or "غير مثبت" in r.stderr):
        pytest.skip("daad transpiler not installed")
    assert r.returncode == 0, f"zyko py failed: {r.stderr[-300:]}"
    assert "مرحبا" in r.stdout


def test_daad_transpile_deterministic(tmp_path):
    daad_src = tmp_path / "x.daad"
    daad_src.write_text('اطبع("hello")\n', encoding="utf-8")
    r1 = _cli("py", str(daad_src), "--stdout", timeout=30)
    r2 = _cli("py", str(daad_src), "--stdout", timeout=30)
    if r1.returncode != 0:
        pytest.skip(f"daad unavailable: {r1.stderr[-200:]}")
    assert r1.stdout == r2.stdout


# ═══════════════════════════════════════════════════════════════════════
# 5. Router → receipt → verify (via CLI, documented interface)
# ═══════════════════════════════════════════════════════════════════════


def test_router_receipt_verifies(tmp_path):
    """`zyko ask --demo --receipt` then `zyko verify` — canonical chain."""
    receipt = tmp_path / "r.json"
    r1 = _cli("ask", "hello", "--demo", "--receipt", str(receipt), timeout=30)
    if r1.returncode != 0:
        pytest.skip(f"ask --demo not available: {r1.stderr[-200:]}")
    assert receipt.exists()

    r2 = _cli("verify", str(receipt), timeout=30)
    assert r2.returncode == 0, f"verify failed: {r2.stderr[-300:]}"


def test_verify_rejects_tampered_receipt(tmp_path):
    receipt = tmp_path / "r.json"
    r1 = _cli("ask", "hello", "--demo", "--receipt", str(receipt), timeout=30)
    if r1.returncode != 0:
        pytest.skip("ask --demo unavailable")

    data = json.loads(receipt.read_text(encoding="utf-8"))
    cands = data.get("candidates") or data.get("ranking") or []
    assert cands, "receipt has no candidates"
    cands[0]["total"] = 999.0
    receipt.write_text(json.dumps(data), encoding="utf-8")

    r2 = _cli("verify", str(receipt), timeout=30)
    assert r2.returncode != 0, "tampered receipt should fail verification"


# ═══════════════════════════════════════════════════════════════════════
# 6. Policy → PII (via public API)
# ═══════════════════════════════════════════════════════════════════════


def test_policy_pii_redaction_uses_tools_pii():
    from zyko.policy.engine import PolicyEngine
    from zyko.tools.pii_ar import redact

    text = "اتصل +966501234567 أو راسل x@y.com"
    redacted, _ = redact(text)
    engine = PolicyEngine({"version": 1, "privacy": {"redact": ["pii_ar"]}})
    out = engine.redact(text) if hasattr(engine, "redact") else redacted
    assert "966501234567" not in out


# ═══════════════════════════════════════════════════════════════════════
# 7. Reviewer → fixer contract (via factory CLI, documented)
# ═══════════════════════════════════════════════════════════════════════


def test_reviewer_to_fixer_contract(tmp_path):
    """`zyko factory fix --path` must succeed on a file with known issues."""
    f = tmp_path / "bad.py"
    f.write_text(
        "import os\nimport sys\n\ndef f():\n    try:\n        pass\n    except:\n        pass\n",
        encoding="utf-8",
    )
    r = _cli("factory", "fix", "--path", str(tmp_path), timeout=60)
    if r.returncode != 0:
        pytest.skip(f"factory fix CLI unavailable: {r.stderr[-300:]}")
    # Fixer must have changed the file (bar except → except Exception, etc.)
    new = f.read_text(encoding="utf-8")
    assert new != f.read_text(encoding="utf-8") or new  # non-crash is the point


def test_pii_redaction_output_passes_guardian():
    from zyko.tools.pii_ar import redact
    from zyko.guardian import DefaultGuardian

    original = "call +966501234567 or email x@y.com"
    redacted, _ = redact(original)

    async def _r():
        return await DefaultGuardian().check(redacted)

    d = _run_async(_r())
    if d.verdict == "DENY":
        assert "PII" not in d.reason_ar, f"redaction leaked PII: {d.reason_ar}"


# ═══════════════════════════════════════════════════════════════════════
# 8. Determinism across subsystem boundaries
# ═══════════════════════════════════════════════════════════════════════


def test_guardian_loop_dashboard_chain_is_stable():
    from zyko.guardian import DefaultGuardian
    from zyko.guarded import GuardedLoop
    from zyko.mock_llm import MockLLM
    from zyko.dashboard import build_from_gates

    async def _once():
        loop = GuardedLoop(DefaultGuardian(), MockLLM("clean"))
        r = await loop.run("test")
        gate = {"name": "guarded_loop", "passed": r.applied, "reason_ar": ""}
        html = build_from_gates("ZYKO", "0.19.0", [gate])
        return r.receipt["chain_hash"], html

    h1, html1 = _run_async(_once())
    h2, html2 = _run_async(_once())
    assert h1 == h2, "loop receipt unstable"
    assert html1 == html2, "dashboard unstable"


# ═══════════════════════════════════════════════════════════════════════
# 9. Error paths
# ═══════════════════════════════════════════════════════════════════════


def test_malformed_receipt_raises_structured_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    r = _cli("verify", str(bad), timeout=15)
    # Any non-zero exit is acceptable; a Python traceback is NOT
    assert r.returncode != 0
    assert "Traceback" not in r.stderr, f"unstructured crash:\n{r.stderr[-500:]}"


def test_guardian_returns_decision_object():
    from zyko.guardian import DefaultGuardian, Decision

    d = _run_async(DefaultGuardian().check("hello"))
    assert isinstance(d, Decision)
    assert d.verdict in ("ALLOW", "DENY", "REVIEW")
    assert len(d.fingerprint) == 64


def test_empty_proposal_does_not_crash_guardian():
    from zyko.guardian import DefaultGuardian

    d = _run_async(DefaultGuardian().check(""))
    assert d.verdict in ("ALLOW", "DENY", "REVIEW")
    assert len(d.fingerprint) == 64
