"""اختبارات zyko.benchmarks.multilab — معمل الترقيع متعدد الملفات.

العقود المُختبرة هنا:
- تسعة سيناريوهات على ثلاث فئات، وكلها تمر على البذور الموثقة
- الإيصال حتمي بالبايت: تشغيلان متتاليان ⇒ نفس بصمة السلسلة
- التقرير يمثل نفسه JSON مرتب المفاتيح وجدولًا عربيًا موثقًا
"""

from __future__ import annotations

import json

from zyko.benchmarks.multilab import (
    CATEGORIES,
    CATEGORY_DISCOVERY,
    CATEGORY_EXECUTION,
    CATEGORY_TRANSACTION,
    MultiLabReport,
    run_multilab,
)


class TestCorpus:
    def test_nine_scenarios_three_categories(self) -> None:
        report = run_multilab()
        assert len(report.rows) == 9
        counts = report.category_counts()
        assert counts[CATEGORY_DISCOVERY]["total"] == 3
        assert counts[CATEGORY_EXECUTION]["total"] == 3
        assert counts[CATEGORY_TRANSACTION]["total"] == 3
        assert set(counts) == set(CATEGORIES)

    def test_scenario_ids_unique_and_ordered(self) -> None:
        report = run_multilab()
        ids = [row.scenario_id for row in report.rows]
        assert len(set(ids)) == 9
        assert ids == sorted(ids)
        assert all(i.startswith("ML-") for i in ids)

    def test_all_passed(self) -> None:
        report = run_multilab()
        assert report.all_passed
        assert all(row.passed for row in report.rows)
        assert all(row.detail_ar for row in report.rows)

    def test_each_row_has_evidence(self) -> None:
        report = run_multilab()
        for row in report.rows:
            assert isinstance(row.evidence, dict)
            assert row.category in CATEGORIES


class TestDeterminism:
    def test_receipt_stable_across_runs(self) -> None:
        first = run_multilab()
        second = run_multilab()
        assert first.receipt_sha256 == second.receipt_sha256
        assert first.to_json() == second.to_json()

    def test_receipt_json_sorted_and_parseable(self) -> None:
        report = run_multilab()
        parsed = json.loads(report.to_json())
        assert parsed["all_passed"] is True
        assert parsed["total"] == 9
        assert parsed["categories"][CATEGORY_TRANSACTION]["passed"] == 3

    def test_report_type(self) -> None:
        assert isinstance(run_multilab(), MultiLabReport)


class TestDocumentation:
    def test_table_ar_documents_all_rows(self) -> None:
        text = run_multilab().table_ar()
        assert "معمل الترقيع متعدد الملفات" in text
        assert "المجموع: 9/9" in text
        for row in run_multilab().rows:
            assert row.scenario_id in text
        # الفئات الثلاث مسماة بالعربية في الجدول
        assert "استكشاف" in text and "تنفيذ" in text and "صفقة" in text

    def test_categories_have_arabic_labels(self) -> None:
        assert set(CATEGORIES) == {
            CATEGORY_DISCOVERY,
            CATEGORY_EXECUTION,
            CATEGORY_TRANSACTION,
        }
        from zyko.benchmarks.multilab import CATEGORY_AR

        assert len(CATEGORY_AR) == 3
        assert all(len(v) > 5 for v in CATEGORY_AR.values())
