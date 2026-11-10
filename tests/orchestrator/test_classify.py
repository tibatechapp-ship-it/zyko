"""المكوّن 1 — بوابة classify: 36 اختباراً (6 أنواع + حواف + حتمية 100 تشغيل).

مجموعة الذهب الذهبية: 10 حالات (6 أنواع + 4 حواف) — يجب أن تمر 100%.
الحتمية مُثبتة بـ 100 تشغيل على نفس المدخل (P6: لا ادعاء حتمية بلا إثبات).
"""

from __future__ import annotations

import json

import pytest

from zyko.orchestrator import TaskType, classify


class TestTaskType:
    def test_task_type_values_exact(self):
        assert {t.value for t in TaskType} == {
            "REVIEW",
            "FIX",
            "GENERATE",
            "TRANSPILE",
            "VERIFY",
            "ANALYZE",
            "UNKNOWN",
        }

    def test_priority_documented_fix_first(self):
        # كسر التعادل الموثق: FIX أولاً حتى تُخطَّط «راجع وأصلح» كإصلاح كامل.
        from zyko.orchestrator.classify import PRIORITY

        assert PRIORITY[0] is TaskType.FIX


class TestReview:
    def test_arabic_review_verb(self):
        assert classify("راجع src/main.py").task is TaskType.REVIEW

    def test_arabic_noun_form(self):
        assert classify("أريد مراجعة شاملة للكود").task is TaskType.REVIEW


class TestFix:
    def test_arabic_fix_verb(self):
        assert classify("أصلح main.py").task is TaskType.FIX

    def test_english_word_boundary(self):
        # «fix» بحدود كلمة: لا يطابق «fixture» — لكن هنا الكلمة قائمة بذاتها.
        assert classify("fix the bug in parser.py").task is TaskType.FIX


class TestGenerate:
    def test_arabic_create(self):
        assert classify("أنشئ مشروع ويب جديد").task is TaskType.GENERATE

    def test_english_generate(self):
        assert classify("generate a scaffold for a new project").task is TaskType.GENERATE


class TestTranspile:
    def test_arabic_translate_daad(self):
        assert classify("ترجم main.daad إلى بايثون").task is TaskType.TRANSPILE

    def test_daad_language_name(self):
        assert classify("حوّل هذا الكود إلى ضاد").task is TaskType.TRANSPILE


class TestVerify:
    def test_arabic_verify_receipt(self):
        assert classify("تحقق من الإيصال receipt.json").task is TaskType.VERIFY

    def test_count_beats_single_review_keyword(self):
        # راجع(1) مقابل تحقق+receipt(2) — الأعلى عدداً يفوز لا الأعلى أولوية.
        result = classify("راجع receipt.json وتحقق منه")
        assert result.task is TaskType.VERIFY
        assert result.alternatives == (TaskType.REVIEW,)


class TestAnalyze:
    def test_arabic_analyze(self):
        assert classify("حلّل جودة المستودع").task is TaskType.ANALYZE

    def test_english_baseline_metrics(self):
        assert classify("run baseline metrics on src").task is TaskType.ANALYZE


class TestUnknown:
    def test_empty_string(self):
        assert classify("").task is TaskType.UNKNOWN

    def test_gibberish_no_keywords(self):
        assert classify("الجو جميل اليوم").task is TaskType.UNKNOWN


class TestConfidence:
    def test_single_keyword_is_0_70(self):
        assert classify("راجع src/main.py").confidence == 0.70

    def test_double_keyword_is_0_85(self):
        # «عالج» ⊂ «عاجل» — تجنّبناها عمداً؛ المطابقتان اصلح+bug فقط.
        assert classify("أصلح هذا الـbug في الكود").confidence == 0.85

    def test_unknown_confidence_zero(self):
        assert classify("الجو جميل اليوم").confidence == 0.0


class TestAlternatives:
    def test_mixed_text_reports_alternative(self):
        result = classify("راجع وأصلح main.py")
        assert result.task is TaskType.FIX
        assert result.alternatives == (TaskType.REVIEW,)

    def test_single_type_has_no_alternatives(self):
        assert classify("ترجم main.daad إلى بايثون").alternatives == ()


class TestMatchedKeywords:
    def test_order_follows_table_not_text(self):
        # نص «عالج وأصلح» لكن الترتيب المُبلَّغ بترتيب الجدول: اصلح ثم عالج.
        assert classify("عالج وأصلح الكود").matched_keywords == ("اصلح", "عالج")

    def test_unknown_has_no_keywords(self):
        assert classify("الجو جميل اليوم").matched_keywords == ()


GOLD_SET = [
    # 6 أنواع
    ("راجع src/main.py", TaskType.REVIEW),
    ("أصلح main.py", TaskType.FIX),
    ("أنشئ مشروع ويب جديد", TaskType.GENERATE),
    ("ترجم هذا الملف إلى ضاد", TaskType.TRANSPILE),
    ("تحقق من الإيصال receipt.json", TaskType.VERIFY),
    ("حلّل جودة الكود", TaskType.ANALYZE),
    # 4 حواف
    ("", TaskType.UNKNOWN),
    ("الجو جميل", TaskType.UNKNOWN),
    ("راجع وأصلح main.py", TaskType.FIX),  # تعادل → FIX (خطة تغطي الفعلين)
    ("1234", TaskType.UNKNOWN),
]


class TestGoldSet:
    @pytest.mark.parametrize(("text", "expected"), GOLD_SET)
    def test_gold_case(self, text, expected):
        assert classify(text).task is expected


class TestDeterminism:
    def test_100_runs_identical(self):
        # P6: لا ادعاء حتمية دون إثبات — 100 تشغيل نفس النتيجة بالبايت.
        first = classify("راجع وأصلح main.py وأريد مراجعة التدقيق")
        for _ in range(100):
            assert classify("راجع وأصلح main.py وأريد مراجعة التدقيق") == first

    def test_to_dict_json_roundtrip(self):
        payload = classify("تحقق من الإيصال receipt.json").to_dict()
        restored = json.loads(json.dumps(payload, ensure_ascii=False))
        assert restored == payload
        assert restored["task"] == "VERIFY"

    def test_to_dict_keys_exact(self):
        assert set(classify("أصلح main.py").to_dict()) == {
            "task",
            "confidence",
            "matched_keywords",
            "alternatives",
        }
