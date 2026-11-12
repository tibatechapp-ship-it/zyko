"""اختبارات بنية مختبر التقييم الكبير — العقد 1000 حالة حتمية بالبايت."""

from __future__ import annotations

from zyko.benchmarks.eval1000 import (
    CASES_TOTAL,
    CATEGORY_LABELS,
    STRENGTH_THRESHOLD,
    WATCH_THRESHOLD,
    EvalCase,
    build_eval_cases,
    run_eval1000,
)
from zyko.benchmarks.eval1000_cases import CATEGORY_ORDER


def test_contract_1000_cases():
    cases = build_eval_cases()
    assert len(cases) == CASES_TOTAL == 1000


def test_ids_unique_and_sequential():
    cases = build_eval_cases()
    ids = [c.case_id for c in cases]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "E-0001" and ids[-1] == "E-1000"
    assert ids == [f"E-{i:04d}" for i in range(1, len(ids) + 1)]


def test_all_20_categories_present():
    cases = build_eval_cases()
    seen = {c.category for c in cases}
    assert seen == set(CATEGORY_ORDER) == set(CATEGORY_LABELS.keys())
    assert len(seen) == 20


def test_build_is_byte_deterministic():
    a = build_eval_cases()
    b = build_eval_cases()
    assert [(c.case_id, c.category, c.family, c.title_ar) for c in a] == [
        (c.case_id, c.category, c.family, c.title_ar) for c in b
    ]


def test_thresholds_documented():
    assert STRENGTH_THRESHOLD == 0.95
    assert WATCH_THRESHOLD == 0.85


def test_subset_determinism():
    """عينة 60 حالة مرتين — نفس السلسلة بالبايت (الحتمية بلا كلفة التشغيل الكامل)."""
    cases = build_eval_cases()[:60]
    r1 = run_eval1000(cases=cases)
    r2 = run_eval1000(cases=cases)
    assert r1.chain_hash == r2.chain_hash
    assert r1.to_json() == r2.to_json()


def test_report_shape_and_verdicts():
    cases = build_eval_cases()[:50]
    report = run_eval1000(cases=cases)
    d = report.to_dict()
    assert d["kind"] == "eval1000"
    assert d["total"] == len(cases)
    # عقد ok: العدد التعاقدي مكتمل وكل الحالات ناجحة — العينة الجزئية لا تكتمل
    assert d["ok"] is (d["failed"] == 0 and d["total"] == 1000)
    for stat in d["by_category"].values():
        assert stat["verdict_ar"] in ("قوة", "مراقبة", "ضعف")


def test_no_timestamps_in_receipt():
    cases = build_eval_cases()[:10]
    report = run_eval1000(cases=cases)
    payload = report.to_json()
    assert "seconds" not in payload and "ts" not in payload


def test_case_exception_becomes_honest_failure():
    """استثناء داخل حالة = فشل موثق لا انهيار العدّة."""

    def boom():
        raise RuntimeError("انفجار تجريبي")

    case = EvalCase("E-9999", "gates", "تجربة", "حالة تنفجر", boom)
    report = run_eval1000(cases=(case,))
    assert report.total == 1
    assert report.failed == 1
    assert "انفجار تجريبي" in report.rows[0].detail_ar


def test_stop_on_first_fail_is_diagnostic_door():
    def bad():
        return False, "فشل موثق"

    def good():
        return True, "سليم"

    cases = (
        EvalCase("E-9001", "gates", "تجربة", "فاشل", bad),
        EvalCase("E-9002", "gates", "تجربة", "سليم", good),
    )
    report = run_eval1000(cases=cases, stop_on_first_fail=True)
    assert report.total == 1  # توقف عند الأول
    report_full = run_eval1000(cases=cases)
    assert report_full.total == 2
