"""المكوّن 2-ب — brain_route: الدماغ الحقيقي كمخطِّط، والحتمي حارسًا.

العقد هنا دقيق ويغلق الفجوة الموثقة في ``docs/REAL_WORLD_TEST.md``:
«الدماغ يخطط، المنفّذ الحتمي يعمل» — لكن الاقتراح لا يُقبل خامًا أبدًا.
التسلسل الكامل لكل هدف:

1. التصنيف الحتمي يُحسب أولًا (``classify``) — هو الأساس الذي نرجع إليه.
2. يُبنى توجيه عربي حتمي يطلب من الدماغ JSON صارمًا (مهام وأدوات مسموحة).
3. اقتراح الدماغ يمرّ بوابات المصنع نفسها (عقل ← PII ← RTL) عبر عقد
   ``Brain`` الحالي — لا نص نموذج يتجاوز البوابات أبدًا.
4. ثم تحقق بنيوي حتمي صارم على الخطة المقترحة:
   - المهمة: REVIEW أو FIX فقط (المنفّذون الحتميون على الكود القائم).
   - الأدوات: review/fix فقط، وتسلسلها محكوم:
     REVIEW ⇒ (review) — FIX ⇒ (review, fix) أو (fix).
   - المسار: نص واحد متطابق لكل الخطوات، بلا أسطر جديدة ولا أصفار،
     بحد 1024 محرفًا، **وموجود فعلاً على القرص** — الدماغ لا يختلق مسارات.
   - سبب كل خطوة عربي بحد 300 محرفًا.
5. أي إخفاق في (2) أو (3) أو (4) ⇒ **رجوع آمن** للمخطط الحتمي مع ملاحظة
   عربية صريحة تشرح السبب — لا استثناء خارج ولا فشل صامت.

الخطة المقبولة تحمل ``planner="brain:<اسم>"`` فيثر الإيصال موثقًا مصدرها
بصدق، وتبقى إيصالات المسار الحتمي بلا هذا الحقل متطابقة بالبايت مع عقدها.
بلا ``--brain`` لا شبكة ولا نموذج إطلاقًا — السلوك السابق حرفيًا.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from zyko.orchestrator.classify import Classification, TaskType, classify
from zyko.orchestrator.route import Plan, Step, route

__all__ = [
    "ALLOWED_TASKS",
    "BRAIN_TOOLS",
    "CLASSIFIABLE_TASKS",
    "MAX_BRAIN_PATH_LEN",
    "MAX_BRAIN_REASON_LEN",
    "MAX_BRAIN_STEPS",
    "classify_with_brain",
    "parse_brain_classification",
    "parse_brain_plan",
    "plan_with_brain",
    "planner_prompt",
]

# المهام والأدوات المسموحة لخطة الدماغ — المنفّذون الحتميون على الكود القائم.
ALLOWED_TASKS: frozenset[str] = frozenset({"REVIEW", "FIX"})
BRAIN_TOOLS: frozenset[str] = frozenset({"review", "fix"})

# التسلسلات المحكومة لكل مهمة — نفس دلالات المخطط الحتمي بلا حرية مفتوحة.
_ALLOWED_SEQUENCES: dict[str, frozenset[tuple[str, ...]]] = {
    "REVIEW": frozenset({("review",)}),
    "FIX": frozenset({("review", "fix"), ("fix",)}),
}

MAX_BRAIN_STEPS = 4
MAX_BRAIN_PATH_LEN = 1024
MAX_BRAIN_REASON_LEN = 300

_PROMPT_TEMPLATE = """أنت مخطِّط مهام داخل zyko. صنّف هدف المستخدم واقترح خطواته.
الأدوات المسموحة فقط: review (مراجعة ملف أو مجلد قائم) و fix (إصلاح ملف قائم).
أجب بـ JSON صالح وحده — بلا شرح وبلا أسوار كود وبلا أي نص قبله أو بعده — بهذا الشكل:
{{"task": "REVIEW", "steps": [{{"tool": "review", "path": "المسار", "reason_ar": "سبب عربي قصير"}}]}}
قواعد ملزمة:
- REVIEW: خطوة review واحدة على المسار.
- FIX: خطوتان review ثم fix على المسار نفسه.
- المسار ملف أو مجلد موجود فعلاً — لا تختلق مسارًا أبدًا.
- reason_ar عربي قصير لكل خطوة.
الهدف: {goal}"""

_CLASSIFIER_PROMPT = """أنت مصنّف مهام داخل zyko. النوع المسموح واحد فقط من هذه الستة:
REVIEW (مراجعة)، FIX (إصلاح)، GENERATE (توليد)، TRANSPILE (ترجمة)، VERIFY (تحقق إيصال)، ANALYZE (تحليل).
أجب بـ JSON صالح وحده — بلا شرح وبلا أسوار كود وبلا أي نص قبله أو بعده — بهذا الشكل:
{{"task": "REVIEW", "confidence": 0.9, "reason_ar": "سبب عربي قصير"}}
قواعد ملزمة:
- confidence رقم بين 0.0 و1.0 يعبّر عن ثقتك بالنوع المختار.
- إن لم تفهم الهدف تمامًا أجب UNKNOWN وثقة 0.0.
- reason_ar عربي قصير يشرح الاختيار.
الهدف: {goal}"""


class _PlannerBrain(Protocol):
    """أدنى عقد عقل يصلح للتخطيط — نفس عقد ``zyko.ai.brains.Brain``."""

    name: str
    deterministic: bool

    def propose(self, request: str) -> Any: ...


def planner_prompt(goal: str) -> str:
    """التوجيه العربي الحتمي للدماغ — نفس الهدف = نفس التوجيه بالبايت."""
    return _PROMPT_TEMPLATE.format(goal=str(goal).strip())


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """أول كائن JSON سليم في النص — يتحمل أسوار الكود والنص المحيط."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _clean_step_value(value: Any, *, max_len: int) -> str | None:
    """قيمة نصية نظيفة: نص واحد بلا أسطر جديدة ولا أصفار ودون الحد."""
    if not isinstance(value, str):
        return None
    if not value or len(value) > max_len:
        return None
    if "\n" in value or "\r" in value or "\x00" in value:
        return None
    return value


