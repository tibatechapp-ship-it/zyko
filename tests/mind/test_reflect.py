"""اختبارات وحدة الانعكاس وإعادة المحاولة — الحرّاس والميزانية والملاحظة.

العقد الحاكم: كل حارس فحص حتمي على ناتج مرحلة، وكل ميزانية سقف صارم
لا يُتجاوز، وكل ملاحظة منعكسة حتمية بالبايت تحفظ معنى الفجوات —
وكلها بلا شبكة ولا نموذج ولا عشوائية.
"""

from __future__ import annotations

import json

import pytest

from zyko.ai.brains import GateVerdict
from zyko.mind.core import DeterministicCore, ScriptedCore
from zyko.mind.loop import MindLoop
from zyko.mind.perception import perceive
from zyko.mind.planner import MindPlan, MindStep, build_plan
from zyko.mind.reflect import (
    MAX_FEEDBACK_CHARS,
    MAX_STAGE_NAME_CHARS,
    MAX_TOTAL_RETRIES,
    Reflection,
    RetryBudget,
    condense_feedback,
    fallback_note,
    gate_verdict_summary,
    guard_execution,
    guard_feedback,
    guard_perception,
    guard_plan,
    normalize_stage,
    reflect_note,
)

GOAL = "انشئ مشروع قائمة مهام مع واجهة سطر أوامر"


def _real_perception():
    return perceive(GOAL)


def _real_plan():
    return build_plan(_real_perception(), DeterministicCore())


# ------------------------------------------------------------------ التطبيع
class TestNormalizeStage:
    def test_none_and_empty_get_safe_name(self):
        assert normalize_stage(None) == "غير-مسماة"
        assert normalize_stage("") == "غير-مسماة"
        assert normalize_stage("   ") == "غير-مسماة"

    def test_whitespace_folded(self):
        assert normalize_stage("  plan \t\n mid  ") == "plan mid"

    def test_huge_name_capped(self):
        name = normalize_stage("x" * 10_000)
        assert len(name) == MAX_STAGE_NAME_CHARS

    @pytest.mark.parametrize("raw", [123, ["plan"], {"a": 1}, b"plan"])
    def test_non_string_coerced(self, raw):
        assert isinstance(normalize_stage(raw), str)
        assert len(normalize_stage(raw)) <= MAX_STAGE_NAME_CHARS


# ------------------------------------------------------------------ الميزانية
class TestRetryBudget:
    def test_default_limit_and_consume_flow(self):
        budget = RetryBudget()
        assert budget.limit("plan") == 2
        assert budget.can_retry("plan")
        assert budget.consume("plan") is True
        assert budget.consume("plan") is True
        assert budget.can_retry("plan") is False
        assert budget.consume("plan") is False  # لا سالب ولا تجاوز أبدًا
        assert budget.used("plan") == 2

    def test_per_stage_override_wins(self):
        budget = RetryBudget(default_limit=1, per_stage={"plan": 5})
        assert budget.limit("plan") == 5
        assert budget.limit("critic") == 1

    def test_stage_isolation(self):
        budget = RetryBudget(default_limit=1)
        assert budget.consume("plan") is True
        assert budget.can_retry("plan") is False
        assert budget.can_retry("critic") is True  # عزل كامل بين المراحل

    def test_total_cap_hard_stops_every_stage(self):
        budget = RetryBudget(default_limit=10, total_cap=2)
        assert budget.consume("plan") and budget.consume("plan")
        assert budget.can_retry("plan") is False
        assert budget.can_retry("critic") is False  # السقف الكلي يضرب الجميع
        assert budget.total_used == 2

    def test_adversarial_names_share_one_bucket(self):
        budget = RetryBudget(default_limit=1)
        assert budget.consume("plan") is True
        # كل صور الاسم العدوية تطبَّع إلى نفس الدلو — لا خانة ميزانية جديدة
        for variant in ("plan ", " plan", "plan\t", "plan\n\n", "plan\r\n"):
            assert budget.consume(variant) is False
        assert budget.used("plan") == 1

    def test_invalid_limits_clamped_not_raised(self):
        budget = RetryBudget(default_limit=-5, per_stage={"plan": "خامس", "x": None}, total_cap=-1)
        assert budget.default_limit == 0
        assert budget.limit("plan") == 0
        assert budget.total_cap == 0
        assert budget.can_retry("plan") is False
        assert budget.consume("plan") is False

    def test_to_dict_deterministic_and_sorted(self):
        b1 = RetryBudget(per_stage={"critic": 3, "plan": 1})
        b2 = RetryBudget(per_stage={"critic": 3, "plan": 1})
        b1.consume("plan")
        b2.consume("plan")
        assert b1.to_dict() == b2.to_dict()
        keys = list(b1.to_dict()["used"])
        assert keys == sorted(keys)

    def test_to_dict_json_round_trip(self):
        budget = RetryBudget()
        budget.consume("critic")
        data = json.loads(json.dumps(budget.to_dict()))
        assert data["used"] == {"critic": 1}
        assert data["total_used"] == 1


