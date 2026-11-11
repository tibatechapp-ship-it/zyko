"""اختبارات حد العملية الموحد والنواة — بروتوكول واحد وثلاثة أنوية."""

from __future__ import annotations

import pytest

from zyko.mind.core import BrainCore, DeterministicCore, ModelCore, ScriptedCore, core_report


class TestDeterministicCore:
    def test_protocol_conformance(self):
        assert isinstance(DeterministicCore(), ModelCore)

    def test_deterministic_flag(self):
        assert DeterministicCore().deterministic is True
        assert DeterministicCore().name == "deterministic"

    def test_same_request_same_bytes(self):
        core = DeterministicCore()
        r1 = core.respond("انشئ مشروع قائمة مهام")
        r2 = core.respond("انشئ مشروع قائمة مهام")
        assert r1 == r2
        assert r1.strip()

    def test_empty_request_empty_response(self):
        assert DeterministicCore().respond("   ") == ""

    def test_no_exception_on_plain_goal(self):
        core = DeterministicCore()
        out = core.respond("قائمة مهام بسيطة")  # لا كلمات بناء — المخطط قد يفشل
        assert isinstance(out, str)


class TestScriptedCore:
    def test_protocol_conformance(self):
        core = ScriptedCore({"مهام": "خطة المهام"}, default="البديل")
        assert isinstance(core, ScriptedCore)
        assert isinstance(core, ModelCore)

    def test_key_match(self):
        core = ScriptedCore({"مهام": "خطة المهام"}, default="البديل")
        assert core.respond("انشئ مشروع مهام") == "خطة المهام"

    def test_default_fallback(self):
        core = ScriptedCore({"مهام": "خطة المهام"}, default="البديل")
        assert core.respond("هدف آخر") == "البديل"

    def test_first_matching_key_wins(self):
        core = ScriptedCore({"مهام": "أ", "مشروع": "ب"}, default="ج")
        assert core.respond("مشروع مهام") == "أ"

    def test_calls_counter(self):
        core = ScriptedCore({}, default="x")
        core.respond("أ")
        core.respond("ب")
        assert core.calls == 2

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError):
            ScriptedCore(["ليس جدولاً"])  # type: ignore[arg-type]


class TestBrainCore:
    def test_wraps_planner_brain(self):
        from zyko.ai.brains import PlannerBrain

        core = BrainCore(PlannerBrain())
        assert core.deterministic is True
        assert core.name.startswith("core:")

    def test_accepted_text_returns_text(self):
        from zyko.ai.brains import PlannerBrain

        core = BrainCore(PlannerBrain())
        out = core.respond("انشئ مشروع قائمة مهام مع واجهة سطر أوامر")
        assert out.strip()

    def test_rejected_returns_empty_with_verdicts(self):
        from zyko.ai.brains import PlannerBrain

        core = BrainCore(PlannerBrain())
        out = core.respond("انشئ مشروع — للتواصل 0501234567")
        assert out == ""
        assert core.last_verdicts
        assert any(not v.passed for v in core.last_verdicts)

    def test_error_contained_no_exception(self):
        class ExplodingBrain:
            name = "exploding"
            deterministic = False

            def propose(self, request):
                raise RuntimeError("انفجار")

        core = BrainCore(ExplodingBrain())  # type: ignore[arg-type]
        out = core.respond("أي هدف")
        assert out == ""
        assert any("خطأ" in v.details_ar for v in core.last_verdicts)


class TestCoreReport:
    def test_report_fields(self):
        report = core_report(DeterministicCore())
        assert report == {"name": "deterministic", "deterministic": True}
