"""المكوّن 2 — بوابة route: ~25 اختباراً (الأمثلة الإلزامية + الحتمية).

الأمثلة الثلاثة الإلزامية من التكليف هنا باسم test_spec_example_*،
والحتمية مُثبتة بـ 100 تشغيل (P6)، وPlan.to_dict() قابل للتسلسل JSON.
"""

from __future__ import annotations

import json

import pytest

from zyko.orchestrator import Classification, Step, TaskType, classify, route


def _cls(task: TaskType) -> Classification:
    return Classification(task, 0.85, ("كلمة",), ())


class TestStep:
    def test_frozen_step_rejects_mutation(self):
        step = Step("review", {"path": "src/main.py"}, "سبب")
        with pytest.raises(Exception):
            step.tool = "fix"  # type: ignore[misc]

    def test_step_to_dict_exact(self):
        step = Step("review", {"path": "src/main.py"}, "سبب")
        assert step.to_dict() == {
            "tool": "review",
            "args": {"path": "src/main.py"},
            "reason_ar": "سبب",
        }

    def test_step_defaults(self):
        step = Step("fix")
        assert step.args == {} and step.reason_ar == ""


class TestPlan:
    def test_frozen_plan_rejects_mutation(self):
        plan = route(_cls(TaskType.REVIEW), context={"path": "p.py"})
        with pytest.raises(Exception):
            plan.estimated_cost = 1.0  # type: ignore[misc]

    def test_plan_to_dict_json_roundtrip(self):
        plan = route(classify("راجع وأصلح main.py"), context={"path": "main.py"})
        restored = json.loads(json.dumps(plan.to_dict(), ensure_ascii=False))
        assert restored == plan.to_dict()

    def test_unknown_plan_shape(self):
        plan = route(_cls(TaskType.UNKNOWN))
        assert plan.steps == () and plan.estimated_cost == 0.0 and len(plan.notes_ar) == 1


class TestSpecExamples:
    """الأمثلة الثلاثة الإلزامية من التكليف — حرفياً."""

    def test_spec_example_review(self):
        plan = route(classify("راجع src/main.py"), context={"path": "src/main.py"})
        assert [s.tool for s in plan.steps] == ["review"]
        assert plan.steps[0].args == {"path": "src/main.py"}

    def test_spec_example_fix(self):
        plan = route(classify("أصلح main.py"), context={"path": "main.py"})
        assert [s.tool for s in plan.steps] == ["review", "fix"]
        assert all(s.args == {"path": "main.py"} for s in plan.steps)

    def test_spec_example_unknown(self):
        plan = route(classify("الجو جميل"))
        assert plan.steps == ()
        assert plan.notes_ar == ("لم أفهم المهمة — وضّح أكثر",)


class TestFixPlan:
    def test_fix_is_two_steps_in_fixed_order(self):
        plan = route(_cls(TaskType.FIX), context={"path": "a.py"})
        assert [s.tool for s in plan.steps] == ["review", "fix"]

    def test_fix_reasons_are_arabic(self):
        plan = route(_cls(TaskType.FIX), context={"path": "a.py"})
        assert all(s.reason_ar.strip() for s in plan.steps)
        assert "الإصلاح يبدأ بمراجعة" in plan.steps[0].reason_ar

    def test_fix_then_review_plan_from_classify(self):
        # «راجع وأصلح» → FIX (كسر التعادل الموثّق) → خطة إصلاح كاملة
        plan = route(classify("راجع وأصلح main.py"), context={"path": "main.py"})
        assert [s.tool for s in plan.steps] == ["review", "fix"]


class TestSingleToolPlans:
    def test_generate_uses_description(self):
        plan = route(_cls(TaskType.GENERATE), context={"description": "مشروع CLI عربي"})
        assert [s.tool for s in plan.steps] == ["generate"]
        assert plan.steps[0].args == {"description": "مشروع CLI عربي"}

    def test_transpile_prefers_file_key(self):
        plan = route(_cls(TaskType.TRANSPILE), context={"file": "app.daad", "path": "x.py"})
        assert plan.steps[0].args == {"file": "app.daad"}

    def test_verify_prefers_receipt_key(self):
        plan = route(_cls(TaskType.VERIFY), context={"receipt": "r.json"})
        assert plan.steps[0].args == {"receipt": "r.json"}

    def test_analyze_uses_src(self):
        plan = route(_cls(TaskType.ANALYZE), context={"src": "."})
        assert [s.tool for s in plan.steps] == ["baseline_check"]
        assert plan.steps[0].args == {"src": "."}

    def test_analyze_falls_back_to_dot(self):
        plan = route(_cls(TaskType.ANALYZE), context={})
        assert plan.steps[0].args == {"src": "."}


class TestMissingContext:
    def test_review_without_context_adds_arabic_note(self):
        plan = route(_cls(TaskType.REVIEW), context=None)
        assert plan.steps[0].args == {"path": ""}
        assert plan.notes_ar == ("لم يُحدد المسار — مرّره في context['path']",)

    def test_generate_without_description_adds_note(self):
        plan = route(_cls(TaskType.GENERATE))
        assert plan.steps[0].args == {"description": ""}
        assert "context['description']" in plan.notes_ar[0]

    def test_transpile_without_file_adds_note(self):
        plan = route(_cls(TaskType.TRANSPILE))
        assert "context['file']" in plan.notes_ar[0]

    def test_verify_without_receipt_adds_note(self):
        plan = route(_cls(TaskType.VERIFY))
        assert "context['receipt']" in plan.notes_ar[0]


class TestUnknown:
    def test_unknown_has_no_steps_and_clear_note(self):
        plan = route(classify("42"))
        assert plan.steps == () and "لم أفهم المهمة" in plan.notes_ar[0]

    def test_unknown_ignores_context(self):
        plan = route(classify(""), context={"path": "main.py"})
        assert plan.steps == ()


class TestDeterminism:
    def test_100_runs_identical(self):
        plan = route(classify("راجع وأصلح main.py"), context={"path": "main.py"})
        for _ in range(100):
            assert route(classify("راجع وأصلح main.py"), context={"path": "main.py"}) == plan

    def test_estimated_cost_is_zero_deterministic_tools(self):
        plan = route(_cls(TaskType.FIX), context={"path": "a.py"})
        assert plan.estimated_cost == 0.0

    def test_plan_to_dict_keys_exact(self):
        assert set(route(_cls(TaskType.REVIEW)).to_dict()) == {
            "classification",
            "steps",
            "estimated_cost",
            "notes_ar",
        }
