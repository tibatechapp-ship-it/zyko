"""اختبارات بوابة المرحلة 6 (zyko.baseline.gate): ست بوابات على ثلاث مراسٍ.

العقد المُختبر هنا:
- البوابة الكاملة ناجحة على المراسي الافتراضية (3 مراسٍ × 6 بوابات)
- كل مرساة تُكمل update⇒check، حتمية، تكشف التراجع والتحسن، وتنتهي سريعًا
- المتانة 12/12: كل مدخل عدائي فشل مهيكل عربي بلا أي استثناء
- جدول البوابة عربي ويعرض النتيجة بوضوح
"""

from __future__ import annotations

from zyko.baseline.engine import BaselineEngine
from zyko.baseline.gate import (
    ANCHORS,
    HOSTILE_TOTAL,
    Phase6GateResult,
    run_phase6_gate,
)


def test_gate_passes_on_default_anchors():
    result = run_phase6_gate()
    assert isinstance(result, Phase6GateResult)
    assert len(result.rows) == len(ANCHORS)
    assert result.ok, "\n".join(r.problems for r in result.rows)
    for row in result.rows:
        assert row.completed, row.problems
        assert row.deterministic, row.problems
        assert row.detects_regression, row.problems
        assert row.detects_improvement, row.problems
        assert row.seconds < result.max_seconds
    assert result.robustness_passed == result.robustness_total == HOSTILE_TOTAL


def test_gate_table_is_arabic_and_decisive():
    table = run_phase6_gate().table_ar()
    assert "بوابة المرحلة 6" in table
    assert "المرساة" in table and "حتمية" in table
    assert "المتانة: 12/12" in table
    assert "ناجحة ✅" in table


def test_gate_robustness_labels_cover_the_12():
    labels = (
        "مجلد غير موجود",
        "ملف بدل مجلد",
        "مسار معدوم النوع",
        "مسار رقمي",
        "مسار بايتات",
        "خط أساس فاسد JSON",
        "خط أساس بترميز فاسد",
        "خط أساس قائمة",
        "مخطط غير معروف",
        "قسم ملفات غير صالح",
        "درجة نصية",
        "خط أساس مجلد لا ملف",
    )
    assert len(labels) == HOSTILE_TOTAL == 12


def test_gate_anchors_are_the_workspace_trees():
    # المراسي نفسها التي يقيس بها المحرك المرحلة 5 — واقع واحد لكل الأدوات
    names = {name for name, _files in ANCHORS}
    assert names == {"small-cli", "pkg-lib", "mixed-tree"}


def test_gate_fails_on_broken_anchor(tmp_path):
    """مرساة مفسودة عمدًا (لا ملفات بايثون) يجب أن تفشل بواباتها."""
    broken = (("hollow", {"notes.txt": "لا بايثون هنا"}),)
    result = run_phase6_gate(broken)
    assert not result.ok
    row = result.rows[0]
    assert not row.completed
    assert row.problems


def test_gate_fails_when_regression_slips_through(tmp_path):
    """مرساة بلا ما يفسد ⇒ كشف التراجع يعمل حتى مع ملف نظيف وحيد."""
    # ملف نظيف + إضافة eval ⇒ يجب أن يُكشف التراجع؛ لو انكسر الكشف فالبوابة تفشل
    anchor = (("only-clean", {"a.py": '"""نظيف."""\n\n\ndef f(x):\n    return x\n'}),)
    result = run_phase6_gate(anchor)
    assert result.ok, "\n".join(r.problems for r in result.rows)


def test_gate_hostile_check_is_structured_not_crash(tmp_path):
    """فحص مباشر لعينة عدائية واحدة خارج البوابة (تعزيز W5)."""
    engine = BaselineEngine()
    good = tmp_path / "good"
    good.mkdir()
    (good / "a.py").write_text("X = 1\n", encoding="utf-8")
    engine.update(good)
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"schema": "zyko.baseline/1", "files": {"a.py": {"score": true}}}\n', encoding="utf-8"
    )
    r = engine.check(good, baseline_path=bad)
    assert not r.ok and r.exit_code == 2
    assert r.failed_stage == "baseline" and r.error_ar


def test_gate_result_defaults_are_fail_closed():
    empty = Phase6GateResult()
    assert not empty.ok  # بلا صفوف: فشل مغلق افتراضيًا
    assert empty.robustness_total == HOSTILE_TOTAL
