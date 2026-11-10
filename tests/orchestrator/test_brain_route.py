"""اختبارات brain_route — الدماغ الحقيقي كمخطِّط خلف تحقق حتمي صارم.

العقد المُختبر هنا (كلها إلزامية):
1. خطة دماغ سليمة تُقبل وتحمل ``planner="brain:<اسم>"`` — مصدرها موثق.
2. كل إخفاق (JSON تالف، أداة غريبة، مسار مختلق، تسلسل مخالف، بوابات
   رافضة، عقل يرمي) ⇒ رجوع آمن للمخطط الحتمي بملاحظة عربية صادقة —
   لا استثناء خارج ولا فشل صامت.
3. بلا دماغ: ``route`` كما كان — إيصالات المسار الحتمي بلا حقل
   ``planner`` متطابقة بالبايت مع عقدها السابق.
"""

from __future__ import annotations

import json

import pytest

from zyko.ai.brains import GateVerdict, Proposal
from zyko.orchestrator import parse_brain_plan, plan_with_brain, planner_prompt, route
from zyko.orchestrator.classify import classify


class FakeBrain:
    """عقل مكتوب مسبقًا للاختبار — يعيد نصًا ثابتًا أو يرمي."""

    def __init__(
        self,
        text: str = "",
        *,
        name: str = "fake",
        deterministic: bool = False,
        fail: bool = False,
        reject: bool = False,
    ) -> None:
        self.text = text
        self.name = name
        self.deterministic = deterministic
        self.fail = fail
        self.reject = reject
        self.last_request: str | None = None

    def propose(self, request: str) -> Proposal:
        self.last_request = request
        if self.fail:
            raise RuntimeError("انقطاع شبكة مُمثَّل")
        if self.reject:
            return Proposal(
                text=self.text,
                brain=self.name,
                deterministic=self.deterministic,
                verdicts=(GateVerdict(gate="pii", passed=False, details_ar="مرفوض: بيان شخصي"),),
            )
        return Proposal(
            text=self.text,
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=(GateVerdict(gate="planner", passed=True, details_ar="مخطط صالح"),),
        )


def _review_json(path: str, *, task: str = "REVIEW", tools: tuple[str, ...] = ("review",)) -> str:
    steps = [{"tool": t, "path": path, "reason_ar": f"سبب {t}"} for t in tools]
    return json.dumps({"task": task, "steps": steps}, ensure_ascii=False)


# ------------------------------------------------------------- التوجيه
def test_planner_prompt_is_deterministic() -> None:
    """نفس الهدف = نفس التوجيه بالبايت، والهدف فيه حرفيًا."""
    a = planner_prompt("راجع src/app.py")
    b = planner_prompt("راجع src/app.py")
    assert a == b and a == planner_prompt("  راجع src/app.py  ")
    assert "راجع src/app.py" in a and "REVIEW" in a and "JSON" in a


# ------------------------------------------------------------- القبول
def test_valid_review_plan_accepted(tmp_path) -> None:
    """خطة مراجعة سليمة: تُقبل، تحمل planner=brain:fake، ودرجتها ثقة 1.0."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    plan = parse_brain_plan(_review_json(str(target)), "fake")
    assert plan is not None
    assert plan.planner == "brain:fake"
    assert plan.classification.task.value == "REVIEW"
    assert plan.classification.confidence == 1.0
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "review"
    assert plan.steps[0].args == {"path": str(target)}
    assert plan.steps[0].reason_ar == "سبب review"


def test_valid_fix_plan_two_steps(tmp_path) -> None:
    """خطة إصلاح سليمة: review ثم fix على المسار نفسه."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    plan = parse_brain_plan(_review_json(str(target), task="FIX", tools=("review", "fix")), "fake")
    assert plan is not None and plan.planner == "brain:fake"
    assert [s.tool for s in plan.steps] == ["review", "fix"]
    assert len({s.args["path"] for s in plan.steps}) == 1


def test_fenced_json_accepted(tmp_path) -> None:
    """أسوار كود ونص محيط لا يمنعان استخراج الـ JSON."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = f"هذه خطتي:\n```json\n{_review_json(str(target))}\n```\nتم."
    plan = parse_brain_plan(text, "fake")
    assert plan is not None and len(plan.steps) == 1


def test_brain_plan_to_dict_documents_planner(tmp_path) -> None:
    """ممثل JSON لخطة الدماغ يحمل planner — والإيصال يوثق المصدر بصدق."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    plan = parse_brain_plan(_review_json(str(target)), "fake")
    assert plan is not None
    assert plan.to_dict()["planner"] == "brain:fake"


def test_deterministic_plan_has_no_planner_key() -> None:
    """المسار الحتمي كما كان: to_dict بلا مفتاح planner — توافق بايتي."""
    plan = route(classify("راجع ملف غير موجود"), context={"path": "أي/مسار"})
    assert "planner" not in plan.to_dict()
    assert plan.planner == "deterministic"


# ------------------------------------------------------------- الرفض البنيوي
def test_invalid_json_falls_back_to_none() -> None:
    """JSON تالف ⇒ None — لا قبول جزئي."""
    assert parse_brain_plan("لست JSON", "fake") is None
    assert parse_brain_plan('{"task": "REVIEW", "steps": [', "fake") is None


