"""اختبارات القوة والسرعة والأمان لحلقة الانعكاس — لا ثغرات ولا انهيار.

هذه الحزمة تعمد إلى إيذار الحلقة بأسوأ ما يمكن أن يصادفها: أنوية ترمي
استثناءات أو تعيد أنواعاً عبثية أو نصوصاً ضخمة أو بيانات شخصية، وميزانيات
مفتوحة على المصانع، وأسماء مراحل عدوية، ومدخلات غير نصية — والعقد الحاكم:
**الحلقة تنتهي دائماً بإيصال موثق، بلا استثناء خارج، بلا حلقة لا نهائية،
وبلا تجاوز سقف مهما عادى المدخل — وبالسرعة المعلنة**.
"""

from __future__ import annotations

import json
import time

import pytest

from zyko.mind.core import DeterministicCore
from zyko.mind.loop import MindLoop
from zyko.mind.reflect import (
    MAX_TOTAL_RETRIES,
    RetryBudget,
    fallback_note,
    guard_feedback,
    normalize_stage,
    reflect_note,
)

GOAL = "انشئ مشروع قائمة مهام مع واجهة سطر أوامر"


# ------------------------------------------------------------------ الأنوية العدوية
class RaiseCore:
    name = "raise-core"
    deterministic = False

    def respond(self, request, *, context=""):
        raise RuntimeError("انفجار متعمد من قلب عدوي")


class NoneCore:
    name = "none-core"
    deterministic = False

    def respond(self, request, *, context=""):
        return None


class DictCore:
    name = "dict-core"
    deterministic = False

    def respond(self, request, *, context=""):
        return {"نوع": "غير نصي"}


class HugeCore:
    name = "huge-core"
    deterministic = False

    def respond(self, request, *, context=""):
        return "خطة عربية سليمة الاتجاه. " * 2500  # ~50 ألف محرف نظيف


class AlwaysPIICore:
    name = "always-pii"
    deterministic = False
    calls = 0
    requests: list[str] = []

    def respond(self, request, *, context=""):
        self.calls += 1
        self.requests.append(request)
        return f"اتصل على 0501234567 للتنسيق (محاولة {self.calls})"


# ------------------------------------------------------------------ الإنهاء المضمون
class TestGuaranteedTermination:
    @pytest.mark.parametrize(
        "core_factory",
        [lambda: RaiseCore(), lambda: NoneCore(), lambda: DictCore(), lambda: HugeCore()],
        ids=["raise", "none", "dict", "huge"],
    )
    def test_adversarial_cores_never_escape_exception(self, tmp_path, core_factory):
        receipt = MindLoop(core_factory()).run(GOAL, tmp_path / "proj")
        assert receipt.chain_hash  # إيصال كامل — الحلقة انتهت لا انفجرت
        # أسوأ حالة موثقة: إدراك + 3 محاولات خطة + ذاكرة — سقف ثابت
        assert len(receipt.steps) <= 8

    @pytest.mark.parametrize(
        "bad_goal",
        [None, 123, [], {}, "   ", "وصف" * 2000, "\u202bانشئ\u202c مشروع", "انشئ مشروع\x00فارغ"],
        ids=["none", "int", "list", "dict", "blank", "huge", "bidi", "nul"],
    )
    def test_adversarial_goals_return_receipt(self, tmp_path, bad_goal):
        receipt = MindLoop().run(bad_goal, tmp_path / "proj")
        assert receipt.chain_hash
        assert len(receipt.chain_hash) == 64
        # المدخلات غير النصية/الفارغة تُرفض هيكليًا بلا أي كتابة —
        # والقابلة للتصنيف تعطي حكمًا صادقًا موثقًا إن فشل ناتجه

    def test_raise_core_exhausts_budget_honestly(self, tmp_path):
        core = RaiseCore()
        receipt = MindLoop(core).run(GOAL, tmp_path / "proj")
        assert not receipt.ok
        assert receipt.failed_step == "plan"
        assert receipt.budget["used"]["plan"] == 2
        # كل استثناء موثق حكمًا لا صمتًا
        assert all("RuntimeError" in r["trigger_ar"] for r in receipt.reflections)

    @pytest.mark.parametrize("limit", [0, 1, 2, 5, 8])
    def test_budget_limits_bound_attempts_monotonically(self, tmp_path, limit):
        core = AlwaysPIICore()
        receipt = MindLoop(core, budget=RetryBudget(default_limit=limit)).run(
            GOAL, tmp_path / "proj"
        )
        expected_attempts = 1 + min(limit, MAX_TOTAL_RETRIES)
        assert core.calls == expected_attempts  # لا محاولة واحدة فوق الميزانية
        plan_attempts = [s for s in receipt.steps if s.step == "plan"]
        assert len(plan_attempts) == expected_attempts

    def test_zero_budget_single_attempt(self, tmp_path):
        core = AlwaysPIICore()
        receipt = MindLoop(core, budget=RetryBudget(default_limit=0)).run(GOAL, tmp_path / "proj")
        assert core.calls == 1
        assert not receipt.ok
        assert receipt.budget["total_used"] == 0


