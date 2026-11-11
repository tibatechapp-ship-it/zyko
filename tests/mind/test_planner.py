"""اختبارات وحدة التخطيط — خطوات حتمية واستشارة قلب خلف البوابات."""

from __future__ import annotations

from zyko.mind.core import DeterministicCore, ScriptedCore
from zyko.mind.perception import perceive
from zyko.mind.planner import build_plan
from zyko.orchestrator.classify import TaskType


class TestBuildPlan:
    def test_generate_plan_three_steps(self):
        p = perceive("انشئ مشروع قائمة مهام")
        plan = build_plan(p, DeterministicCore())
        assert plan.accepted
        assert plan.kind is TaskType.GENERATE
        assert len(plan.steps) == 3
        assert [s.tool for s in plan.steps] == ["pipeline", "critic", "baseline"]
        assert [s.index for s in plan.steps] == [1, 2, 3]

    def test_fix_plan_on_existing_file(self):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "app.py"
            f.write_text("x = 1\n", encoding="utf-8")
            p = perceive(f"اصلح الملف {f}")
            plan = build_plan(p, DeterministicCore())
            assert plan.accepted
            assert f.name in plan.steps[0].title_ar

    def test_unknown_task_rejected_with_guidance(self):
        p = perceive("قائمة مهام عادية")
        plan = build_plan(p, DeterministicCore())
        assert not plan.accepted
        assert plan.steps == ()
        assert "بلا مسار تنفيذ" in plan.verdicts[0].details_ar

    def test_core_verdict_first_then_pii_then_rtl(self):
        p = perceive("انشئ مشروع قائمة مهام")
        plan = build_plan(p, DeterministicCore())
        gates = [v.gate for v in plan.verdicts]
        assert gates[0] == "core"
        assert "pii" in gates and "rtl" in gates

    def test_pii_advisory_rejected(self):
        p = perceive("انشئ مشروع قائمة مهام")
        core = ScriptedCore({"مشروع": "للتواصل: 0501234567"}, default="x")
        plan = build_plan(p, core)
        assert not plan.accepted
        assert any(v.gate == "pii" and not v.passed for v in plan.verdicts)

    def test_empty_core_response_rejected(self):
        p = perceive("انشئ مشروع قائمة مهام")
        core = ScriptedCore({}, default="   ")
        plan = build_plan(p, core)
        assert not plan.accepted
        assert "فارغ" in plan.verdicts[0].details_ar

    def test_core_exception_contained(self):
        class ExplodingCore:
            name = "exploding"
            deterministic = False

            def respond(self, request, *, context=""):
                raise RuntimeError("انفجار")

        p = perceive("انشئ مشروع قائمة مهام")
        plan = build_plan(p, ExplodingCore())  # type: ignore[arg-type]
        assert not plan.accepted
        assert any("القلب أثار خطأ" in v.details_ar for v in plan.verdicts)

    def test_plan_text_deterministic(self):
        p = perceive("انشئ مشروع قائمة مهام مع واجهة سطر أوامر")
        a = build_plan(p, DeterministicCore())
        b = build_plan(p, DeterministicCore())
        assert a.text_ar() == b.text_ar()

    def test_steps_have_acceptance_criteria(self):
        p = perceive("انشئ مشروع قائمة مهام")
        plan = build_plan(p, DeterministicCore())
        assert all(s.acceptance_ar.strip() for s in plan.steps)
        assert all(s.title_ar.strip() for s in plan.steps)
