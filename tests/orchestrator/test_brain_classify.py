"""اختبارات classify_with_brain — الدماغ كمصنِّف خلف التحقق الحتمي الصارم.

العقد المُختبر هنا:
1. التصنيف الحتمي بلا ``--brain`` يبقى متطابقاً بالبايت — ``to_dict`` بلا
   مفتاح ``classifier`` إطلاقاً.
2. تصنيف الدماغ لا يُقبل خاماً أبداً: النوع واحد من الستة الحقيقية (UNKNOWN
   منه رفض)، والثقة رقم حقيقي في ‎[0.0, 1.0] إلزامي، والكلمات المتطابقة
   تُنقَّى حتمياً — والناجح يحمل ``classifier="brain:<اسم>"``.
3. أي إخفاق (عقل يرمي، بوابات ترفض، JSON فاسد، نوع مخالف، ثقة خارج
   الحدود أو مفقودة أو نصية) ⇒ رجوع موثق بالجدول الحتمي مع ملاحظة عربية
   صريحة — لا استثناء خارج ولا فشل صامت.
4. تماسك السلسلة: خطة المخطط يجب أن تعتُد بقرار المصنِّف — تنافرهما رفض
   للخطة كلها، والتصنيف المُمرَّر يتدفق إلى الخطة والإيصال كما هو.
5. ``cmd_do --brain`` يستشير المصنِّف ثم المخطِّط بنفس العقل، ويطبع
   الملاحظة الصادقة في الحالين.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from zyko.ai.brains import GateVerdict, Proposal
from zyko.orchestrator import (
    classify_with_brain,
    parse_brain_classification,
    plan_with_brain,
)
from zyko.orchestrator.brain_route import classifier_prompt
from zyko.orchestrator.classify import classify


class FakeBrain:
    """عقل مكتوب مسبقاً للاختبار — يعيد نصاً ثابتاً أو يرمي أو يُرفض."""

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
        self.requests: list[str] = []

    def propose(self, request: str) -> Proposal:
        self.requests.append(request)
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
            verdicts=(GateVerdict(gate="planner", passed=True, details_ar="مقترح سليم"),),
        )


# ------------------------------------------------------------- العقد الحتمي
def test_deterministic_to_dict_has_no_classifier_key() -> None:
    """المسار الحتمي: قرارات الجدول بلا مفتاح classifier — تطابق بالبايت."""
    for goal in ("راجع src/x.py", "راجع وأصلح x.py", "أرسل بريدًا للعميل", ""):
        payload = classify(goal).to_dict()
        assert "classifier" not in payload, payload


def test_classifier_prompt_is_deterministic_and_arabic() -> None:
    """نفس الهدف = نفس التوجيه بالبايت، والهدف فيه حرفيًا."""
    a = classifier_prompt("راجع src/x.py")
    b = classifier_prompt("راجع src/x.py")
    assert a == b
    assert "راجع src/x.py" in a
    assert "UNKNOWN" in a and "confidence" in a


# ------------------------------------------------------------- القبول
def test_valid_brain_classification_is_signed() -> None:
    """تصنيف سليم ⇒ موقّع باسم العقل وكلماته المتطابقة محفوظة."""
    text = '{"task": "FIX", "confidence": 0.9, "matched_keywords": ["اصلح", "bug"], "reason_ar": "طلب إصلاح"}'
    classification = parse_brain_classification(text, "fake")
    assert classification is not None
    payload = classification.to_dict()
    assert payload["task"] == "FIX"
    assert payload["confidence"] == 0.9
    assert payload["matched_keywords"] == ["اصلح", "bug"]
    assert payload["classifier"] == "brain:fake"


def test_keywords_are_sanitized_deterministically() -> None:
    """كلمات فاسدة تُهمَل لعُطب تجميلي — القائمة النظيفة فقط تبقى."""
    text = json.dumps(
        {
            "task": "REVIEW",
            "confidence": 0.5,
            "matched_keywords": ["راجع", 42, "", "x" * 200, "bug\n", None, "ok"],
        },
        ensure_ascii=False,
    )
    classification = parse_brain_classification(text, "fake")
    assert classification is not None
    assert classification.matched_keywords == ("راجع", "ok")


def test_classify_with_brain_accepts_and_documents() -> None:
    """قبول كامل عبر العقل: الملاحظة تذكر اسمه والقرار موقعّع."""
    brain = FakeBrain('{"task": "REVIEW", "confidence": 0.8}')
    classification, note = classify_with_brain("افحص هذا الملف", brain)
    assert classification.task.value == "REVIEW"
    assert classification.confidence == 0.8
    assert classification.classifier == "brain:fake"
    assert "الدماغ (fake)" in note
    # التوجيهان اختلفا: المصنِّف يُستشار بتوجيهه الخاص
    assert brain.requests == [classifier_prompt("افحص هذا الملف")]


# ------------------------------------------------------------- الرفض والرجوع
def test_brain_unknown_is_rejected_to_deterministic_table() -> None:
    """UNKNOWN من الدماغ ممنوع: الجدول الحتمي هو من يقرر العتلة أصلاً."""
    brain = FakeBrain('{"task": "UNKNOWN", "confidence": 0.0}')
    fallback = classify("هدف غامض تمامًا")
    classification, note = classify_with_brain("هدف غامض تمامًا", brain)
    assert classification == fallback
    assert classification.classifier is None
    assert "الجدول الحتمي قرر" in note


def test_confidence_out_of_bounds_or_missing_or_textual_rejects() -> None:
    """الثقة خارج ‎[0,1] أو مفقودة أو نصية ⇒ رفض ورجوع حتمي موثق."""
    goal = "راجع src/x.py"
    fallback = classify(goal)
    for bad in (
        '{"task": "REVIEW", "confidence": 1.5}',
        '{"task": "REVIEW", "confidence": -0.1}',
        '{"task": "REVIEW"}',
        '{"task": "REVIEW", "confidence": "0.9"}',
        '{"task": "REVIEW", "confidence": true}',
    ):
        classification, note = classify_with_brain(goal, FakeBrain(bad))
        assert classification == fallback, bad
        assert classification.classifier is None
        assert "فشل التحقق الحتمي" in note


def test_disallowed_task_type_rejects() -> None:
    """نوع خارج الستة (أو مخالف بنيوياً) ⇒ رفض ورجوع حتمي."""
    goal = "راجع src/x.py"
    fallback = classify(goal)
    for bad in ('{"task": "PLAN", "confidence": 0.5}', '{"task": "review", "confidence": 0.5}'):
        classification, note = classify_with_brain(goal, FakeBrain(bad))
        assert classification == fallback
        assert "فشل التحقق الحتمي" in note


def test_throwing_brain_falls_back_with_documented_note() -> None:
    """عقل يرمي ⇒ رجوع موثق بنوع الخطأ — لا استثناء خارج."""
    classification, note = classify_with_brain("راجع x.py", FakeBrain(fail=True))
    assert classification == classify("راجع x.py")
    assert classification.classifier is None
    assert "RuntimeError" in note


def test_rejecting_brain_falls_back_with_gate_reasons() -> None:
    """بوابات ترفض ⇒ رجوع موثق بأسبابها العربية."""
    classification, note = classify_with_brain("راجع x.py", FakeBrain(reject=True))
    assert classification == classify("راجع x.py")
    assert "مرفوض عند البوابات" in note and "بيان شخصي" in note


def test_broken_json_falls_back() -> None:
    """JSON فاسد أو أسوار كود ناقصة ⇒ رجوع حتمي."""
    classification, note = classify_with_brain("راجع x.py", FakeBrain("ليس JSON إطلاقاً"))
    assert classification.classifier is None
    assert "فشل التحقق الحتمي" in note


# ------------------------------------------------------------- تماسك السلسلة
def test_plan_with_brain_accepts_precomputed_classification(tmp_path) -> None:
    """التصنيف المُمرَّر يتدفق للخطة كما هو مع تماسك المهمة."""
    target = tmp_path / "x.py"
    target.write_text("x = 1\n", encoding="utf-8")
    classification = parse_brain_classification('{"task": "REVIEW", "confidence": 0.8}', "fake")
    assert classification is not None
    plan_text = json.dumps(
        {"task": "REVIEW", "steps": [{"tool": "review", "path": str(target), "reason_ar": "سبب"}]}
    )
    plan, note = plan_with_brain(
        f"افحص {target}", FakeBrain(plan_text), classification=classification
    )
    assert plan.planner == "brain:fake"
    assert plan.classification is classification
    assert classification.classifier == "brain:fake"
    assert "المخطط من الدماغ" in note


def test_plan_rejected_when_brain_plan_contradicts_classification(tmp_path) -> None:
    """تنافر المصنِّف (REVIEW) والمخطِّط (FIX) ⇒ رفض الخطة ورجوع موثق."""
    target = tmp_path / "x.py"
    target.write_text("x = 1\n", encoding="utf-8")
    classification = parse_brain_classification('{"task": "REVIEW", "confidence": 0.8}', "fake")
    assert classification is not None
    plan_text = json.dumps(
        {
            "task": "FIX",
            "steps": [
                {"tool": "review", "path": str(target), "reason_ar": "سبب"},
                {"tool": "fix", "path": str(target), "reason_ar": "سبب"},
            ],
        }
    )
    fallback_plan, note = plan_with_brain(
        f"افحص {target}", FakeBrain(plan_text), classification=classification
    )
    assert fallback_plan.planner == "deterministic"
    assert "تماسك التصنيف" in note or "فشل التحقق الحتمي" in note
    assert fallback_plan.classification.task.value == "REVIEW"


def test_plan_with_brain_without_classification_unchanged(tmp_path) -> None:
    """غياب التصنيف المُمرَّر يعيد السلوك السابق حرفياً (تصنيف حتمي محلي)."""
    target = tmp_path / "x.py"
    target.write_text("x = 1\n", encoding="utf-8")
    plan_text = json.dumps(
        {"task": "REVIEW", "steps": [{"tool": "review", "path": str(target), "reason_ar": "سبب"}]}
    )
    plan, note = plan_with_brain(f"افحص {target}", FakeBrain(plan_text))
    assert plan.planner == "brain:fake"
    assert plan.classification.classifier is None  # التصنيف الحتمي المحلي
    assert plan.classification == classify(f"افحص {target}")
    assert "المخطط من الدماغ" in note


# ------------------------------------------------------------- تكامل cmd_do
def test_cmd_do_brain_classifies_then_plans(monkeypatch, capsys, tmp_path) -> None:
    """--brain: المصنِّف ثم المخطِّط بنفس العقل — والملاحظتان مطبوعتان."""
    from zyko.cli.commands import cmd_do

    target = tmp_path / "x.py"
    target.write_text("x = 1\n", encoding="utf-8")
    classification_text = '{"task": "REVIEW", "confidence": 0.9}'
    plan_text = json.dumps(
        {"task": "REVIEW", "steps": [{"tool": "review", "path": str(target), "reason_ar": "سبب"}]}
    )

    class SplitBrain(FakeBrain):
        """عقل يجيب: أول استشارة تصنيف، والباقي تخطيط."""

        def __init__(self) -> None:
            super().__init__("")
            self.calls = 0

        def propose(self, request: str) -> Proposal:
            self.calls += 1
            self.text = classification_text if self.calls == 1 else plan_text
            return super().propose(request)

    split = SplitBrain()
    monkeypatch.setattr("zyko.ai.cli.build_brain", lambda args: split)

    split_text_goal = f"افحص {target}"

    args = SimpleNamespace(
        goal=split_text_goal,
        brain="fake",
        model="fake-model",
        write=False,
        json=False,
        path=None,
        file=None,
        src=None,
        description=None,
    )
    code = cmd_do(args)
    out = capsys.readouterr().out
    assert code == 0
    assert split.calls == 2, "المصنِّف ثم المخطِّط بنفس العقل"
    assert "التصنيف من الدماغ (fake)" in out
    assert "المخطط من الدماغ (fake)" in out
    assert "المهمة: REVIEW — ثقة 0.90" in out
    assert split.requests[0] == classifier_prompt(split_text_goal), "أول استشارة بتوجيه المصنِّف"


def test_cmd_do_brain_fallback_classify_prints_warning(monkeypatch, capsys, tmp_path) -> None:
    """تصنيف دماغ مرفوض ⇒ ملاحظة تحذير والجدول الحتمي يقرر — السير مستمر."""
    from zyko.cli.commands import cmd_do

    target = tmp_path / "x.py"
    target.write_text("x = 1\n", encoding="utf-8")
    plan_text = json.dumps(
        {"task": "REVIEW", "steps": [{"tool": "review", "path": str(target), "reason_ar": "سبب"}]}
    )

    class RejectClassifyBrain(FakeBrain):
        """يُرفض تصنيفه عند البوابات وتُقبل خطته."""

        def __init__(self) -> None:
            super().__init__(plan_text, reject=True)
            self.calls = 0

        def propose(self, request: str) -> Proposal:
            self.calls += 1
            if self.calls == 1:
                return super().propose(request)  # مرفوض
            self.reject = False
            return super().propose(request)

    brain = RejectClassifyBrain()
    monkeypatch.setattr("zyko.ai.cli.build_brain", lambda args: brain)

    args = SimpleNamespace(
        goal=f"افحص {target}",
        brain="fake",
        model="fake-model",
        write=False,
        json=False,
        path=None,
        file=None,
        src=None,
        description=None,
    )
    code = cmd_do(args)
    captured = capsys.readouterr()
    assert code == 0
    assert brain.calls == 2
    assert "مرفوض عند البوابات" in captured.out
    assert "الجدول الحتمي قرر" in captured.out
    assert "المخطط من الدماغ (fake)" in captured.out
