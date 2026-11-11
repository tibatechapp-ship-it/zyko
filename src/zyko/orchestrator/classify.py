"""المكوّن 1 — classify: ما نوع المهمة؟ (طبقة قرار حتمية بحتة).

تصنيف هدف المستخدم المكتوب (عربي أو إنجليزي) إلى أحد ستة أنواع مهام، أو
UNKNOWN إن لم يُفهم. الحتمية كاملة:

* لا نموذج لغوي ولا شبكة — مطابقة كلمات مفتاحية على نص مُطبَّع.
* لا `datetime` ولا `random` ولا `os.environ` — دالة نقية.
* نفس النص يعطي نفس `Classification` بالبايت، دائماً (مُثبت باختبار 100 تشغيل).

التطبيع: تشكيلٌ وتطويلٌ تُحذف (مدى U+064B–U+0652 كاملاً بما فيه الشدّة)،
الهمزات تُوحَّد (أإآ → ا)، والمحارف اللاتينية تُقارَن بحدود كلمات لاتينية
بحتة: «fix» لا يطابق «fixture»، لكن «الـbug» الملتصقة بحرف عربي تطابق
«bug» — لأن الحد اللاتيني يقيد المحارف اللاتينية فقط. العربية تُطابَق
كSubstring لأن السوابق تلتصق بها («وأصلح» تحوي «اصلح»).

كسر التعادل ثابت وموثَّق: عند تساوي الأنواع يفوز الأعلى أولوية في
``PRIORITY`` — والسبب: «راجع وأصلح» يجب أن تُخطَّط كإصلاح كامل
``[review, fix]`` لا كمراجعة فقط، لأن خطوة fix تتضمن review في خطة العقل.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    """أنواع المهام الستة + حالة عدم الفهم."""

    REVIEW = "REVIEW"
    FIX = "FIX"
    GENERATE = "GENERATE"
    TRANSPILE = "TRANSPILE"
    VERIFY = "VERIFY"
    ANALYZE = "ANALYZE"
    UNKNOWN = "UNKNOWN"


# ترتيب كسر التعادل — ثابت وموثَّق في docstring الوحدة واختباراته.
PRIORITY: tuple[TaskType, ...] = (
    TaskType.FIX,
    TaskType.REVIEW,
    TaskType.GENERATE,
    TaskType.TRANSPILE,
    TaskType.VERIFY,
    TaskType.ANALYZE,
)

# الكلمات المفتاحية بترتيبها الثابت — التطابق يُبلَّغ بنفس الترتيب دائماً.
# النصوص هنا مُطبَّعة سلفاً (بلا همزات، بلا تشكيل): أصلح → اصلح، إيصال → ايصال.
TASK_KEYWORDS: dict[TaskType, tuple[str, ...]] = {
    TaskType.FIX: (
        "اصلح",
        "اصلاح",
        "صحح",
        "عالج",
        "معالجة",
        "bug",
        "fix",
        "repair",
    ),
    TaskType.REVIEW: (
        "راجع",
        "مراجعة",
        "تدقيق",
        "افحص",
        "review",
        "audit",
    ),
    TaskType.GENERATE: (
        "انشئ",
        "انشاء",
        "اكتب",
        "ولد",
        "مشروع جديد",
        "generate",
        "create",
        "scaffold",
    ),
    TaskType.TRANSPILE: (
        "ترجم",
        "ترجمة",
        "حول",
        "ضاد",
        ".daad",
        "daad",
        "transpile",
    ),
    TaskType.VERIFY: (
        "تحقق",
        "ايصال",
        "receipt",
        "verify",
    ),
    TaskType.ANALYZE: (
        "حلل",
        "تحليل",
        "قياس",
        "خط الاساس",
        "baseline",
        "analyze",
        "metrics",
    ),
}

# التشكيل كاملاً: تنوين + حركات + شدّة (U+0651) + سكون، والتطويل
_TASHKEEL = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_ALEF = re.compile("[أإآ]")
_SPACES = re.compile(r"\s+")
_LATIN = re.compile(r"^[a-z0-9]")
# حدود لاتينية بحتة: لا حرف لاتيني قبل/بعد الكلمة (العربي المجاور لا يمنع)
_LATIN_EDGE = r"(?<![a-z0-9]){0}(?![a-z0-9])"


@dataclass(frozen=True)
class Classification:
    """قرار التصنيف — مجمّد وقابل للتسلسل JSON.

    ``classifier`` يوثّق مصدر القرار: ``None`` (الافتراضي — الجدول الحتمي
    بلا نموذج) أو ``"brain:<اسم>"`` (تصنيف دماغ حقيقي اجتاز التحقق الحتمي
    الصارم). الحقل يدخل ``to_dict`` فقط عند تصنيف دماغ — فتبقى قرارات
    المسار الحتمي متطابقة بالبايت مع عقدها السابق، على مثال حقل
    ``planner`` في الخطة.
    """

    task: TaskType
    confidence: float
    matched_keywords: tuple[str, ...]
    alternatives: tuple[TaskType, ...]
    classifier: str | None = None

    def to_dict(self) -> dict:
        """ممثل JSON كامل — مفاتيح ثابتة وقيم قابلة للتسلسل بالبايت."""
        payload: dict = {
            "task": self.task.value,
            "confidence": self.confidence,
            "matched_keywords": list(self.matched_keywords),
            "alternatives": [t.value for t in self.alternatives],
        }
        if self.classifier is not None:
            payload["classifier"] = self.classifier
        return payload


def normalize(text: str) -> str:
    """تطبيع حتمي: طي حالة، حذف تشكيل وتطويل، توحيد الهمزات، ضبط المسافات."""
    t = ("" if text is None else str(text)).casefold()
    t = _TASHKEEL.sub("", t)
    t = _ALEF.sub("ا", t)
    return _SPACES.sub(" ", t).strip()


def _match_one(keyword: str, normalized: str) -> bool:
    """مطابقة كلمة واحدة: حدود لاتينية بحتة، Substring للعربية و«.daad»."""
    if _LATIN.match(keyword):
        return re.search(_LATIN_EDGE.format(re.escape(keyword)), normalized) is not None
    return keyword in normalized


def _matched_keywords(normalized: str, keywords: tuple[str, ...]) -> tuple[str, ...]:
    """الكلمات المتطابقة فعلاً — بترتيب الجدول الثابت (لا ترتيب النص)."""
    return tuple(kw for kw in keywords if _match_one(kw, normalized))


def _confidence(matches: int) -> float:
    """ثقة حتمية بعدد المطابقات: 1 → 0.70، 2 → 0.85، ≥3 → 0.95."""
    if matches >= 3:
        return 0.95
    if matches == 2:
        return 0.85
    return 0.70


def classify(text: str) -> Classification:
    """صنّف هدف المستخدم إلى نوع مهمة — قرار حتمي بنفس المدخل دائماً.

    تُحسب مطابقات كل نوع ثم يفوز الأعلى عدداً؛ وعند التعادل يفوز الأعلى
    في ``PRIORITY`` (FIX أولاً — انظر docstring الوحدة). بلا أي مطابقة
    يُعاد UNKNOWN بثقة 0.0.
    """
    normalized = normalize(text)
    matched_by_type: list[tuple[TaskType, tuple[str, ...]]] = []
    for task_type in PRIORITY:
        matched = _matched_keywords(normalized, TASK_KEYWORDS[task_type])
        if matched:
            matched_by_type.append((task_type, matched))

    if not matched_by_type:
        return Classification(TaskType.UNKNOWN, 0.0, (), ())

    best_count = max(len(m) for _, m in matched_by_type)
    task = next(t for t, m in matched_by_type if len(m) == best_count)
    matched = next(m for t, m in matched_by_type if t is task)
    alternatives = tuple(
        t
        for t, m in sorted(
            matched_by_type,
            key=lambda pair: (-len(pair[1]), PRIORITY.index(pair[0])),
        )
        if t is not task
    )
    return Classification(task, _confidence(best_count), matched, alternatives)
