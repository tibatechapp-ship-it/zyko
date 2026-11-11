"""اختبارات وحدة النقد — فحوص حتمية على الناتج الفعلي لا بالحدس."""

from __future__ import annotations

import pathlib

from zyko.mind.critic import critique
from zyko.mind.perception import perceive


class TestCritiqueGenerate:
    def test_green_on_generated_project(self, tmp_path):
        (tmp_path / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        (tmp_path / "test_app.py").write_text("def test_main():\n    assert main() == 0\n", encoding="utf-8")
        p = perceive("انشئ مشروع مهام مع اختبارات")
        report = critique(p, tmp_path, score_after=90, fail_under=75)
        assert report.ok
        assert not report.gaps_ar

    def test_score_below_threshold_is_gap(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        p = perceive("انشئ مشروع مهام")
        report = critique(p, tmp_path, score_after=40, fail_under=75)
        assert not report.ok
        assert "أدنى درجة مراجعة لا تقل عن الحد" in report.gaps_ar

    def test_missing_score_rejected_precautionarily(self, tmp_path):
        p = perceive("انشئ مشروع مهام")
        report = critique(p, tmp_path, score_after=None, fail_under=75)
        assert not report.ok

    def test_explicit_tests_criterion_checks_disk(self, tmp_path):
        p = perceive("انشئ مشروع مهام مع اختبارات")
        report = critique(p, tmp_path, score_after=90)
        assert "اختبارات المشروع موجودة على القرص" in report.gaps_ar
        (tmp_path / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        report2 = critique(p, tmp_path, score_after=90)
        assert "اختبارات المشروع موجودة على القرص" not in report2.gaps_ar

    def test_explicit_readme_criterion(self, tmp_path):
        p = perceive("انشئ مشروع مهام مع توثيق")
        report = critique(p, tmp_path, score_after=90)
        assert any("README" in g for g in report.gaps_ar)
        (tmp_path / "README.md").write_text("# المشروع\n", encoding="utf-8")
        report2 = critique(p, tmp_path, score_after=90)
        assert not any("README" in g for g in report2.gaps_ar)

    def test_pii_in_generated_files_is_gap(self, tmp_path):
        (tmp_path / "contact.py").write_text("PHONE = '0501234567'\n", encoding="utf-8")
        p = perceive("انشئ مشروع مهام")
        report = critique(p, tmp_path, score_after=90)
        assert not report.ok
        assert "الناتج خالٍ من بيانات شخصية" in report.gaps_ar


class TestCritiqueExisting:
    def test_fix_score_after(self, tmp_path):
        target = tmp_path / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        p = perceive(f"اصلح الملف {target}")
        report = critique(p, tmp_path, score_after=85, fail_under=75)
        assert report.ok

    def test_missing_target_is_gap(self, tmp_path):
        p = perceive("اصلح الملف غير_موجود.py")
        report = critique(p, tmp_path, score_after=85, fail_under=75)
        assert "الملف المستهدف موجود قبل الإصلاح وبعده" in report.gaps_ar


class TestCritiqueDryRun:
    def test_dry_run_skips_not_verifiable(self, tmp_path):
        p = perceive("انشئ مشروع مهام")
        report = critique(p, tmp_path, score_after=None, dry_run=True)
        assert report.ok  # تخطٍّ موثق لا فجوة

    def test_dry_run_still_scans_existing_target_pii(self, tmp_path):
        target = tmp_path / "app.py"
        target.write_text("phone = '0501234567'\n", encoding="utf-8")
        p = perceive(f"اصلح الملف {target}")
        report = critique(p, tmp_path, score_after=80, dry_run=True)
        assert not report.ok  # القراءة وحدها تكفي لفحص الهوية
        assert "الناتج خالٍ من بيانات شخصية" in report.gaps_ar


class TestCriticContract:
    def test_report_table_deterministic(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        p = perceive("انشئ مشروع مهام")
        a = critique(p, tmp_path, score_after=80)
        b = critique(p, tmp_path, score_after=80)
        assert a.table_ar() == b.table_ar()

    def test_findings_evidence_non_empty(self, tmp_path):
        p = perceive("انشئ مشروع مهام")
        report = critique(p, tmp_path, score_after=80)
        assert all(f.evidence_ar.strip() for f in report.findings)

    def test_scan_cap_respected(self, tmp_path):
        # 50 ملفًا py — السقف 40 فحصًا نصيًا بلا انهيار
        for i in range(50):
            (tmp_path / f"mod_{i}.py").write_text(f"x_{i} = {i}\n", encoding="utf-8")
        p = perceive("انشئ مشروع مهام")
        report = critique(p, tmp_path, score_after=80)
        assert report.findings