# الأنواع القابلة للتصنيف من دماغ — UNKNOWN ممنوع عليه: الدماغ مُستشار
# ليفهم لا ليعتل؛ إن قال UNKNOWN رجعنا للجدول الحتمي مع ملاحظة صادقة.
CLASSIFIABLE_TASKS: frozenset[str] = frozenset(
    {"REVIEW", "FIX", "GENERATE", "TRANSPILE", "VERIFY", "ANALYZE"}
)
MAX_CLASSIFIER_REASON_LEN = 300
MAX_CLASSIFIER_KEYWORDS = 8
MAX_CLASSIFIER_KEYWORD_LEN = 64


def parse_brain_classification(text: str, brain_name: str) -> Classification | None:
    """حوّل نص الدماغ إلى تصنيف موثّق — أو None إن أخفق أي تحقق حتمي.

    القواعد الصارمة:
    - ``task`` واحد من ``CLASSIFIABLE_TASKS`` — UNKNOWN من الدماغ رفض (والجدول
      الحتمي هو من يقرر UNKNOWN أصلاً بلا استشارة).
    - ``confidence`` رقم حقيقي (لا نص ولا منطقي) في ‎[0.0, 1.0] — مفقود ⇒ رفض.
    - ``matched_keywords`` اختياري: قائمة نصوص قصيرة — فسادها يُهمل لعُطب
      تجميلي لا يُسقط قراراً سليمًا.
    التصنيف الناجح يحمل ``classifier="brain:<اسم>"`` ليقرأ الإيصال من أين
    جاء القرار بصدق.
    """
    obj = _extract_json_object(str(text or ""))
    if obj is None:
        return None
    task = obj.get("task")
    if not isinstance(task, str) or task not in CLASSIFIABLE_TASKS:
        return None
    confidence = obj.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not (0.0 <= float(confidence) <= 1.0):
        return None
    raw_keywords = obj.get("matched_keywords", ())
    keywords: tuple[str, ...] = ()
    if isinstance(raw_keywords, list):
        cleaned = [
            kw
            for kw in raw_keywords
            if isinstance(kw, str)
            and kw
            and len(kw) <= MAX_CLASSIFIER_KEYWORD_LEN
            and "\n" not in kw
            and "\x00" not in kw
        ][:MAX_CLASSIFIER_KEYWORDS]
        keywords = tuple(cleaned)
    return Classification(
        TaskType(task),
        float(confidence),
        keywords,
        (),
        classifier=f"brain:{brain_name}",
    )


