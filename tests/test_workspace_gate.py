"""اختبارات بوابة المرحلة 5: ست بوابات كمية على مراسٍ عربية.

العقد المُختبر هنا:
- البوابة كاملة على المراسي الثلاث ناجحة: تكامل/حتمية/اعتدال/تحسن/متانة 12/12/أداء
- مرساة نظيفة بلا ما يُصلَح تُسقط البوابة (لا قيمة بلا إصلاحات)
- الحكم حتمي: تشغيلان للبوابة ⇒ النتيجة نفسها
"""

from __future__ import annotations

from zyko.workspace.gate import (
    ANCHORS,
    HOSTILE_TOTAL,
    GateRow,
    Phase5GateResult,
    run_phase5_gate,
)

CLEAN_ONLY = {
    "clean.py": '"""نظيف."""\n\n\ndef add(a: int, b: int) -> int:\n    """يجمع."""\n    return a + b\n'
}


def test_full_gate_passes():
    gate = run_phase5_gate()
    assert gate.ok is True
    assert len(gate.rows) == len(ANCHORS)
    assert gate.robustness_passed == gate.robustness_total == HOSTILE_TOTAL
    assert HOSTILE_TOTAL == 12
    for r in gate.rows:
        assert r.passed, f"مرساة {r.name}: {r.problems}"


def test_gate_anchors_are_three_trees_with_expected_shape():
    names = [n for n, _ in ANCHORS]
    assert names == ["small-cli", "pkg-lib", "mixed-tree"]
    mixed = dict(ANCHORS)[  # noqa: C416 — قراءة واضحة
        "mixed-tree"
    ]
    assert any(isinstance(v, bytes) for v in mixed.values()), "مرساة الفساد تحتاج ملفًا بترميز فاسد"


def test_gate_table_ar_contains_all_sections():
    text = run_phase5_gate().table_ar()
    assert "بوابة المرحلة 5" in text
    assert "المتانة: 12/12" in text
    assert "النتيجة: البوابة ناجحة ✅" in text
    for name in ("small-cli", "pkg-lib", "mixed-tree", "متانة"):
        assert name in text


def test_clean_anchor_fails_improved_gate():
    gate = run_phase5_gate(anchors=(("نظيف-فقط", CLEAN_ONLY),))
    assert gate.ok is False
    row = gate.rows[0]
    assert row.completed is True
    assert row.improved is False
    assert any("لا إصلاحات" in p for p in row.problems)


def test_gate_robustness_failure_marks_not_ok(monkeypatch):
    gate = run_phase5_gate()
    assert gate.ok is True
    gate.robustness_passed = gate.robustness_total - 1
    assert gate.ok is False
    assert "فاشلة" in gate.table_ar()


def test_gate_performance_gate_respects_max_seconds():
    gate = run_phase5_gate(max_seconds=0.0000001)
    assert gate.ok is False
    assert any(r.seconds > 0 for r in gate.rows)


def test_gate_verdict_is_deterministic():
    a = run_phase5_gate()
    b = run_phase5_gate()
    assert a.ok == b.ok
    assert a.robustness_passed == b.robustness_passed


def test_gate_row_passing_semantics():
    row = GateRow(name="x", description="")
    assert row.passed is False
    row.completed = row.deterministic = row.idempotent = row.improved = True
    assert row.passed is True
    result = Phase5GateResult()
    assert result.ok is False, "بلا صفوف لا نجاح"


def test_custom_anchor_minimal_but_real(tmp_path):
    files = {"mod.py": "import os\n\n\ndef f(x):\n    return x == None\n"}
    gate = run_phase5_gate(anchors=(("مصغر", files),), tmp_root=tmp_path)
    assert gate.ok is True
    assert gate.rows[0].passed