# ------------------------------------------------------------------ حرّاس الإدراك والخطة
class TestGuardPerception:
    def test_real_perception_passes(self):
        guard = guard_perception(_real_perception())
        assert guard.ok
        assert "GENERATE" in guard.reason_ar

    def test_unknown_goal_fails_with_arabic_reason(self):
        perception = perceive("قائمة مهام عادية بلا أمر")
        guard = guard_perception(perception)
        assert not guard.ok
        assert "غير معروف" in guard.reason_ar

    def test_identity_criteria_missing_fails(self):
        base = _real_perception()
        stripped = type(base)(
            goal=base.goal,
            classification=base.classification,
            criteria=tuple(c for c in base.criteria if c.kind != "always"),
            target_path=base.target_path,
        )
        guard = guard_perception(stripped)
        assert not guard.ok
        assert "الهوية" in guard.reason_ar

    def test_zero_confidence_fails(self):
        base = _real_perception()
        bumped = type(base)(
            goal=base.goal,
            classification=type(base.classification)(
                task=base.classification.task,
                confidence=0.0,
                matched_keywords=base.classification.matched_keywords,
                alternatives=base.classification.alternatives,
            ),
            criteria=base.criteria,
            target_path=base.target_path,
        )
        assert not guard_perception(bumped).ok


class TestGuardPlan:
    def test_real_plan_passes(self):
        guard = guard_plan(_real_plan(), _real_perception())
        assert guard.ok
        assert "مطابق للجدول الحتمي" in guard.reason_ar

    def test_route_mismatch_rejected(self):
        plan = MindPlan(
            goal=GOAL,
            kind=_real_perception().kind,
            steps=(MindStep(index=1, title_ar="خطوة", tool="orchestrator", acceptance_ar="سليم"),),
            advisory="نص",
            core_name="c",
            deterministic=True,
            verdicts=(GateVerdict(gate="core", passed=True, details_ar="نص"),),
        )
        guard = guard_plan(plan, _real_perception())
        assert not guard.ok
        assert "لا يطابق الجدول الحتمي" in guard.reason_ar

    def test_non_sequential_indices_rejected(self):
        perception = _real_perception()
        plan = MindPlan(
            goal=GOAL,
            kind=perception.kind,
            steps=(
                MindStep(index=2, title_ar="أ", tool="pipeline", acceptance_ar="أ"),
                MindStep(index=3, title_ar="ب", tool="critic", acceptance_ar="ب"),
                MindStep(index=4, title_ar="ج", tool="baseline", acceptance_ar="ج"),
            ),
            advisory="نص",
            core_name="c",
            deterministic=True,
            verdicts=(GateVerdict(gate="core", passed=True, details_ar="نص"),),
        )
        guard = guard_plan(plan, perception)
        assert not guard.ok
        assert "غير متسلسل" in guard.reason_ar

    def test_failed_verdicts_named_in_reason(self):
        plan = MindPlan(
            goal=GOAL,
            kind=_real_perception().kind,
            steps=(),
            advisory="",
            core_name="c",
            deterministic=True,
            verdicts=(GateVerdict(gate="pii", passed=False, details_ar="بيان شخصي"),),
        )
        guard = guard_plan(plan)
        assert not guard.ok
        assert "pii" in guard.reason_ar and "بيان شخصي" in guard.reason_ar

    def test_without_perception_skips_route_check(self):
        guard = guard_plan(_real_plan())
        assert guard.ok  # الفحص الهيكلي وحده يكفي حين لا يُمرر الإدراك


