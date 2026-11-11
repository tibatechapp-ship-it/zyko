"""اختبارات معمل الإصلاح المحلي — عقد الكوربوس والحتمية والفئات الثلاث.

الاختبارات هنا لا تشغّل المعمل كاملاً (28 تشغيل pytest متتالي ثقيلة على
المصفوفة) — بل تشغّل **عينات حتمية صغيرة** تثبت العقود:
بنية الكوربوس سليمة، الفئات الثلاث كل واحدة على عقدتها، والإيصال
حتمي بالبايت بين تشغيلين.
"""

from __future__ import annotations

import ast

import pytest

from zyko.benchmarks.repair import (
    CATEGORIES,
    CATEGORY_BEHAVIORAL,
    CATEGORY_MANUAL,
    CATEGORY_QUALITY,
    CORPUS,
    RepairCase,
    run_repair_lab,
)
from zyko.reviewer.rules import RULES_BY_ID

# عينات حتمية خفيفة — كل واحدة تُثبت عقد فئة كامل بأقل زمن تشغيل
_QUALITY_SAMPLE = (
    CORPUS[6],  # unused_import
    CORPUS[9],  # missing_docstrings
)
_BEHAVIORAL_SAMPLE = (CORPUS[3],)  # eq_none_trap — سلوك نقي بلا اعتماديات خارجية
_MANUAL_SAMPLE = (CORPUS[10],)  # eval_on_input


# --------------------------------------------------------------- بنية الكوربوس
def test_corpus_size_and_categories():
    """14 حالة موزعة 5 سلوكية و5 جودة و4 يدوية — لا فئة صامتة."""
    assert len(CORPUS) == 14
    counts = {cat: 0 for cat in CATEGORIES}
    for case in CORPUS:
        counts[case.category] += 1
    assert counts == {
        CATEGORY_BEHAVIORAL: 5,
        CATEGORY_QUALITY: 5,
        CATEGORY_MANUAL: 4,
    }


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_corpus_module_parses(case: RepairCase):
    """كل وحدة في الكوربوس شيفرة بايثون سليمة قابلة للتحليل."""
    ast.parse(case.source)


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_corpus_seeded_rules_exist(case: RepairCase):
    """كل قاعدة مبذورة في الكوربوس موجودة في سجل المراجع الـ38 — لا قاعدة وهمية."""
    assert case.seeded, f"{case.name} بلا بذور"
    for rid, count in case.seeded:
        assert rid in RULES_BY_ID, f"{case.name}: القاعدة {rid} غير معروفة"
        assert count >= 1, f"{case.name}: عدد بذور {rid} غير منطقي"


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_corpus_tests_are_selfcontained(case: RepairCase):
    """اختبارات النية لا تستورد zyko ولا تمس الشبكة — وحدة تحت الفحص فقط."""
    assert "zyko" not in case.tests
    for forbidden in ("requests", "urllib", "socket"):
        assert forbidden not in case.tests, f"{case.name}: اختبار يمس {forbidden}"


# --------------------------------------------------------------- عقد الفئات
def test_quality_sample_repaired_without_breaking():
    """فئة الجودة: القاعدة تختفي والاختبارات تمر قبل وبعد والإصلاح معتدل."""
    report = run_repair_lab(cases=_QUALITY_SAMPLE)
    assert report.ok
    assert report.quality_repair_rate == 1.0
    for row in report.rows:
        assert row.tests_before_ok and row.tests_after_ok
        assert row.idempotent
        assert row.score_after >= row.score_before


def test_behavioral_sample_flips_tests():
    """فئة السلوك: الاختبارات تفشل قبل الإصلاح وتمر بعده — مقياس الانعكاس الحرفي."""
    report = run_repair_lab(cases=_BEHAVIORAL_SAMPLE)
    assert report.ok
    row = report.rows[0]
    assert row.tests_before_ok is False
    assert row.tests_after_ok is True
    assert row.resolved is True


def test_manual_sample_detected_not_fixed():
    """فئة اليدوية: تُكشف البذرة كاملة ولا يتغير النص — اعتراف بالحد لا تظاهر."""
    report = run_repair_lab(cases=_MANUAL_SAMPLE)
    assert report.ok
    row = report.rows[0]
    assert row.detected == ("R-SEC-101",)
    assert row.changed is False
    assert row.tests_before_ok and row.tests_after_ok


# --------------------------------------------------------------- الحتمية
def test_receipt_is_byte_deterministic():
    """نفس العينة مرتين ⇒ نفس الإيصال بالبايت (بلا أزمنة في التمثيل)."""
    first = run_repair_lab(cases=_QUALITY_SAMPLE)
    second = run_repair_lab(cases=_QUALITY_SAMPLE)
    assert first.to_json() == second.to_json()
    assert first.chain_hash == second.chain_hash


def test_empty_cases_rejected():
    """معمل بلا حالات رفض صريح — لا تقرير فارغ يزيف النجاح."""
    with pytest.raises(ValueError):
        run_repair_lab(cases=())
