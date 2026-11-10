"""Tests for zyko.dashboard — determinism, RTL, no-JS, dark mode, markdown."""

from __future__ import annotations

import hashlib
import re

from zyko.dashboard import (
    DashboardInput,
    GateResult,
    build_dashboard,
    build_from_gates,
    build_markdown_from_gates,
)


def _gates():
    return [
        {"name": "PIIGate", "passed": True},
        {"name": "RTLGate", "passed": True},
        {"name": "StructuralGate", "passed": False, "reason_ar": "اقتراح فارغ"},
    ]


def _files():
    return [
        {"path": "a.py", "score_before": 68, "score_after": 96},
        {"path": "b.py", "score_before": 90, "score_after": 85},
    ]


# ── Determinism ────────────────────────────────────────────────────


def test_html_is_deterministic():
    a = build_from_gates("test", "0.1.0", _gates())
    b = build_from_gates("test", "0.1.0", _gates())
    assert a == b
    assert hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()


def test_html_sorting_is_deterministic():
    a = build_from_gates("t", "0", [{"name": "Z", "passed": True}, {"name": "A", "passed": True}])
    b = build_from_gates("t", "0", [{"name": "A", "passed": True}, {"name": "Z", "passed": True}])
    assert a == b


def test_html_stable_across_100_runs():
    base = hashlib.sha256(build_from_gates("t", "0", _gates()).encode()).hexdigest()
    for _ in range(100):
        h = hashlib.sha256(build_from_gates("t", "0", _gates()).encode()).hexdigest()
        assert h == base


def test_no_timestamps():
    out = build_from_gates("t", "0", _gates())
    assert not re.search(r"\b20\d{2}\b", out)


# ── Content ────────────────────────────────────────────────────────


def test_reports_failures():
    out = build_from_gates("t", "0", _gates())
    assert "❌" in out
    assert "2/3" in out


def test_reports_all_success():
    g = [{"name": "A", "passed": True}, {"name": "B", "passed": True}]
    assert "✅ 2/2" in build_from_gates("t", "0", g)


def test_empty_gates():
    assert "لا توجد بوابات" in build_from_gates("t", "0", [])


def test_with_files():
    out = build_from_gates("t", "0", _gates(), _files())
    assert "a.py" in out
    assert "68 → 96" in out


def test_partial_file_scores():
    f = [{"path": "p.py", "score_before": 50, "score_after": None}]
    out = build_from_gates("t", "0", [], f)
    assert "50 → —" in out


def test_file_delta_negative():
    out = build_from_gates("t", "0", [], _files())
    assert "-5" in out


# ── RTL & a11y ─────────────────────────────────────────────────────


def test_is_rtl():
    out = build_from_gates("t", "0", _gates())
    assert 'dir="rtl"' in out
    assert 'lang="ar"' in out


def test_has_anchor_links():
    out = build_from_gates("t", "0", _gates())
    assert 'id="gates"' in out
    assert 'id="files"' in out
    assert 'href="#gates"' in out


def test_has_viewport():
    assert 'name="viewport"' in build_from_gates("t", "0", _gates())


def test_tables_have_labels():
    out = build_from_gates("t", "0", _gates())
    assert 'aria-label="نتائج البوابات"' in out
    assert 'aria-label="درجات الملفات"' in out


# ── Security ───────────────────────────────────────────────────────


def test_no_javascript():
    out = build_from_gates("t", "0", _gates())
    assert "<script" not in out.lower()
    assert "javascript:" not in out.lower()
    assert "onclick" not in out.lower()


def test_escapes_html():
    g = [{"name": "<script>x</script>", "passed": True, "reason_ar": "<b>y</b>"}]
    out = build_from_gates("t", "0", g)
    assert "&lt;script&gt;" in out
    assert "<script>x" not in out


def test_no_external_resources():
    out = build_from_gates("t", "0", _gates())
    assert "http://" not in out
    assert "https://" not in out


# ── Dark mode ──────────────────────────────────────────────────────


def test_dark_mode_css_present():
    out = build_from_gates("t", "0", _gates())
    assert "prefers-color-scheme: dark" in out
    assert "--bg: #0a0a0a" in out


# ── Fingerprint & duration ─────────────────────────────────────────


def test_html_fingerprint_in_footer():
    out = build_from_gates("t", "0", _gates())
    assert "البصمة:" in out
    assert re.search(r"[a-f0-9]{64}", out)


def test_gate_duration_rendered():
    g = [{"name": "A", "passed": True, "duration_ms": 12}]
    out = build_from_gates("t", "0", g)
    assert "12 ms" in out
    md = build_markdown_from_gates("t", "0", g)
    assert "12 ms" in md


def test_gate_duration_default_dash():
    out = build_from_gates("t", "0", _gates())
    assert "<td>—</td>" in out


# ── Dataclass path ─────────────────────────────────────────────────


def test_build_dashboard_dataclass_direct():
    data = DashboardInput(
        project_name="t",
        version="0",
        gates=(GateResult(name="A", passed=True),),
    )
    via_dicts = build_from_gates("t", "0", [{"name": "A", "passed": True}])
    assert build_dashboard(data) == via_dicts


# ── Markdown ───────────────────────────────────────────────────────


def test_markdown_deterministic():
    a = build_markdown_from_gates("t", "0", _gates())
    b = build_markdown_from_gates("t", "0", _gates())
    assert a == b


def test_markdown_contains_title():
    md = build_markdown_from_gates("t", "0", _gates())
    assert "# لوحة تحكم t" in md


def test_markdown_contains_fingerprint():
    md = build_markdown_from_gates("t", "0", _gates())
    assert "البصمة:" in md
    assert re.search(r"[a-f0-9]{64}", md)


def test_markdown_with_files():
    md = build_markdown_from_gates("t", "0", _gates(), _files())
    assert "a.py" in md
    assert "+28" in md


def test_markdown_no_html():
    md = build_markdown_from_gates("t", "0", _gates())
    for tag in ("<html", "<div", "<table"):
        assert tag not in md.lower()


def test_markdown_escapes_pipes():
    g = [{"name": "a|b", "passed": True, "reason_ar": "سبب|غريب"}]
    md = build_markdown_from_gates("t", "0", g)
    assert "a\\|b" in md
    assert "سبب\\|غريب" in md
    assert "| a|b " not in md


def test_markdown_empty_gates_warn():
    md = build_markdown_from_gates("t", "0", [])
    assert "لا توجد بوابات مسجلة" in md