def classifier_prompt(goal: str) -> str:
    """التوجيه العربي الحتمي لمصنّف الدماغ — نفس الهدف = نفس التوجيه بالبايت."""
    return _CLASSIFIER_PROMPT.format(goal=str(goal).strip())


def classify_with_brain(goal: str, brain: _PlannerBrain) -> tuple[Classification, str]:
    """صنّف بالدماغ خلف التحقق الحتمي — أو رجع آمنًا للجدول الحتمي.

    يعيد زوجًا: التصنيف ثم الملاحظة العربية — التصنيف إما قرار دماغ اجتاز
    كل البوابات والتحقق الحتمي، أو قرار الجدول الحتمي الأصلي؛ والملاحظة
    تشرح ما جرى بصدق في الحالين.
    """
    fallback = classify(goal)
    brain_name = str(getattr(brain, "name", "brain") or "brain")

    try:
        proposal = brain.propose(classifier_prompt(goal))
    except Exception as exc:  # noqa: BLE001 — خطأ الدماغ رجوع موثق لا انهيار
        note = f"تعذّر استشارة الدماغ للتصنيف ({type(exc).__name__}) — الجدول الحتمي قرر"
        return fallback, note
    if not getattr(proposal, "accepted", False):
        reasons = "؛ ".join(
            v.details_ar
            for v in getattr(proposal, "verdicts", ()) or ()
            if not v.passed and v.details_ar
        )
        note = "اقتراح التصنيف مرفوض عند البوابات — الجدول الحتمي قرر" + (
            f": {reasons}" if reasons else ""
        )
        return fallback, note

    classification = parse_brain_classification(getattr(proposal, "text", "") or "", brain_name)
    if classification is None:
        note = "تصنيف الدماغ فشل التحقق الحتمي (نوع/ثقة) — الجدول الحتمي قرر"
        return fallback, note
    note = f"التصنيف من الدماغ ({brain_name}) — اجتاز البوابات والتحقق الحتمي"
    return classification, note


def parse_brain_plan(
    text: str, brain_name: str, classification: Classification | None = None
) -> Plan | None:
    """حوّل نص الدماغ إلى خطة موثّقة — أو None إن أخفق أي تحقق حتمي.

    التحقق بنيوي صارم (المهمة، الأدوات، التسلسل، المسار الواحد الموجود،
    حدود الأطوال) — لا قبول لأي اقتراح خارج العقد، والفشل صامت بحكم
    النوع (None) والمستدعي يوثّق الرجوع العربي.

    التدريج مقصود: المسار حقل دلالي — تجاوز حده أو فساده يرفض الخطة كلها؛
    أما سبب الخطوة (cosmetic) فتجاوز حده يُستبدل بالسبب الافتراضي الحتمي
    بدل رفض خطة سليمة — الدماغ الثرثار لا يُسقط التنفيذ الصحيح.
    """
    obj = _extract_json_object(str(text or ""))
    if obj is None:
        return None
    task = obj.get("task")
    if not isinstance(task, str) or task not in ALLOWED_TASKS:
        return None
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list) or not (1 <= len(raw_steps) <= MAX_BRAIN_STEPS):
        return None
    cleaned: list[tuple[str, str, str]] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            return None
        tool = raw.get("tool")
        if not isinstance(tool, str) or tool not in BRAIN_TOOLS:
            return None
        path = _clean_step_value(raw.get("path"), max_len=MAX_BRAIN_PATH_LEN)
        if path is None or not Path(path).exists():
            return None
        reason = _clean_step_value(raw.get("reason_ar"), max_len=MAX_BRAIN_REASON_LEN) or ""
        cleaned.append((tool, path, reason))

    tools_seq = tuple(t for t, _, _ in cleaned)
    if tools_seq not in _ALLOWED_SEQUENCES[task]:
        return None
    paths = {p for _, p, _ in cleaned}
    if len(paths) != 1:
        return None

    if classification is not None:
        # تماسك السلسلة: خطة المخطط يجب أن تعتُد بقرار المصنّف نفسه —
        # تنافرهما رفض للخطة كلها مع رجوع موثق عند المستدعي.
        if classification.task.value != task:
            return None
        cls = classification
    else:
        cls = Classification(TaskType(task), 1.0, (), ())
    steps = tuple(
        Step(tool, {"path": path}, reason or _default_reason_ar(tool))
        for tool, path, reason in cleaned
    )
    return Plan(cls, steps, 0.0, (), planner=f"brain:{brain_name}")