# ------------------------------------------------------------------ حرس التنفيذ
class TestGuardExecution:
    def _run_receipt(self, tmp_path):
        return MindLoop().run(GOAL, tmp_path / "proj")

    def test_real_execution_passes(self, tmp_path):
        receipt = self._run_receipt(tmp_path)
        record = next(s for s in receipt.steps if s.step == "execute")
        guard = guard_execution(record, tmp_path / "proj", write=True)
        assert guard.ok
        assert "موجودة على القرص" in guard.reason_ar

    def test_missing_evidence_file_rejected(self, tmp_path):
        out = tmp_path / "proj"
        receipt = MindLoop().run(GOAL, out)
        record = next(s for s in receipt.steps if s.step == "execute")
        victim = sorted(out.rglob("*.py"))[0]
        victim.unlink()
        guard = guard_execution(record, out, write=True)
        assert not guard.ok
        assert "بلا ملف على القرص" in guard.reason_ar

    def test_dry_run_documents_skip(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "dry", write=False)
        record = next(s for s in receipt.steps if s.step == "execute")
        guard = guard_execution(record, tmp_path / "dry", write=False)
        assert guard.ok
        assert "تشغيل جاف" in guard.reason_ar

    def test_failed_record_rejected_with_details(self):
        class Fake:
            ok = False
            evidence = {}
            details_ar = "انفجر التنفيذ"

        guard = guard_execution(Fake())
        assert not guard.ok
        assert "انفجر التنفيذ" in guard.reason_ar

    def test_write_mode_empty_evidence_rejected(self):
        class Fake:
            ok = True
            evidence = {}
            details_ar = "سليم ظاهريًا"

        guard = guard_execution(Fake(), write=True)
        assert not guard.ok
        assert "لا أدلة موقعة" in guard.reason_ar

    def test_absolute_evidence_paths_resolved(self, tmp_path):
        target = tmp_path / "app.py"
        target.write_text("print('سلام')\n", encoding="utf-8")
        from zyko.ai.receipt import hash_file

        class Fake:
            ok = True
            evidence = {str(target): hash_file(target)}
            details_ar = "سليم"

        assert guard_execution(Fake(), write=True).ok


# ------------------------------------------------------------------ حارس الملاحظة والتكثيف
class TestGuardFeedback:
    def test_clean_note_passes(self):
        note = reflect_note("plan", reason_ar="سبب موثق", gaps=("فجوة أولى",), attempt=1)
        guard = guard_feedback(note, ("فجوة أولى",))
        assert guard.ok

    def test_pii_note_rejected(self):
        guard = guard_feedback("ملاحظة — اتصل على 0501234567 للتنسيق")
        assert not guard.ok
        assert "بيانًا شخصيًا" in guard.reason_ar

    def test_over_cap_rejected(self):
        note = "ط" * (MAX_FEEDBACK_CHARS + 1)
        guard = guard_feedback(note)
        assert not guard.ok
        assert "فوق السقف" in guard.reason_ar

    def test_missing_gap_preserves_meaning_check(self):
        guard = guard_feedback("ملاحظة بلا الفجوة المطلوبة", ("فجوة النسية",))
        assert not guard.ok
        assert "الفجوة المفقودة" in guard.reason_ar

    def test_empty_note_rejected(self):
        assert not guard_feedback("   ").ok
        assert not guard_feedback(None).ok

    def test_non_string_coerced(self):
        assert guard_feedback(12345).ok  # نص مشتق قصير نظيف


