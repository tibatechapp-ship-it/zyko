"""اختبارات بوابة المرحلة 3: الصفوف الستة والغtabs الافتتاحية."""

from __future__ import annotations

from pathlib import Path

from zyko.fixer.engine import FixerEngine
from zyko.fixer.gate import (
    DEFAULT_MAX_SECONDS,
    GateRow,
    Phase3GateResult,
    default_samples_dir,
    run_phase3_gate,
)


def test_gate_on_anchor_samples_full_pass():
    result = run_phase3_gate()
    assert result.ok, result.table_ar()
    assert result.passed_count == 6
    ids = [r.gate_id for r in result.rows]
    assert ids == ["G1", "G2", "G3", "G4", "G5", "G6"]


def test_gate_missing_samples_reports_g0(tmp_path):
    result = run_phase3_gate(tmp_path)
    assert not result.ok
    assert result.rows[0].gate_id == "G0"
    assert "manifest.json" in result.rows[0].detail_ar


def test_gate_row_table_arabic():
    res = Phase3GateResult(
        rows=[
            GateRow("G1", "اسم عربي", True, "تفصيل"),
            GateRow("G2", "آخر", False, "سبب"),
        ]
    )
    t = res.table_ar()
    assert "ناجحة" in t and "فاشلة" in t
    assert "الحكم: مرفوض" in t
    assert res.passed_count == 1 and res.ok is False


def test_gate_empty_rows_not_ok():
    assert Phase3GateResult().ok is False


def test_default_samples_dir_resolution():
    # من جذر المستودع (الآباء الثلاثة) تُرصد العينات
    here = Path(__file__).resolve()
    candidates = [here.parents[i] for i in range(1, 4)]
    if any((c / "samples" / "fix" / "manifest.json").is_file() for c in candidates):
        assert default_samples_dir() is not None
    else:
        assert default_samples_dir() is None


def test_gate_determinism_row_wording():
    result = run_phase3_gate()
    g3 = result.rows[2]
    assert g3.gate_id == "G3"
    assert "بايتات متطابقة" in g3.detail_ar


def test_gate_g6_covers_38_rules():
    result = run_phase3_gate()
    g6 = result.rows[5]
    assert g6.passed
    assert "12/12" in g6.detail_ar and "26/26" in g6.detail_ar


def test_gate_performance_under_default_budget():
    result = run_phase3_gate()
    g5 = result.rows[4]
    assert g5.passed
    assert DEFAULT_MAX_SECONDS == 5.0


def test_fixer_engine_default_samples_consistency():
    # البوابة والمحرك يتفقان على مكان العينات — لا انحراف بين الطبقات
    d = default_samples_dir()
    if d is not None:
        assert (d / "manifest.json").is_file()
        fixer = FixerEngine()
        results = [
            fixer.fix_file(d / e["file"])
            for e in __import__("json").loads((d / "manifest.json").read_text(encoding="utf-8"))[
                "defective"
            ]
        ]
        assert all(r.parse_error is None for r in results)