def _default_reason_ar(tool: str) -> str:
    """سبب عربي افتراضي حتمي إن أغفل الدماغ حقل السبب."""
    return (
        "مراجعة حتمية بقواعد AST — بلا نموذج وبلا شبكة"
        if tool == "review"
        else "إصلاح آلي للملاحظات القابلة للإصلاح ثم إعادة فحص"
    )


def plan_with_brain(
    goal: str,
    brain: _PlannerBrain,
    *,
    context: dict[str, Any] | None = None,
    classification: Classification | None = None,
) -> tuple[Plan, str]:
    """خطّط بالدماغ خلف التحقق الحتمي — أو رجع آمنًا للمخطط الحتمي.

    ``classification`` اختياري: قرار مصنّف جاهز (مثل ناتج
    ``classify_with_brain``) يُعتمد أساسًا للرجوع ويُلزم خطة الدماغ بالتماس
    معه؛ وغيابه يعيد السلوك السابق حرفيًا (تصنيف حتمي محلي).

    يعيد زوجًا: الخطة ثم الملاحظة العربية — الخطة إما خطة دماغ اجتازت كل
    البوابات والتحقق، أو الخطة الحتمية الأصلية؛ والملاحظة تشرح ما جرى
    بصدق — تُطبع للمستخدم وتُحفظ في ملاحظات الخطة نفسها.
    """
    if classification is None:
        classification = classify(goal)
    fallback = route(classification, context=context)
    brain_name = str(getattr(brain, "name", "brain") or "brain")

    try:
        proposal = brain.propose(planner_prompt(goal))
    except Exception as exc:  # noqa: BLE001 — خطأ الدماغ رجوع موثق لا انهيار
        note = f"تعذّر استشارة الدماغ ({type(exc).__name__}) — رجوع للمخطط الحتمي"
        return _with_note(fallback, note), note
    if not getattr(proposal, "accepted", False):
        reasons = "؛ ".join(
            v.details_ar
            for v in getattr(proposal, "verdicts", ()) or ()
            if not v.passed and v.details_ar
        )
        note = "اقتراح الدماغ مرفوض عند البوابات — رجوع للمخطط الحتمي" + (
            f": {reasons}" if reasons else ""
        )
        return _with_note(fallback, note), note

    plan = parse_brain_plan(getattr(proposal, "text", "") or "", brain_name, classification)
    if plan is None:
        note = "خطة الدماغ فشلت التحقق الحتمي (مهمة/أدوات/مسار/تماسك التصنيف) — رجوع للمخطط الحتمي"
        return _with_note(fallback, note), note
    note = f"المخطط من الدماغ ({brain_name}) — اجتاز البوابات والتحقق الحتمي"
    return _with_note(plan, note), note


def _with_note(plan: Plan, note: str) -> Plan:
    """أضف الملاحظة العربية للخطة إن لم تكن فيها — Plans مجمّدة."""
    if note in plan.notes_ar:
        return plan
    return Plan(
        plan.classification,
        plan.steps,
        plan.estimated_cost,
        plan.notes_ar + (note,),
        planner=plan.planner,
    )