def test_unknown_tool_rejected(tmp_path) -> None:
    """أداة خارج القائمة البيضاء ⇒ رفض كامل."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = json.dumps(
        {"task": "REVIEW", "steps": [{"tool": "rm_rf", "path": str(target)}]}, ensure_ascii=False
    )
    assert parse_brain_plan(text, "fake") is None


def test_hallucinated_path_rejected() -> None:
    """مسار غير موجود على القرص ⇒ رفض — الدماغ لا يختلق مسارات."""
    text = _review_json("/definitely/not/there/ever.py")
    assert parse_brain_plan(text, "fake") is None


def test_disallowed_task_rejected(tmp_path) -> None:
    """مهمة خارج REVIEW/FIX (مثل GENERATE) ⇒ رفض."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = json.dumps(
        {"task": "GENERATE", "steps": [{"tool": "review", "path": str(target)}]},
        ensure_ascii=False,
    )
    assert parse_brain_plan(text, "fake") is None


def test_review_task_with_fix_step_rejected(tmp_path) -> None:
    """تسلسل مخالف: REVIEW بخطوة fix ⇒ رفض كامل."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = json.dumps(
        {"task": "REVIEW", "steps": [{"tool": "fix", "path": str(target)}]}, ensure_ascii=False
    )
    assert parse_brain_plan(text, "fake") is None


def test_two_different_paths_rejected(tmp_path) -> None:
    """مساران مختلفان في خطة واحدة ⇒ رفض — العقد مسار واحد."""
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("x = 1\n", encoding="utf-8")
    b.write_text("y = 2\n", encoding="utf-8")
    text = json.dumps(
        {
            "task": "FIX",
            "steps": [
                {"tool": "review", "path": str(a)},
                {"tool": "fix", "path": str(b)},
            ],
        },
        ensure_ascii=False,
    )
    assert parse_brain_plan(text, "fake") is None


def test_empty_steps_rejected() -> None:
    assert parse_brain_plan('{"task": "REVIEW", "steps": []}', "fake") is None


def test_reason_ar_over_limit_replaced_with_default(tmp_path) -> None:
    """سبب أطول من 300 محرف ⇒ يُستبدل بالسبب الافتراضي الحتمي — خطة سليمة تبقى سليمة."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = json.dumps(
        {
            "task": "REVIEW",
            "steps": [{"tool": "review", "path": str(target), "reason_ar": "س" * 301}],
        },
        ensure_ascii=False,
    )
    plan = parse_brain_plan(text, "fake")
    assert plan is not None
    assert plan.steps[0].reason_ar == "مراجعة حتمية بقواعد AST — بلا نموذج وبلا شبكة"


