"""اختبارات بوابة المرحلة 4: تكامل، حتمية، اعتدال، تحسن، متانة، أداء."""

from __future__ import annotations

from zyko.pipeline.engine import PipelineEngine
from zyko.pipeline.gate import (
    ANCHORS,
    GateRow,
    Phase4GateResult,
    _check_robustness,
    _run_anchor,
    run_phase4_gate,
)

FAST_ANCHORS: tuple[tuple[str, str], ...] = (
    ("todo-cli", "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها"),
    ("blog-site", "مدونة عربية أنشر فيها مقالاتي مع صفحة تعريف عني"),
)


def test_gate_full_passes_default_anchors():
    result = run_phase4_gate()
    assert result.ok is True
    assert len(result.rows) >= len(ANCHORS)
    for row in result.rows:
        if row.description:  # صفوف المراسي فقط (صفوف متانة بلا وصف)
            assert row.completed
            assert row.deterministic
            assert row.idempotent
            assert row.improved


def test_gate_fast_subset(tmp_path):
    result = run_phase4_gate(FAST_ANCHORS, tmp_root=tmp_path)
    assert result.ok
    assert result.robustness_passed == result.robustness_total


def test_gate_robustness_covers_all_hostile_inputs(tmp_path):
    engine = PipelineEngine()
    passed, total, problems = _check_robustness(engine, tmp_path)
    assert passed == total
    assert problems == []
    assert total >= 8


def test_gate_row_properties():
    empty = GateRow(name="فارغ", description="x")
    assert empty.passed is False  # لا شيء مُتحقق منه بعد
    full = GateRow(
        name="كامل",
        description="x",
        completed=True,
        deterministic=True,
        idempotent=True,
        improved=True,
    )
    assert full.passed is True


def test_gate_table_contains_columns_and_verdict(tmp_path):
    result = run_phase4_gate(FAST_ANCHORS, tmp_root=tmp_path)
    table = result.table_ar()
    for header in ("المرساة", "اكتمال", "حتمية", "اعتدال", "تحسن", "ثوانٍ"):
        assert header in table
    assert "المتانة:" in table
    assert "النتيجة: البوابة ناجحة" in table


def test_gate_detects_broken_engine(tmp_path):
    """مرساة على محرك مكسور ⇒ البوابة تفشل مع مشكلة عربية معلنة."""

    class Broken:
        def review_source(self, source, filename="<text>"):  # noqa: ARG002
            raise ValueError("boom")

    engine = PipelineEngine(reviewer=Broken())
    row = _run_anchor(engine, "مكسور", FAST_ANCHORS[0][1], tmp_path)
    assert row.completed is False
    assert row.passed is False
    assert any("فشل في" in p for p in row.problems)


def test_gate_performance_bound_enforced(tmp_path):
    """حد أداء مستحيل (ميكروثانية) ⇒ البوابة تفشل من باب الأداء لا المنطق."""
    result = run_phase4_gate(FAST_ANCHORS[:1], max_seconds=0.000001, tmp_root=tmp_path)
    assert result.ok is False


def test_gate_result_defaults():
    r = Phase4GateResult()
    assert r.ok is False  # بلا صفوف: لا نجاح بالافتراض
    assert r.robustness_passed == 0
