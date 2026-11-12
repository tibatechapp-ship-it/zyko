"""اختبارات معمل المُقترِح الحتمي — العدّة نفسها تخضع لعقدها.

المعمَل أداة قياس، وأداة القياس تُقاس: الحالات الستين بأرقامها
التعاقدية، وحتمية الإيصال بالبايت، وحكم الفئات الثلاث.
"""

from __future__ import annotations

import json

from zyko.benchmarks.synthlab import (
    CASES,
    CATEGORY_ORDER,
    LAB_KIND,
    SynthLabReport,
    run_synth_lab,
)

# المعمَل يُشغَّل مرة واحدة للجلسة — العدّة حتمية بالبايت فلا يتغير
# تشغيلها الثاني حرفاً؛ والاختبارات تحاكم الإيصال نفسه لا الزمن.
_REPORT: SynthLabReport | None = None


def _lab() -> SynthLabReport:
    global _REPORT
    if _REPORT is None:
        _REPORT = run_synth_lab()
    return _REPORT


def test_case_count_is_contractual() -> None:
    assert len(CASES) == 60
    ids = [c.case_id for c in CASES]
    assert ids == [f"S-{i + 1:04d}" for i in range(60)]


def test_categories_are_the_declared_three() -> None:
    seen = {c.category for c in CASES}
    assert seen == set(CATEGORY_ORDER)
    counts = {cat: sum(1 for c in CASES if c.category == cat) for cat in CATEGORY_ORDER}
    assert counts["synthesized"] == 30
    assert counts["exhausted"] == 12
    assert counts["honest-limit"] == 18


def test_full_lab_passes_its_own_contracts() -> None:
    report = _lab()
    assert report.ok, f"فشل المعمل: {report.failures}"
    assert report.passed == 60
    assert report.failed == 0
    for stats in report.by_category.values():
        assert stats["passed"] == stats["total"]


def test_lab_receipt_is_deterministic_bytes() -> None:
    report = _lab()
    assert len(report.chain_hash) == 64
    # البصمة تُعاد من الصفوف نفسها — لا زمن ولا عشوائية في التركيب
    import hashlib

    from zyko.benchmarks.synthlab import _judge, _run_case

    payload = "\x1f".join(
        f"{r['case_id']}\x1f{r['verdict']}\x1f{r['winner_expr'] or ''}" for r in report.rows
    )
    assert report.chain_hash == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    # تشغيل مزدوج لحالة كاملة: الإيصال بالبايت متطابق
    case = CASES[0]
    a = _run_case(case)
    b = _run_case(case)
    assert a.to_json() == b.to_json()
    ok_a, _ = _judge(case, a)
    ok_b, _ = _judge(case, b)
    assert ok_a and ok_b


def test_lab_receipt_structure() -> None:
    report = _lab()
    doc = json.loads(report.to_json())
    assert doc["kind"] == LAB_KIND
    assert doc["total"] == 60
    assert len(doc["rows"]) == 60
    for row in doc["rows"]:
        assert row["ok"] is True
        assert row["problem_ar"] == ""
        assert isinstance(row["verdict"], str)
    for banned in ("timestamp", "wall_time"):
        assert banned not in doc


def test_synthesis_rows_have_governed_winners() -> None:
    report = _lab()
    for case, row in zip(CASES, report.rows):
        if case.category != "synthesized":
            continue
        assert row["winner_expr"] is not None
        assert row["verdict"] == "synthesized"


def test_exhaustion_rows_are_full_space_proofs() -> None:
    report = _lab()
    for case, row in zip(CASES, report.rows):
        if case.category != "exhausted":
            continue
        assert row["winner_expr"] is None
        assert row["verdict"] == "exhausted"


def test_reference_receipt_chain_is_live_truth():
    """حارس الحقيقة المرجعية للمعمل: التشغيل الحيّ يطابق الإيصال المرجعي."""
    import json
    from pathlib import Path

    reference = Path(__file__).resolve().parents[1] / (
        "benchmarks/results/synthlab_2026-11-12.json"
    )
    doc = json.loads(reference.read_text(encoding="utf-8"))
    report = _lab()
    assert report.ok
    assert report.total == 60
    assert report.chain_hash == doc["chain_hash"], (
        "بصمة المعمل الحيّ اختلفت عن المرجع — حالات المعمل تغيّرت دلالياً بلا تجديد المرجع"
    )
