"""المكوّن 2 — route: أي أداة؟ بأي ترتيب؟ (خطة محسوسة من قرار التصنيف).

يحوّل ``Classification`` إلى ``Plan``: قائمة خطوات (``Step``) كلٌّ بأداة
ووسائطها وسببها العربي. القواعد حتمية بالكامل — بلا ``datetime`` ولا
``random`` ولا ``os.environ``: نفس التصنيف + نفس السياق = نفس الخطة بالبايت.

جدول القرار (موثَّق بالاختبارات الإلزامية):

    REVIEW     → [review]
    FIX        → [review, fix]   (الإصلاح يبدأ بمراجعة — ترتيب ثابت)
    GENERATE   → [generate]
    TRANSPILE  → [transpile]
    VERIFY     → [verify]
    ANALYZE    → [baseline_check]
    UNKNOWN    → خطوات فارغة + ملاحظة عربية واضحة

الوسائط تُستخرج من ``context`` بسلاسل بدائل ثابتة لكل أداة؛ إن غاب
المفتاح تبقى القيمة نصاً فارغاً وتُضاف ملاحظة عربية تشرح المفتاح الناقص —
العقل يقرر «أي أداة» دائماً، وتعبئة الوسائط مسؤولية المستدعي.
كل الأدوات حتمية بلا نموذج ⇒ ``estimated_cost == 0.0`` دائماً.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zyko.orchestrator.classify import Classification, TaskType

# سلاسل البدائل الثابتة لاستخراج وسيطة كل أداة من السياق (الترتيب = الأولوية).
_ARG_KEYS: dict[str, tuple[str, ...]] = {
    "review": ("path", "target", "file"),
    "fix": ("path", "target", "file"),
    "generate": ("description",),
    "transpile": ("file", "path"),
    "verify": ("receipt", "path"),
    "baseline_check": ("src", "path"),
}

# ملاحظة عربية حتمية عند غياب المفتاح الأساسي لكل أداة.
_MISSING_NOTE_AR: dict[str, str] = {
    "review": "لم يُحدد المسار — مرّره في context['path']",
    "fix": "لم يُحدد المسار — مرّره في context['path']",
    "generate": "لم يُحدد الوصف — مرّره في context['description']",
    "transpile": "لم يُحدد ملف ضاد — مرّره في context['file']",
    "verify": "لم يُحدد إيصال — مرّره في context['receipt']",
    "baseline_check": "",  # الافتراضي «.» يعمل دائماً — لا ملاحظة
}

_REVIEW_REASON_AR = "مراجعة حتمية بقواعد AST — بلا نموذج وبلا شبكة"
_FIX_REVIEW_REASON_AR = "الإصلاح يبدأ بمراجعة تحدد ما يمكن إصلاحه آلياً"
_FIX_REASON_AR = "إصلاح آلي للملاحظات القابلة للإصلاح ثم إعادة فحص"
_GENERATE_REASON_AR = "توليد مشروع من قوالب محققّة عبر بوابة الموافقة"
_TRANSPILE_REASON_AR = "ترجمة ملف ضاد إلى بايثون عبر المترجم المستقل"
_VERIFY_REASON_AR = "تحقق بلا ثقة من الإيصال: إعادة حساب كل البصمات"
_BASELINE_REASON_AR = "مقارنة الوضع الحالي بخط الأساس لمنع الانحدار"
_UNKNOWN_NOTE_AR = "لم أفهم المهمة — وضّح أكثر"


def _first_arg(context: dict[str, Any], keys: tuple[str, ...]) -> str:
    """أول مفتاح موجود في السياق — قيمة نصية، وإلا نص فارغ."""
    for key in keys:
        value = context.get(key)
        if value is not None:
            return str(value)
    return ""


@dataclass(frozen=True)
class Step:
    """خطوة واحدة في الخطة: أداة + وسائطها + سببها العربي للعرض."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason_ar: str = ""

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON كامل للخطوة — مفاتيح ثابتة."""
        return {"tool": self.tool, "args": dict(self.args), "reason_ar": self.reason_ar}


@dataclass(frozen=True)
class Plan:
    """الخطة الكاملة: التصنيف + الخطوات + التكلفة المقدرة + ملاحظات عربية.

    ``planner`` يوثّق مصدر الخطة: ``"deterministic"`` (الافتراضي — جدول
    القرار الحتمي) أو ``"brain:<اسم>"`` (خطة دماغ حقيقية اجتازت التحقق
    الحتمي الصارم). الحقل يدخل ``to_dict`` فقط عند تخطيط دماغ — فتبقى
    إيصالات المسار الحتمي متطابقة بالبايت مع عقدها السابق.
    """

    classification: Classification
    steps: tuple[Step, ...]
    estimated_cost: float | None
    notes_ar: tuple[str, ...]
    planner: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON كامل للخطة — قابل للتسلسل والتحقق دون ثقة."""
        payload = {
            "classification": self.classification.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "estimated_cost": self.estimated_cost,
            "notes_ar": list(self.notes_ar),
        }
        if self.planner != "deterministic":  # توثيق صادق لمصدر الخطة عند وجوده
            payload["planner"] = self.planner
        return payload


def route(classification: Classification, *, context: dict[str, Any] | None = None) -> Plan:
    """حوّل قرار التصنيف إلى خطة تنفيذ حتمية — نفس المدخل = نفس الخطة."""
    context = context or {}
    notes: list[str] = []
    steps: list[Step] = []

    task = classification.task
    if task is TaskType.UNKNOWN:
        return Plan(classification, (), 0.0, (_UNKNOWN_NOTE_AR,))

    if task is TaskType.FIX:
        path = _first_arg(context, _ARG_KEYS["fix"])
        if not path:
            notes.append(_MISSING_NOTE_AR["fix"])
        steps.append(Step("review", {"path": path}, _FIX_REVIEW_REASON_AR))
        steps.append(Step("fix", {"path": path}, _FIX_REASON_AR))
    elif task is TaskType.REVIEW:
        path = _first_arg(context, _ARG_KEYS["review"])
        if not path:
            notes.append(_MISSING_NOTE_AR["review"])
        steps.append(Step("review", {"path": path}, _REVIEW_REASON_AR))
    elif task is TaskType.GENERATE:
        description = _first_arg(context, _ARG_KEYS["generate"])
        if not description:
            notes.append(_MISSING_NOTE_AR["generate"])
        steps.append(Step("generate", {"description": description}, _GENERATE_REASON_AR))
    elif task is TaskType.TRANSPILE:
        file = _first_arg(context, _ARG_KEYS["transpile"])
        if not file:
            notes.append(_MISSING_NOTE_AR["transpile"])
        steps.append(Step("transpile", {"file": file}, _TRANSPILE_REASON_AR))
    elif task is TaskType.VERIFY:
        receipt = _first_arg(context, _ARG_KEYS["verify"])
        if not receipt:
            notes.append(_MISSING_NOTE_AR["verify"])
        steps.append(Step("verify", {"receipt": receipt}, _VERIFY_REASON_AR))
    elif task is TaskType.ANALYZE:
        src = _first_arg(context, _ARG_KEYS["baseline_check"]) or "."
        steps.append(Step("baseline_check", {"src": src}, _BASELINE_REASON_AR))

    return Plan(classification, tuple(steps), 0.0, tuple(notes))