class TestCondenseFeedback:
    def test_gaps_never_cut_even_with_huge_reason(self):
        reason = "س" * 5_000
        gaps = ("فجوة النسخ الطويل الموثقة جدًا في المشروع",)
        text = condense_feedback(reason, gaps, budget=MAX_FEEDBACK_CHARS)
        assert len(text) <= MAX_FEEDBACK_CHARS
        assert gaps[0] in text  # المعنى محفوظ كاملًا

    def test_small_budget_keeps_gaps_only(self):
        gaps = ("فجوة أولى؛ فجوة ثانية مفصلة",)
        text = condense_feedback("سبب", gaps, budget=10)
        assert text.startswith("الفجوات: ")
        assert "فجوة ثانية مفصلة" in text

    def test_no_gaps_returns_condensed_reason(self):
        text = condense_feedback(" " + "سبب  مفروق " * 100, ())
        assert len(text) == MAX_FEEDBACK_CHARS  # السقف على النثر
        assert text.startswith("سبب مفروق")

    def test_deterministic_by_the_byte(self):
        a = condense_feedback("سبب", ("فجوة",))
        b = condense_feedback("سبب", ("فجوة",))
        assert a == b


class TestReflectNote:
    def test_contains_stage_attempt_and_directive(self):
        note = reflect_note("plan", reason_ar="سبب", gaps=(), attempt=3)
        assert "plan" in note and "المحاولة 3" in note
        assert "أعد المحاولة" in note

    def test_gap_directive_differs(self):
        note = reflect_note("critic", reason_ar="سبب", gaps=("فجوة",), attempt=1)
        assert "علّم من هذه الفجوات" in note
        assert "فجوة" in note

    def test_bounded_even_with_adversarial_stage(self):
        note = reflect_note("س" * 10_000, reason_ar="س" * 10_000, gaps=(), attempt=1)
        assert len(note) <= MAX_FEEDBACK_CHARS

    def test_gaps_survive_adversarial_reason(self):
        gaps = tuple(f"فجوة رقم {i} نصها الطويل الموثق" for i in range(20))
        note = reflect_note("critic", reason_ar="س" * 10_000, gaps=gaps, attempt=2)
        for gap in gaps:
            assert gap in note  # كل فجوة كاملة — الضغط لا يمحو المعنى

    def test_prose_cap_exempts_preserved_gap_bytes(self):
        # فجوات كثيرة تتجاوز السقف: الملاحظة تُقبل ما دام النثر (عدا الفجوات)
        # تحت السقف — السقف عقد على النثر لا على المعنى
        gaps = tuple(f"فجوة رقم {i} نصها الطويل الموثق" for i in range(20))
        note = reflect_note("critic", reason_ar="سبب", gaps=gaps, attempt=1)
        assert len(note) > MAX_FEEDBACK_CHARS
        assert guard_feedback(note, gaps).ok

    def test_non_numeric_attempt_clamped(self):
        assert "المحاولة 1" in reflect_note("plan", reason_ar="س", gaps=(), attempt="خامس")
        assert "المحاولة 1" in reflect_note("plan", reason_ar="س", gaps=(), attempt=-3)

    def test_deterministic_by_the_byte(self):
        a = reflect_note("plan", reason_ar="سبب", gaps=("فجوة",), attempt=2)
        b = reflect_note("plan", reason_ar="سبب", gaps=("فجوة",), attempt=2)
        assert a == b