def test_path_with_newline_rejected(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = _review_json(f"{target}\n/etc/passwd")
    assert parse_brain_plan(text, "fake") is None


def test_step_not_a_dict_rejected(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = json.dumps({"task": "REVIEW", "steps": ["review"]}, ensure_ascii=False)
    assert parse_brain_plan(text, "fake") is None


# ------------------------------------------------------------- الرجوع الآمن
def test_plan_with_brain_end_to_end_accepts(tmp_path) -> None:
    """دماغ سليم ⇒ خطة دماغ + ملاحظة قبول صادقة."""
    target = tmp_path / "mod.py"
    target.write_text("x = 1\n", encoding="utf-8")
    goal = f"افحص {target}"
    brain = FakeBrain(_review_json(str(target)))
    plan, note = plan_with_brain(goal, brain)
    assert plan.planner == "brain:fake"
    assert "المخطط من الدماغ" in note
    # التوجيه وصل للدماغ وفيه الهدف حرفيًا
    assert brain.last_request is not None and goal in brain.last_request
    # الملاحظة داخل الخطة نفسها — توثق في الإيصال لاحقًا
    assert any("المخطط من الدماغ" in n for n in plan.notes_ar)


def test_plan_with_brain_invalid_json_falls_back() -> None:
    """JSON تالف ⇒ الخطة الحتمية الأصلية + ملاحظة رجوع صادقة."""
    from zyko.orchestrator.context import extract_context

    goal = "راجع src/whatever.py"
    plan, note = plan_with_brain(goal, FakeBrain("إجابة غير JSON"), context=extract_context(goal))
    assert plan.planner == "deterministic"
    assert "رجوع للمخطط الحتمي" in note
    assert plan.classification.task.value == "REVIEW"  # من classify الحتمي
    assert plan.steps[0].args["path"].startswith("src/whatever")  # من المستخرج الحتمي


def test_plan_with_brain_exception_falls_back() -> None:
    """عقل يرمي ⇒ رجوع موثق بنوع الاستثناء — لا انهيار."""
    plan, note = plan_with_brain("راجع src/x.py", FakeBrain("", fail=True))
    assert plan.planner == "deterministic"
    assert "RuntimeError" in note


def test_plan_with_brain_gate_rejection_falls_back() -> None:
    """بوابات رفضت الاقتراح ⇒ رجوع وسبب البوابات في الملاحظة."""
    plan, note = plan_with_brain("راجع src/x.py", FakeBrain("نص", reject=True))
    assert plan.planner == "deterministic"
    assert "البوابات" in note and "بيان شخصي" in note


def test_fallback_note_inside_plan_notes() -> None:
    """ملاحظة الرجوع داخل الخطة نفسها — تدخل الإيصال دون جهد إضافي."""
    plan, note = plan_with_brain("راجع src/x.py", FakeBrain("", fail=True))
    assert note in plan.notes_ar


# ------------------------------------------------------------- الحتمية
def test_brain_plan_deterministic_by_text(tmp_path) -> None:
    """نفس نص الدماغ ⇒ نفس الخطة بالبايت — التحقق نفسه حتمي."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    text = _review_json(str(target))
    a = parse_brain_plan(text, "fake")
    b = parse_brain_plan(text, "fake")
    assert a is not None and b is not None
    assert a.to_dict() == b.to_dict()


# ------------------------------------------------------------- التكامل مع run
def test_brain_plan_executes_through_orchestrator(tmp_path) -> None:
    """خطة الدماغ تُنفَّذ عبر المنسق نفسه بإيصال موقّع — بلا مسار خاص."""
    from zyko.orchestrator.run import run

    target = tmp_path / "real_code.py"
    target.write_text("def f(a, b):\n    return a + b\n", encoding="utf-8")
    brain = FakeBrain(_review_json(str(target)))
    plan, _note = plan_with_brain(f"افحص {target}", brain)
    result = run(plan, dry_run=True)
    assert result.ok
    assert result.receipt["plan"]["planner"] == "brain:fake"
    assert result.steps[0].ok and result.steps[0].output["score"] >= 0


def test_default_goal_without_brain_unchanged(tmp_path) -> None:
    """بلا دماغ: classify → route كما كان حرفيًا — نفس المسار والسبب."""
    goal = "راجع src/requests/models.py"
    plan = route(classify(goal), context={"path": "src/requests/models.py"})
    assert plan.planner == "deterministic"
    assert plan.steps[0].tool == "review"
    assert plan.steps[0].args == {"path": "src/requests/models.py"}
    assert plan.estimated_cost == 0.0


# ------------------------------------------------------------- CLI
def test_cli_do_requires_model_with_brain(capsys) -> None:
    """--brain بلا --model ⇒ خطأ استخدام 2 ورسالة عربية على stderr."""
    from zyko.cli.commands import cmd_do
    from types import SimpleNamespace

    args = SimpleNamespace(
        goal="راجع x.py", path=None, file=None, src=None, description=None,
        brain="qwen", model=None, qwen_host=None, ollama_host=None,
        write=False, json=False, receipt=None, dry_run=True,
    )
    assert cmd_do(args) == 2
    err = capsys.readouterr().err
    assert "--model" in err and "qwen" in err


def test_cli_do_with_brain_fallback_prints_note(capsys, monkeypatch) -> None:
    """CLI كامل: دماغ فاشل JSON ⇒ يعمل على الخطة الحتمية ويطبع ملاحظة الرجوع."""
    from types import SimpleNamespace

    import zyko.ai.cli as ai_cli

    def fake_build_brain(_args):
        return FakeBrain("لست خطة")

    monkeypatch.setattr(ai_cli, "build_brain", fake_build_brain)
    ns = SimpleNamespace(
        goal="راجع نقطة/الدخول.py", path=None, file=None, src=None, description=None,
        brain="qwen", model="m", qwen_host=None, ollama_host=None,
        write=False, json=False, receipt=None, dry_run=True,
    )
    # الملف غير موجود ⇒ الخطة الحتمية تُنفَّذ وتفشل خطوتها بأدب — لكن الملاحظة طُبعت
    from zyko.cli import commands  # noqa: F401 — يثبت قابلية الاستيراد

    code = commands.cmd_do(ns)
    out = capsys.readouterr().out
    assert "رجوع للمخطط الحتمي" in out
    assert code in (0, 1, 2)


def test_cli_do_with_brain_accepted_prints_note(tmp_path, capsys, monkeypatch) -> None:
    """CLI كامل: دماغ سليم ⇒ ملاحظة القبول تُطبع والتنفيذ على خطة الدماغ."""
    from types import SimpleNamespace

    import zyko.ai.cli as ai_cli

    target = tmp_path / "cli_target.py"
    target.write_text("value = 42\n", encoding="utf-8")

    def fake_build_brain(_args):
        return FakeBrain(_review_json(str(target)))

    monkeypatch.setattr(ai_cli, "build_brain", fake_build_brain)
    ns = SimpleNamespace(
        goal=f"افحص {target}", path=None, file=None, src=None, description=None,
        brain="qwen", model="m", qwen_host=None, ollama_host=None,
        write=False, json=False, receipt=None, dry_run=True,
    )
    from zyko.cli import commands

    code = commands.cmd_do(ns)
    out = capsys.readouterr().out
    assert "المخطط من الدماغ" in out
    assert "REVIEW" in out
    assert code == 0