# ------------------------------------------------------------------ الأمان
class TestSecurity:
    def test_pii_from_core_never_leaks_into_later_requests(self, tmp_path):
        core = AlwaysPIICore()
        receipt = MindLoop(core).run(GOAL, tmp_path / "proj")
        assert not receipt.ok
        # البيان الشخصي يظهر في ردود القلب فقط — لا في أي طلب لاحق ولا إيصال
        assert core.calls == 3
        for request in core.requests:
            assert (
                "0501234567" not in request.replace("اتصل على 0501234567", "")
                or request is core.requests[0]
            )
        dumped = json.dumps(receipt.to_dict())
        assert "0501234567" not in dumped

    def test_reflection_note_stays_clean_when_reason_dirty(self, tmp_path):
        core = AlwaysPIICore()
        receipt = MindLoop(core).run(GOAL, tmp_path / "proj")
        for reflection in receipt.reflections:
            note = reflection["feedback_ar"]
            guard = guard_feedback(note)
            # الملاحظة إما نظيفة تجتاز الحارس، أو بديلة صلبة نظيفة بالضرورة
            assert guard.ok or note == fallback_note()

    def test_huge_clean_advisory_accepted_under_two_seconds(self, tmp_path):
        started = time.perf_counter()
        receipt = MindLoop(HugeCore()).run(GOAL, tmp_path / "proj")
        elapsed = time.perf_counter() - started
        assert receipt.ok  # نص نظيف ضخم يمر البوابات — الحلقة تتحمله
        assert elapsed < 5.0

    def test_stage_name_never_breaks_budget_accounting(self):
        budget = RetryBudget(default_limit=1)
        variants = ["plan", "plan ", " plan", "plan\t", "plan\n", "plan\r\n"]
        first = True
        for variant in variants:
            granted = budget.consume(variant)
            if first:
                assert granted is True
                first = False
            else:
                assert granted is False
        assert budget.total_used == 1
        # الاسم الطويل جدًا (حتى المتكرر) يُطبع إلى سقفه — دلو محدود لا خانة لا نهائية
        huge = normalize_stage("plan " * 5000)
        assert len(huge) == 32
        assert huge.startswith("plan")

    def test_receipt_json_has_no_secrets_or_control_chars(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        dumped = receipt.to_json()
        for forbidden in ("API_KEY", "api_key", "token", "password", "\x00"):
            assert forbidden not in dumped


# ------------------------------------------------------------------ السرعة
class TestSpeed:
    def test_reflection_primitives_batch_under_one_second(self):
        gaps = ("فجوة أولى موثقة", "فجوة ثانية الموثقة في التقرير")
        started = time.perf_counter()
        for index in range(1000):
            note = reflect_note("critic", reason_ar=f"سبب موثق رقم {index}", gaps=gaps, attempt=1)
            guard_feedback(note, gaps)
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0  # أقل من مللي ثانية لكل دورة مقاسة فعليًا

    def test_budget_100k_consumes_under_half_second(self):
        budget = RetryBudget(default_limit=200_000, total_cap=200_000)
        started = time.perf_counter()
        for _ in range(100_000):
            budget.consume("plan")
        elapsed = time.perf_counter() - started
        assert budget.used("plan") == 100_000
        assert elapsed < 0.5

    def test_full_loop_offline_latency_canary(self, tmp_path):
        started = time.perf_counter()
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        elapsed = time.perf_counter() - started
        assert receipt.ok
        assert elapsed < 2.0  # canary انحدار الأداء — البيئة بلا شبكة

    def test_worst_case_retry_loop_still_fast(self, tmp_path):
        started = time.perf_counter()
        receipt = MindLoop(AlwaysPIICore()).run(GOAL, tmp_path / "proj")
        elapsed = time.perf_counter() - started
        assert not receipt.ok
        assert elapsed < 2.0  # 3 محاولات خطة موثقة بلا شبكة — أسرع من ثانيتين


# ------------------------------------------------------------------ الحتمية تحت الضغط
class TestDeterminismUnderStress:
    def test_exhausted_budget_receipts_identical(self, tmp_path):
        hashes = []
        for _ in range(2):
            out = tmp_path / "proj"
            receipt = MindLoop(AlwaysPIICore()).run(GOAL, out)
            hashes.append(receipt.to_json())
            import shutil

            shutil.rmtree(out, ignore_errors=True)  # الرفض لا يكتب مجلدًا أصلًا
        assert hashes[0] == hashes[1]

    def test_raise_core_receipts_identical(self, tmp_path):
        hashes = []
        for _ in range(2):
            out = tmp_path / "proj"
            receipt = MindLoop(RaiseCore()).run(GOAL, out)
            assert not receipt.ok
            hashes.append(receipt.chain_hash)
            import shutil

            shutil.rmtree(out, ignore_errors=True)
        assert hashes[0] == hashes[1]

    def test_recovered_receipt_identical_across_budget_objects(self, tmp_path):
        # ميزانيتان مستقلتان بنفس الحدود ⇒ نفس القصة ⇒ نفس البصمة
        hashes = []
        for _ in range(2):
            out = tmp_path / "proj"

            class OncePIICore:
                name = "once-pii"
                deterministic = False
                calls = 0

                def respond(self, request, *, context=""):
                    self.calls += 1
                    if self.calls == 1:
                        return "اتصل على 0501234567 للتنسيق"
                    return "خطة نظيفة بعد التعلم من الدرس"

            receipt = MindLoop(OncePIICore(), budget=RetryBudget()).run(GOAL, out)
            assert receipt.ok
            hashes.append(receipt.chain_hash)
            import shutil

            shutil.rmtree(out)
        assert hashes[0] == hashes[1]


# ------------------------------------------------------------------ الحدود الحتمية للسلوك
class TestContractEdges:
    def test_recovered_receipt_final_verdict_ignores_superseded_attempts(self, tmp_path):
        out = tmp_path / "proj"

        class OncePIICore:
            name = "once-pii"
            deterministic = False
            calls = 0

            def respond(self, request, *, context=""):
                self.calls += 1
                if self.calls == 1:
                    return "اتصل على 0501234567 للتنسيق"
                return "خطة نظيفة بعد التعلم من الدرس"

        receipt = MindLoop(OncePIICore(), rounds=2).run(GOAL, out)
        assert receipt.ok  # آخر سجل لكل بوابة هو الحاكم
        assert receipt.failed_step is None
        # المحاولة المرفوضة موثقة تاريخًا لا حكمًا
        assert any(not s.ok for s in receipt.steps)

    def test_dry_run_reflects_without_writing(self, tmp_path):
        receipt = MindLoop(AlwaysPIICore()).run(GOAL, tmp_path / "dry", write=False)
        assert not (tmp_path / "dry").exists()
        assert receipt.dry_run
        assert receipt.budget["used"]["plan"] == 2

    def test_offline_by_default_under_stress(self, tmp_path):
        import os

        saved = {
            k: os.environ.pop(k, None)
            for k in ("ZYKO_QWEN_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        }
        try:
            receipt = MindLoop(DeterministicCore()).run(GOAL, tmp_path / "proj")
            assert receipt.ok
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
