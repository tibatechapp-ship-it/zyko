"""zyko.mind.perception — وحدة الإدراك: أول وحدة في الحلقة الإدراكية.

وحدة «الإدراك» من ``docs/MIND.md`` §6.1-1: تطبيع الطلب العربي، تصنيف
نوعه (بناء/إصلاح/مراجعة/تحليل...)، وتحديد معايير النجاح مبدئيًا — كلها
**حتمية بالبايت**: لا نموذج ولا شبكة ولا ``datetime`` ولا ``os.environ``
في هذا المسار؛ نفس الطلب يعطي نفس الإدراك دائمًا.

التصنيف نفسه مفوَّض حرفيًا لمصنّف ``zyko.orchestrator.classify`` الموثّق
(الجدول الحتمي نفسه الذي يخدم ``zyko do``) — لا إعادة تنفيذ ولا جدول
موازٍ: الإدراك يضيف التطبيع ومعايير النجاح فوق قرار المصنّف، لا يخترقه.

معايير النجاح ثلاثة أنواع حتمية:

  - ``artifact``: ملف/مجلد متوقع على القرص بعد التنفيذ.
  - ``score``: درجة مراجعة لا تقل عن حد.
  - ``explicit``: مطلب صريح في نص الهدف (اختبارات، توثيق، واجهة سطر
    أوامر) يُتحقق منه حتميًا على الناتج الفعلي.

وكل إدراك يضم معيارين ثابتَين لا يُسقَطان أبدًا: الناتج خالٍ من بيانات
شخصية، والنص العربي سليم الاتجاه — هويّة ZYKO قبل أي هدف.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zyko.orchestrator.classify import Classification, TaskType, classify
from zyko.orchestrator.context import extract_context
from zyko.pipeline.engine import MAX_DESCRIPTION_LEN

# أزواج «كلمة صريحة في الهدف ⇒ معيار نجاح» — الترتيب ثابت والفحص نصي حتمي.
_EXPLICIT_CRITERIA: tuple[tuple[str, str], ...] = (
    ("اختبار", "اختبارات المشروع موجودة على القرص"),
    ("توثيق", "توثيق المشروع (README.md) موجود"),
    ("واجهة سطر", "واجهة سطر أوامر في المشروع المولَّد"),
    ("سطر أوامر", "واجهة سطر أوامر في المشروع المولَّد"),
)


@dataclass(frozen=True)
class SuccessCriterion:
    """معيار نجاح واحد: نص عربي + نوع الفحص الحتمي الذي يثبته."""

    text_ar: str
    kind: str  # "artifact" | "score" | "explicit" | "always"


@dataclass(frozen=True)
class Perception:
    """إدراك الطلب: الهدف المطبَّع + نوعه + معايير النجاح + المسار المستخرج."""

    goal: str  # الهدف بعد التطبيع (strip + طي الفراغات الداخلية)
    classification: Classification
    criteria: tuple[SuccessCriterion, ...]
    target_path: str | None  # مسار ملف قائم استُخرج من الهدف — إن وُجد

    @property
    def kind(self) -> TaskType:
        """نوع المهمة — اختصار القراءة للتصنيف الداخلي."""
        return self.classification.task

    @property
    def is_existing_task(self) -> bool:
        """مهمة على كود قائم = نوع خارج البناء + مسار ملف مستخرج فعليًا."""
        return (
            self.classification.task is not TaskType.GENERATE
            and self.target_path is not None
            and Path(self.target_path).is_file()
        )


def normalize_goal(goal: str) -> str:
    """تطبيع حتمي: strip + طي تسلسلات الفراغ إلى فراغ واحد — بلا مساس بالأحرف العربية."""
    return " ".join(str(goal).split())


def _explicit_criteria(goal: str) -> tuple[SuccessCriterion, ...]:
    """معايير «explicit» من كلمات صريحة في الهدف — أول ظهور فقط لكل معيار."""
    found: list[SuccessCriterion] = []
    seen: set[str] = set()
    for keyword, criterion in _EXPLICIT_CRITERIA:
        if keyword in goal and criterion not in seen:
            found.append(SuccessCriterion(text_ar=criterion, kind="explicit"))
            seen.add(criterion)
    return tuple(found)


def _kind_criteria(task: TaskType) -> tuple[SuccessCriterion, ...]:
    """معايير النوع الحتمية — نفس الجدول لكل نوع، بلا استثناء."""
    if task is TaskType.GENERATE:
        return (
            SuccessCriterion(text_ar="مشروع مولَّد مكتمل الملفات على القرص", kind="artifact"),
            SuccessCriterion(text_ar="أدنى درجة مراجعة لا تقل عن الحد", kind="score"),
        )
    if task is TaskType.FIX:
        return (
            SuccessCriterion(
                text_ar="الملف المستهدف مُصلَّح ودرجته ارتفعت أو بقي ≥ الحد", kind="score"
            ),
            SuccessCriterion(text_ar="الملف المستهدف موجود قبل الإصلاح وبعده", kind="artifact"),
        )
    if task in (TaskType.REVIEW, TaskType.ANALYZE, TaskType.VERIFY, TaskType.TRANSPILE):
        return (
            SuccessCriterion(text_ar="تقرير الفحص أو التحويل مكتمل بلا خطأ هيكلي", kind="score"),
        )
    return ()


def _unknown_classification() -> Classification:
    """تصنيف UNKNOWN الحتمي للمدخلات غير القابلة للفهم — ثقة صفر."""
    return Classification(
        task=TaskType.UNKNOWN,
        confidence=0.0,
        matched_keywords=(),
        alternatives=(),
    )


def _identity_criteria() -> tuple[SuccessCriterion, ...]:
    """معيارا الهوية اللذان لا يُسقَطان: لا بيانات شخصية، والاتجاه سليم."""
    return (
        SuccessCriterion(text_ar="الناتج خالٍ من بيانات شخصية", kind="always"),
        SuccessCriterion(text_ar="النص العربي سليم الاتجاه بلا أخطاء RTL", kind="always"),
    )


def perceive(goal: object) -> Perception:
    """أدرِك الطلب كاملًا — بلا استثناء: مدخل غير نصي يُدرَك فشلًا هيكليًا.

    المدخل غير النصي أو الفارغ يرجع إدراكًا من نوع ``UNKNOWN`` بثقة صفر
    ومعيارَي الهوية ثابتَين — فتبقى الحلقة أعلى «دائمًا تُدرِك» ثم تُقرِّر
    البوابات المصير، لا انهيارًا عند أول مدخل عدائي.
    """
    if not isinstance(goal, str):
        return Perception(
            goal=repr(goal),
            classification=_unknown_classification(),
            criteria=_identity_criteria(),
            target_path=None,
        )
    normalized = normalize_goal(goal)
    if not normalized:
        return Perception(
            goal="",
            classification=_unknown_classification(),
            criteria=_identity_criteria(),
            target_path=None,
        )
    classification = classify(normalized)
    context = extract_context(normalized)
    target = context.get("path") or None
    criteria = _kind_criteria(classification.task) + _explicit_criteria(normalized) + _identity_criteria()
    return Perception(
        goal=normalized,
        classification=classification,
        criteria=criteria,
        target_path=target,
    )


__all__ = [
    "MAX_DESCRIPTION_LEN",
    "Perception",
    "SuccessCriterion",
    "normalize_goal",
    "perceive",
]
