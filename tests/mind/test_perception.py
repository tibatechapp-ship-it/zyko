"""اختبارات وحدة الإدراك — تطبيع وتصنيف ومعايير نجاح، حتمية بالبايت."""

from __future__ import annotations

import pytest

from zyko.mind.perception import normalize_goal, perceive
from zyko.orchestrator.classify import TaskType


class TestNormalize:
    def test_strip_and_collapse(self):
        assert normalize_goal("  انشئ   مشروع\nمهام  ") == "انشئ مشروع مهام"

    def test_preserves_arabic(self):
        assert normalize_goal("اًنشئ إِيصالًا") == "اًنشئ إِيصالًا"

    def test_deterministic(self):
        g = "انشئ   مشروع  قائمة  مهام"
        assert normalize_goal(g) == normalize_goal(g)


class TestPerceive:
    def test_generate_kind(self):
        p = perceive("انشئ مشروع قائمة مهام")
        assert p.kind is TaskType.GENERATE
        assert p.goal == "انشئ مشروع قائمة مهام"

    def test_fix_kind_with_path(self):
        p = perceive("اصلح الملف src/app.py")
        assert p.kind is TaskType.FIX
        assert p.target_path == "src/app.py"

    def test_generate_criteria_table(self):
        p = perceive("انشئ مشروع قائمة مهام")
        kinds = [c.kind for c in p.criteria]
        assert kinds.count("artifact") == 1
        assert kinds.count("score") == 1
        assert kinds[-2:] == [
            ("always" if "بيانات" in c.text_ar else "always") for c in p.criteria[-2:]
        ]

    def test_identity_criteria_always_present(self):
        p = perceive("انشئ مشروع قائمة مهام")
        texts = [c.text_ar for c in p.criteria]
        assert "الناتج خالٍ من بيانات شخصية" in texts
        assert "النص العربي سليم الاتجاه بلا أخطاء RTL" in texts

    def test_explicit_test_criterion(self):
        p = perceive("انشئ مشروع مهام مع اختبارات")
        texts = [c.text_ar for c in p.criteria]
        assert "اختبارات المشروع موجودة على القرص" in texts

    def test_explicit_readme_criterion(self):
        p = perceive("انشئ مشروع مهام مع توثيق")
        texts = [c.text_ar for c in p.criteria]
        assert any("README.md" in t for t in texts)

    def test_no_duplicate_explicit_criteria(self):
        p = perceive("انشئ مشروع مهام مع اختبارات واختبارات إضافية")
        texts = [c.text_ar for c in p.criteria]
        assert texts.count("اختبارات المشروع موجودة على القرص") == 1

    def test_empty_goal_is_safe_unknown(self):
        p = perceive("   ")
        assert p.kind is TaskType.UNKNOWN
        assert p.classification.confidence == 0.0

    def test_non_string_goal_is_safe(self):
        p = perceive(12345)
        assert p.kind is TaskType.UNKNOWN
        assert "12345" in p.goal

    def test_none_goal_is_safe(self):
        p = perceive(None)
        assert p.kind is TaskType.UNKNOWN

    def test_determinism_bytes(self):
        goal = "انشئ مشروع قائمة مهام مع واجهة سطر أوامر"
        a, b = perceive(goal), perceive(goal)
        assert [c.text_ar for c in a.criteria] == [c.text_ar for c in b.criteria]
        assert a.kind == b.kind
        assert a.target_path == b.target_path
        assert a.classification.confidence == b.classification.confidence

    @pytest.mark.skipif(
        __import__("sys").platform == "win32",
        reason="فجوة ويندوز الموثقة (تقطيع المسارات/دلالات العدّاء على ويندوز) — قيد مخطط لا إخفاء",
    )
    def test_is_existing_task_contract(self):
        import os
        import tempfile

        p = perceive("اصلح الملف nonexist_xyz.py")
        assert not p.is_existing_task  # المسار غير موجود على القرص
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "app.py")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            p2 = perceive(f"اصلح الملف {f}")
            assert p2.is_existing_task