class TestHelpers:
    def test_fallback_note_constant_and_clean(self):
        assert fallback_note() == fallback_note()
        assert guard_feedback(fallback_note()).ok

    def test_gate_verdict_summary_lists_failures_in_order(self):
        verdicts = (
            GateVerdict(gate="core", passed=True, details_ar="ناجح"),
            GateVerdict(gate="pii", passed=False, details_ar="بيان"),
            GateVerdict(gate="rtl", passed=False, details_ar="اتجاه"),
        )
        summary = gate_verdict_summary(verdicts)
        assert summary.index("pii") < summary.index("rtl")
        assert "ناجح" not in summary

    def test_gate_verdict_summary_all_pass(self):
        assert gate_verdict_summary((GateVerdict(gate="pii", passed=True),)) == "كل البوابات ناجحة"

    def test_reflection_to_dict_types(self):
        data = Reflection(
            stage="plan", attempt=2, trigger_ar="سبب", feedback_ar="درس", retried=True
        ).to_dict()
        assert data["attempt"] == 2 and data["retried"] is True
        assert set(data) == {"stage", "attempt", "trigger_ar", "feedback_ar", "retried"}


# ------------------------------------------------------------------ التكامل مع الحلقة
class TestLoopIntegration:
    def test_receipt_carries_budget_even_without_reflections(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        assert receipt.reflections == []
        assert receipt.budget["default_limit"] == 2
        assert receipt.budget["total_used"] == 0
        assert "reflections" in receipt.to_dict()
        assert receipt.to_dict()["budget"]["total_cap"] == MAX_TOTAL_RETRIES

    def test_injected_budget_respected(self, tmp_path):
        budget = RetryBudget(default_limit=0)
        receipt = MindLoop(budget=budget).run(GOAL, tmp_path / "proj")
        assert receipt.ok
        assert receipt.budget["default_limit"] == 0

    def test_recovery_scenario_deterministic_chain(self, tmp_path):
        # نفس السيناريو الانعكاسي مرتين ⇒ نفس chain_hash بالبايت
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

            receipt = MindLoop(OncePIICore(), rounds=2).run(GOAL, out)
            assert receipt.ok
            hashes.append(receipt.chain_hash)
            import shutil

            shutil.rmtree(out)
        assert hashes[0] == hashes[1]

    def test_recovery_lesson_reaches_memory(self, tmp_path):
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
        assert receipt.ok
        joined = " ".join(receipt.lessons_learned)
        assert "أعدت المحاولة" in joined or "أعادت المحاولة" in joined

    def test_to_md_documents_reflections_section(self, tmp_path):
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
        md = receipt.to_md()
        assert "## الانعكاسات وإعادة المحاولة" in md
        assert "المحاولة 1" in md
        # البيان الشخصي نفسه لا يتسرب إلى الملاحظة الموثقة
        assert "0501234567" not in json.dumps(receipt.to_dict())

    def test_critic_reflection_only_on_generate_with_gaps(self, tmp_path):
        # مسار الكود القائم: الفجوات توثق رفض الإعادة — لا انعكاس إعادة
        target = tmp_path / "app.py"
        target.write_text("def f( ):\n    x=1\n    return x\n", encoding="utf-8")
        receipt = MindLoop().run(f"راجع الملف {target}", tmp_path / "session")
        assert all(r.get("retried") is not True for r in receipt.reflections)

    def test_empty_advisory_exhausts_budget_honestly(self, tmp_path):
        receipt = MindLoop(ScriptedCore({}, default="   ")).run(GOAL, tmp_path / "proj")
        assert not receipt.ok
        assert receipt.failed_step == "plan"
        assert receipt.budget["used"].get("plan") == 2
        assert len(receipt.reflections) == 3  # محاولة أصلية + إعادتان موثقتان
        # كل انعكاس يحمل سبه الموثق وإشعار التوقف أو الإعادة
        assert all(r["trigger_ar"] for r in receipt.reflections)
        assert receipt.reflections[-1]["retried"] is False
