"""frontier anchors — عدّة المقاييس الأمامية (الموجة 24): كل رقم مرساة لا ادعاء.

هذه الاختبارات تحكم أن مصفوفة المقاييس الأمامية صادقة وحتمية بالبايت:
الأوزان معلنة ومجموعها 1.0، والمحاور الحية (العقود والطرفية) تمر على
العقود الحقيقية، والقارئات ترفض الوثيقة الغائبة، والضعف الموثق يُسمّى
لا يُطمس — وترقية أي رقم تمر بإعادة قياس موثقة لا بتحرير يدوي.
"""

from __future__ import annotations

import json

import pytest

from zyko.benchmarks.frontier import (
    APPLICABLE_WEIGHTS,
    AXES,
    EVAL1000_DOC,
    SYNTHLAB_DOC,
    WEIGHT_SUM,
    WIDE19_DOC,
    WIDE25_MERGED_DOC,
    read_signed_doc,
    read_wide_metrics,
    run_contract_lab,
    run_frontier,
    run_terminal_lab,
    verdict_for,
)


def test_axes_weights_declared_and_sum_to_one():
    """الأوزان معلنة ومجموعها 1.0 — لا محور خفي وزنه."""
    assert round(WEIGHT_SUM, 6) == 1.0, "مجموع الأوزان معلن لا مُختلق"
    keys = {a.key for a in AXES}
    assert {
        "swe_engineering",
        "agentic_tools",
        "terminal",
        "reasoning_determinism",
        "platforms",
        "multimodal",
    } <= keys
    mm = next(a for a in AXES if a.key == "multimodal")
    assert mm.weight == 0.0, "متعدد الوسائط معلن خارج النطاق بوزن صفر — لا رقم مزيف"
    assert APPLICABLE_WEIGHTS == 1.0, "المحاور القابلة للقياس تحمل الوزن كاملاً"


def test_contract_lab_twelve_scenarios_all_correct():
    """معمل قرارات العقود: 12 سيناريو بالاتجاهين — القبول الخاطئ فشل والرفض الخاطئ فشل."""
    lab = run_contract_lab()
    assert lab["total"] == 12
    assert lab["correct"] == 12, "دقة قرارات العقود 12/12 — أي انحراف يُسمّى"
    assert lab["accuracy_pct"] == 100.0
    # إعادة التشغيل بنفس الحكم — العقد حتمي لا حظي
    lab2 = run_contract_lab()
    assert lab2["correct"] == lab["correct"]


def test_terminal_lab_eight_tasks_all_pass():
    """معمل الطرفية: 8 مهام حقيقية تحت العقد والجِل — كتابة وتشغيل وحراسة."""
    lab = run_terminal_lab()
    assert lab["total"] == 8
    assert lab["passed"] == 8, "مهام الطرفية الثمانية كلها تمر — والفاشل موثق لا مطموس"
    assert lab["success_pct"] == 100.0


def test_frontier_report_deterministic_bytes():
    """التقرير حتمي بالبايت: تشغيلان متتاليان بنفس بصمة السلسلة."""
    r1 = run_frontier()
    r2 = run_frontier()
    assert r1["chain_hash"] == r2["chain_hash"]
    assert r1["zfi"] == r2["zfi"]


def test_zfi_equals_declared_weighted_sum():
    """المؤشر المجمع = المتوسط الموزون المعلن — لا غرق الضعف في المتوسط بلا حساب."""
    report = run_frontier()
    zfi = (
        sum(
            a.weight * float(row["score_pct"])
            for a, row in zip(AXES, report["axes"])
            if a.weight > 0 and row["score_pct"] is not None
        )
        / APPLICABLE_WEIGHTS
    )
    assert round(zfi, 2) == report["zfi"]


def test_swe_axis_score_matches_declared_formula():
    """مزيج هندسة البرمجيات معلن: 0.4 تعدد الملفات + 0.3 بيئي + 0.3 صارم — بمصادر موقّعة."""
    report = run_frontier()
    swe = next(r for r in report["axes"] if r["axis"] == "swe_engineering")
    wide = read_wide_metrics()
    expected = round(
        0.4 * 100.0 + 0.3 * float(wide["env_solve_pct"]) + 0.3 * float(wide["strict_solve_pct"]), 2
    )
    assert float(swe["score_pct"]) == expected
    sources = json.dumps(swe["sub_metrics"], ensure_ascii=False)
    assert WIDE19_DOC.name in sources and WIDE25_MERGED_DOC.name in sources, (
        "كل رقم فرعي يفصح بوثيقته الموقّعة"
    )


def test_readers_refuse_missing_documents():
    """الوثيقة الموقّعة الغائبة فشل موثق — لا ادعاء بلا عدّاد."""
    missing = EVAL1000_DOC.with_name("not_there.json")
    with pytest.raises(FileNotFoundError, match="بلا عدّاد"):
        read_signed_doc(missing)


def test_signed_documents_present_in_tree():
    """الوثائق الموقّعة موجودة في الشجرة — قراءة المحاور لا تتخيلها."""
    for doc in (WIDE19_DOC, WIDE25_MERGED_DOC, EVAL1000_DOC, SYNTHLAB_DOC):
        assert doc.is_file(), f"وثيقة موقّعة مفقودة: {doc.name}"
        data = json.loads(doc.read_text(encoding="utf-8"))
        assert data, f"وثيقة فارغة: {doc.name}"


def test_weakness_is_named_not_hidden():
    """الضعف الموثق يُسمّى: هندسة البرمجيات تحت العتبة — هذا بيت القصيد المنهجي."""
    report = run_frontier()
    swe = next(r for r in report["axes"] if r["axis"] == "swe_engineering")
    assert swe["verdict"] == "ضعف", "حين يتحسن الحل الصارم يُحدَّث هذا المرساة بإعادة قياس موثقة"
    assert float(swe["score_pct"]) < 60.0


def test_verdict_thresholds_boundaries():
    """حدود الحكم الثلاثي: قوة ≥ 90، مراقبة 60–90، ضعف < 60."""
    assert verdict_for(90.0) == "قوة"
    assert verdict_for(89.9) == "مراقبة"
    assert verdict_for(60.0) == "مراقبة"
    assert verdict_for(59.9) == "ضعف"


def test_multimodal_declared_out_of_scope():
    """متعدد الوسائط معلن خارج النطاق — زبدة المنهج: لا تُدّعِ ما لا تقيسه."""
    report = run_frontier()
    mm = next(r for r in report["axes"] if r["axis"] == "multimodal")
    assert mm["score_pct"] is None
    assert "خارج النطاق" in str(mm["verdict"])
    assert "MMMU-Pro" in mm["frontier_analogs"] and "ScreenSpot Pro" in mm["frontier_analogs"]


def test_synthetic_doc_presence_guard():
    """synthlab وثيقة موقّعة ببصمة سلسلة — التفكير الحتمي يقاس منها لا يُفترض."""
    data = json.loads(SYNTHLAB_DOC.read_text(encoding="utf-8"))
    assert data.get("chain_hash"), "بصمة السلسلة شرط التوقيع"
    assert data["passed"] == data["total"], "معمل التوليف كامل النجاح على وثيقته"
