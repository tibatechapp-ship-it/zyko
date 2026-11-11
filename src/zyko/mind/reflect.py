"""zyko.mind.reflect — الانعكاس وإعادة المحاولة: حرّاس مخرجات وميزانية محدودة.

الأولوية 2 من خريطة الاستقلال: تحويل «النقد ثم جولة إصلاح واحدة» إلى
**حلقة ذاتية التصحيح موثقة**: كل مرحلة يفحص ناتجها **حارس حتمي**، وكل
فشل يولّد **ملاحظة انعكاس عربية** تُوثَّق وتعود مدخلًا للمحاولة التالية،
وإعادة المحاولة نفسها تحت **ميزانية صارمة لكل مرحلة** — لا حلقة لا نهائية
ولا تجاوز سقف مهما عادى المدخل.

الركائز الأربع، كلها حتمية بالبايت وبلا اعتمادية:

  1. **الحرّاس** (``guard_perception`` / ``guard_plan`` / ``guard_execution``
     / ``guard_feedback``): فحوص ثابتة على الناتج الفعلي — التصنيف معروف؟
     المسار يطابق الجدول الحتمي للنوع؟ الأدلة الموقّعة موجودة فعلًا على
     القرص؟ الملاحظة المكثّفة تحفظ معنى الفجوات وتنضبط بالسقف وتنقّي
     الهوية (PII ← RTL بالترتيب الثابت)؟
  2. **الميزانية** (``RetryBudget``): سقف لكل مرحلة + سقف كلي صارم —
     ``consume`` يمنح أو يرفض بلا استثناء، والأسماء تُطبَّع فلا يخترق
     اسم عدوي الميزانية، والاستهلاك يُوثَّق في الإيصال حتمًا.
  3. **الانعكاس** (``reflect_note``): ملاحظة عربية حتمية من سبب الفشل
     والفجوات — أسماء الفجوات لا تُقصّ قطعًا (الضغط يحفظ المعنى)،
     والنص كله تحت سقف محارف ثابت.
  4. **الإيصال**: كل انعكاس وحكم حارس وميزانية مستهلكة تدخل
     ``MindReceipt`` وسلسلة sha256 — الجولة موثقة لا مكررة ولا صامتة.

التمييز الأخلاقي الذي يقود التصميم: إعادة المحاولة ذات معنى حيث تغيّر
الملاحظة **مدخل الفعل** فعلًا — نص القلب عند بوابة الخطة (الدرس يعيد
الاستشارة)، وملفات المشروع عند النقد (الجولة تصلح ثم تنقد ثانية).
أما المسار الحتمي الذي لا تتغير مدخلاته فإعادة أعمى له هي مسرحية لا
إصلاح — فتُرفض الموثقة لا صامتة.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from zyko.ai.brains import GateVerdict
from zyko.tools.pii_ar import scan as pii_scan
from zyko.tools.rtl.core import RTLChecker

if TYPE_CHECKING:  # الاستيراد الدائري يُكسر في الفحص النوعي فقط
    from zyko.mind.perception import Perception
    from zyko.mind.planner import MindPlan

# ------------------------------------------------------------------ السقوف
MAX_FEEDBACK_CHARS = 600  # سقف الملاحظة المنعكسة — أسماء الفجوات خارج السقف
MAX_STAGE_NAME_CHARS = 32  # سقف اسم المرحلة بعد التطبيع — لا اسم عدوي طويل
MAX_TOTAL_RETRIES = 8  # سقف الحماية الكلي: إعادة المحاولة عبر كل المراحل
DEFAULT_STAGE_RETRIES = 2  # الميزانية الافتراضية لكل مرحلة واحدة

# جدول المسار الحتمي لكل نوع — مرآة جدول الخطوات في ``planner`` تقفل
# «هل المسار صحيح؟»: أدوات الخطة وترتيبها لا يقبلان غير مطابقة الجدول.
ROUTE_TABLE: dict[str, tuple[str, ...]] = {
    "GENERATE": ("pipeline", "critic", "baseline"),
    "FIX": ("orchestrator", "orchestrator", "critic"),
    "REVIEW": ("orchestrator", "critic"),
    "ANALYZE": ("orchestrator", "critic"),
    "VERIFY": ("orchestrator", "critic"),
    "TRANSPILE": ("orchestrator", "critic"),
}

STAGE_PERCEIVE = "perceive"
STAGE_PLAN = "plan"
STAGE_EXECUTE = "execute"
STAGE_CRITIC = "critic"

_MIRSALE_STAGE = "غير-مسماة"


# ------------------------------------------------------------------ الحرّاس
@dataclass(frozen=True)
class GuardReport:
    """حكم حارس واحد على ناتج مرحلة: نجاح + دليل عربي موثق."""

    guard: str
    ok: bool
    reason_ar: str

    def to_dict(self) -> dict:
        """ممثل JSON حتمي — مفاتيح مفرزة."""
        return {"guard": self.guard, "ok": self.ok, "reason_ar": self.reason_ar}


def normalize_stage(name: object) -> str:
    """طبّع اسم المرحلة: نص، إزالة فراغات الطرفين، طي الفراغات، سقف محارف.

    أسماء المراحل مفاتيح الميزانية — الاسم العدوي (فارغ، غير نصي، طويل
    بلا حد، محارف تحكم) يُطبَّع هنا في نقطة واحدة فلا يفتح خانة ميزانية
    جديدة ولا يخرج من السقوف إطلاقًا.
    """
    text = str(name).strip() if name is not None else ""
    folded = " ".join(text.split())
    if not folded:
        return _MIRSALE_STAGE
    return folded[:MAX_STAGE_NAME_CHARS]


@dataclass(frozen=True)
class Reflection:
    """انعكاس موثق واحد: مرحلة، محاولة، سبب، ملاحظة، وهل أُعيدت المحاولة."""

    stage: str
    attempt: int
    trigger_ar: str
    feedback_ar: str
    retried: bool

    def to_dict(self) -> dict:
        """ممثل JSON حتمي — يفرز داخل الإيصال كله."""
        return {
            "stage": self.stage,
            "attempt": int(self.attempt),
            "trigger_ar": self.trigger_ar,
            "feedback_ar": self.feedback_ar,
            "retried": bool(self.retried),
        }


class RetryBudget:
    """ميزانية إعادة المحاولة: سقف لكل مرحلة + سقف كلي صارم — بلا استثناء.

    العقد: ``consume`` يعيد ``True`` إذا منحت إعادة وستهلك منها، و``False``
    إذا نفدت ميزانية المرحلة أو السقف الكلي — فقرار الحلقة عند كل فشل
    «أعيد أو أتوقف» حتمي موثق. الحالة علنية (``used``) بلا خفاء، والحدود
    السالبة أو غير العددية تُقيَّد إلى صفر لا ترمي — فالميزانية جزء من
    الحلقة التي عقدُها ألا يخرج استثناء منها أبدًا.
    """

    def __init__(
        self,
        *,
        default_limit: int = DEFAULT_STAGE_RETRIES,
        per_stage: dict[str, int] | None = None,
        total_cap: int = MAX_TOTAL_RETRIES,
    ) -> None:
        try:
            self.default_limit = max(0, int(default_limit))
        except (TypeError, ValueError):
            self.default_limit = 0
        overrides: dict[str, int] = {}
        for key, limit in (per_stage or {}).items():
            try:
                overrides[normalize_stage(key)] = max(0, int(limit))
            except (TypeError, ValueError):
                overrides[normalize_stage(key)] = 0
        self._overrides = overrides
        try:
            self.total_cap = max(0, int(total_cap))
        except (TypeError, ValueError):
            self.total_cap = 0
        self._used: dict[str, int] = {}
        self.total_used = 0

    # ------------------------------------------------------------ القراءة
    def limit(self, stage: object) -> int:
        """سقف المرحلة بعد التطبيع — الاستثناء المفروض يغلب الافتراضي."""
        return self._overrides.get(normalize_stage(stage), self.default_limit)

    def used(self, stage: object) -> int:
        """ما استُهلك من ميزانية المرحلة حتى الآن."""
        return self._used.get(normalize_stage(stage), 0)

    def remaining(self, stage: object) -> int:
        """ما تبقى من ميزانية المرحلة."""
        return max(0, self.limit(stage) - self.used(stage))

    def can_retry(self, stage: object) -> bool:
        """هل تسمح ميزانية المرحلة **والسقف الكلي** بإعادة واحدة أخرى؟"""
        return self.remaining(stage) > 0 and self.total_used < self.total_cap

    # ------------------------------------------------------------ الكتابة
    def consume(self, stage: object) -> bool:
        """اطلب إعادة واحدة: تُمنح وتستهلك إن سمحت الميزانية، أو تُرفض."""
        key = normalize_stage(stage)
        if not self.can_retry(key):
            return False
        self._used[key] = self.used(key) + 1
        self.total_used += 1
        return True

    # ------------------------------------------------------------ التوثيق
    def to_dict(self) -> dict:
        """ممثل JSON حتمي — السقوف والمستخدم مفرزون بلا أي زمن."""
        return {
            "default_limit": self.default_limit,
            "total_cap": self.total_cap,
            "total_used": self.total_used,
            "limits": {k: v for k, v in sorted(self._overrides.items())},
            "used": {k: v for k, v in sorted(self._used.items())},
        }


def guard_perception(perception: "Perception") -> GuardReport:
    """حارس الإدراك: التصنيف معروف والثقة موجبة ومعيارا الهوية محفوظان.

    «هل التصنيف صحيح؟» بالحد الأدنى المضمون: نوع غير ``UNKNOWN`` بثقة
    أكبر من صفر، ومعيارا الهوية (لا بيانات شخصية، اتجاه سليم) موجودان
    فلا يُدرَك ناتج ساقط الهوية — فحص حتمي على كائن الإدراك نفسه.
    """
    kind_value = getattr(getattr(perception, "kind", None), "value", None)
    confidence = getattr(getattr(perception, "classification", None), "confidence", 0.0)
    criteria = [str(getattr(c, "text_ar", "")) for c in getattr(perception, "criteria", ())]
    kinds = [str(getattr(c, "kind", "")) for c in getattr(perception, "criteria", ())]
    has_identity = kinds.count("always") >= 2
    problems: list[str] = []
    if kind_value in (None, "UNKNOWN"):
        problems.append(f"النوع غير معروف ({kind_value or 'مفقود'})")
    try:
        conf_ok = float(confidence) > 0.0
    except (TypeError, ValueError):
        conf_ok = False
    if not conf_ok:
        problems.append(f"الثقة غير موجبة ({confidence})")
    if not has_identity:
        problems.append("معيارا الهوية غير محفوظين في المعايير")
    if problems:
        return GuardReport(
            guard="perception",
            ok=False,
            reason_ar="؛ ".join(problems),
        )
    return GuardReport(
        guard="perception",
        ok=True,
        reason_ar=(f"النوع {kind_value} بثقة {float(confidence):.2f} — {len(criteria)} معيارًا"),
    )


def guard_plan(plan: "MindPlan", perception: "Perception | None" = None) -> GuardReport:
    """حارس الخطة: مقبولة + الأدوات والترتيب مطابقة للجدول الحتمي للنوع.

    «هل المسار صحيح؟» تُقفل هنا: الخطة المقبولة يجب أن تحمل خطوات أدواتها
    وترتيبها في صورة جدول النوع الحتمي مرآةً (``ROUTE_TABLE``) — أي اقتراح
    مسار موازٍ أو ترتيب مقلوب يُرفض بدليل عربي، حتى لو اجتازت نصوصه
    البوابات النصية.
    """
    steps = list(getattr(plan, "steps", ()) or ())
    verdicts = list(getattr(plan, "verdicts", ()) or ())
    tools = tuple(str(getattr(s, "tool", "")) for s in steps)
    indices = [int(getattr(s, "index", 0)) for s in steps]
    problems: list[str] = []
    if not steps:
        problems.append("الخطة بلا خطوات تنفيذ")
    if verdicts and not all(getattr(v, "passed", False) for v in verdicts):
        failed = "؛ ".join(
            f"{getattr(v, 'gate', 'بوابة')}: {getattr(v, 'details_ar', '')}"
            for v in verdicts
            if not getattr(v, "passed", False)
        )
        problems.append(f"أحكام بوابات ساقطة — {failed}")
    if perception is not None and steps:
        kind_value = getattr(getattr(perception, "kind", None), "value", None)
        expected = ROUTE_TABLE.get(str(kind_value))
        if expected is None:
            problems.append(f"النوع {kind_value} بلا جدول مسار حتمي")
        elif tools != expected:
            problems.append(f"المسار لا يطابق الجدول الحتمي — المتوقع {expected} والواقع {tools}")
        if indices != list(range(1, len(steps) + 1)):
            problems.append(f"ترقيم الخطوات غير متسلسل {indices}")
    if problems:
        return GuardReport(guard="plan", ok=False, reason_ar="؛ ".join(problems))
    return GuardReport(
        guard="plan",
        ok=True,
        reason_ar=f"الخطة مقبولة — {len(steps)} خطوة بمسار مطابق للجدول الحتمي",
    )


def guard_execution(step: object, out_path: object = None, *, write: bool = True) -> GuardReport:
    """حارس التنفيذ: الناتج سليم والأدلة الموقّعة موجودة فعلًا على القرص.

    كل بصمة sha256 في الدليل يجب أن يقابلها ملف حقيقي قابل للقراءة —
    «إيصال بلا أثر على القرص» رفض قاطع. الوضع الجاف يُوثَّق تخطين صريحًا:
    الأدلة تُفحص عند وضع الكتابة، والفحص نفسه مسقوف (64 دليلًا) فحتمية
    محدودة التكلفة لا تنمو مع حجم الناتج.
    """
    ok = bool(getattr(step, "ok", False))
    evidence = dict(getattr(step, "evidence", {}) or {})
    if not ok:
        details_ar = str(getattr(step, "details_ar", "") or "بلا تفاصيل")
        return GuardReport(guard="execute", ok=False, reason_ar=f"الخطوة فشلت — {details_ar}")
    if not write:
        return GuardReport(
            guard="execute",
            ok=True,
            reason_ar="تشغيل جاف — فحص الأدلة الموثقة يُفعَّل عند وضع الكتابة",
        )
    if not evidence:
        return GuardReport(
            guard="execute", ok=False, reason_ar="لا أدلة موقعة في وضع الكتابة — الناتج غير مثبت"
        )
    missing: list[str] = []
    checked = 0
    base = Path(str(out_path)) if out_path is not None else None
    for rel in sorted(evidence):
        if checked >= 64:
            break
        checked += 1
        candidate = Path(str(rel))
        if base is not None and not candidate.is_absolute():
            candidate = base / candidate
        if not candidate.is_file():
            missing.append(str(rel))
    if missing:
        shown = "، ".join(missing[:3])
        return GuardReport(
            guard="execute",
            ok=False,
            reason_ar=f"{len(missing)} دليلًا بلا ملف على القرص — {shown}",
        )
    return GuardReport(
        guard="execute",
        ok=True,
        reason_ar=f"الناتج مثبت — {checked} دليلًا موقّعًا موجودة على القرص",
    )


def guard_feedback(feedback: object, gaps: tuple[str, ...] = ()) -> GuardReport:
    """حارس الملاحظة المنعكسة: الضغط يحفظ المعنى وينضبط بالسقف وينقّى الهوية.

    الملاحظة تعود **مدخلًا** للمحاولة التالية، فتُفحص كأي اقتراح نصي:
    PII ثم RTL بالترتيب الثابت، وسقف المحارف، وكل فجوة مسمّاة مذكورة
    نصًا في الملاحظة — «تكثيف يفقد فجوة» رفض، فلا تمحو الجولة ملاحظة
    سببها بلا أثر.
    """
    text = feedback if isinstance(feedback, str) else str(feedback or "")
    problems: list[str] = []
    if not text.strip():
        return GuardReport(guard="feedback", ok=False, reason_ar="الملاحظة فارغة")
    hits = pii_scan(text)
    if hits:
        kinds = "، ".join(sorted({h.type for h in hits}))
        return GuardReport(
            guard="feedback",
            ok=False,
            reason_ar=f"مرفوض: {len(hits)} بيانًا شخصيًا في الملاحظة ({kinds})",
        )
    rtl_errors = [
        f for f in RTLChecker().check_source(text, "text", "feedback.txt") if f.severity == "error"
    ]
    if rtl_errors:
        return GuardReport(
            guard="feedback",
            ok=False,
            reason_ar=f"مرفوض: {len(rtl_errors)} خطأ اتجاه في الملاحظة",
        )
    if len(text) > MAX_FEEDBACK_CHARS:
        # السقف عقد على النثر لا على المعنى: بايتات الفجوات المحفوظة
        # في النص تُعفى من الحساب — فلا يعاقب الحارس ملاحظة فجواتها
        # كثيرة ولا يمرّر نثرًا منتفخًا بذريتها
        gap_bytes = sum(len(gap) for gap in gaps if gap and gap in text)
        prose_len = len(text) - gap_bytes
        if prose_len > MAX_FEEDBACK_CHARS:
            problems.append(
                f"نثر الملاحظة (عدا الفجوات المحفوظة) فوق السقف "
                f"({prose_len} > {MAX_FEEDBACK_CHARS} محرفًا)"
            )
    missing_gaps = [gap for gap in gaps if gap and gap not in text]
    if missing_gaps:
        shown = "؛ ".join(missing_gaps[:2])
        problems.append(f"الفجوة المفقودة من الملاحظة: {shown}")
    if problems:
        return GuardReport(guard="feedback", ok=False, reason_ar="؛ ".join(problems))
    return GuardReport(
        guard="feedback",
        ok=True,
        reason_ar=f"ملاحظة سليمة ({len(text)} محرفًا) — {len(gaps)} فجوة محفوظة المعنى",
    )


# ------------------------------------------------------------------ الانعكاس
def condense_feedback(
    reason_ar: str, gaps: tuple[str, ...], *, budget: int = MAX_FEEDBACK_CHARS
) -> str:
    """كثّف السبب والفجوات تحت السقف — أسماء الفجوات لا تُقصّ قطعًا أبدًا.

    الفجوات هي المعنى؛ النثر حولها قابل للضغط. إذا امتلأت الحيّز فتُقصّ
    جملة السبب أولًا ثم تُسقَت كليًا قبل أي فجوة — وإذا فاقت الفجوات نفسها
    السقف فتبقى كاملة موثقة (السقف عقد على النثر لا على المعنى). حتمي
    بالبايت: نفس المدخلات تعطي نفس النص.
    """
    gap_list = [str(g).strip() for g in gaps if str(g).strip()]
    reason = " ".join(str(reason_ar or "").split())
    if not gap_list:
        return reason[: max(0, int(budget))]
    gaps_text = "؛ ".join(gap_list)
    prefix = f"الفجوات: {gaps_text}"
    if len(prefix) >= int(budget):
        return prefix
    if not reason:
        return prefix
    room = int(budget) - len(prefix) - 3  # « — » الفاصلة ثلاثية المحارف
    if room <= 0:
        return prefix
    return f"{reason[:room]} — {prefix}"


def reflect_note(
    stage: object,
    *,
    reason_ar: str,
    gaps: tuple[str, ...] = (),
    attempt: int = 1,
) -> str:
    """ملاحظة الانعكاس العربية الحتمية — تعود مدخلًا للمحاولة التالية.

    البنية ثابتة: مُهيّئ المرحلة والمحاولة، ثم السبب المكثّف، ثم
    توجيه صريح بالتعلم من الفجوات. الملاحظة الناتجة تمرّ إلزاميًا على
    ``guard_feedback`` في الحلقة قبل أن تلمس أي طلب — التوليد هنا لا
    يعفيها من الفحص.
    """
    stage_name = normalize_stage(stage)
    safe_attempt = max(1, int(attempt) if str(attempt).lstrip("-").isdigit() else 1)
    header = f"انعكاس «{stage_name}» — المحاولة {safe_attempt}: "
    if gaps:
        directive = "علّم من هذه الفجوات وأعد المحاولة على أساسها"
    else:
        directive = "أعد المحاولة معالجًا سبب الفشل المذكور"
    # ميزانية النثر: السقف الكلي ناقص الهيكل الثابت (الترويسة والتوجيه
    # والفواصل) — فالناتج كله تحت السقف والفجوات خارج الحساب أصلًا
    overhead = len(header) + len(" — ") + len(directive) + len(".")
    prose_budget = max(0, MAX_FEEDBACK_CHARS - overhead)
    body = condense_feedback(reason_ar, gaps, budget=prose_budget)
    return f"{header}{body} — {directive}."


def fallback_note() -> str:
    """الملاحظة البديلة الصلبة عندما يرفض حارس الملاحظة الأصلية نفسها.

    لا PII ولا اتجاه معطوب ولا فجوات مقتبسة — نص ثابت بالبايت يضمن أن
    ما يدخل طلب القلب التالي نظيف حتى لو كانت أسباب الفشل نفسها ملطخة
    بانعكاس عدوي.
    """
    return "ملاحظة آمنة: أعد صياغة الاقتراح بلا بيانات شخصية وباتجاه عربي سليم، وعالج سبب الرفض الموثق."


def gate_verdict_summary(verdicts: tuple[GateVerdict, ...]) -> str:
    """ملخص عربي حتمي لأحكام البوابات الساقطة — بذرة الانعكاس عند الخطة."""
    failed = [v for v in verdicts or () if not getattr(v, "passed", False)]
    if not failed:
        return "كل البوابات ناجحة"
    return "؛ ".join(
        f"{getattr(v, 'gate', 'بوابة')}: {getattr(v, 'details_ar', '')}".strip() for v in failed
    )


__all__ = [
    "DEFAULT_STAGE_RETRIES",
    "MAX_FEEDBACK_CHARS",
    "MAX_STAGE_NAME_CHARS",
    "MAX_TOTAL_RETRIES",
    "ROUTE_TABLE",
    "Reflection",
    "RetryBudget",
    "STAGE_CRITIC",
    "STAGE_EXECUTE",
    "STAGE_PERCEIVE",
    "STAGE_PLAN",
    "GuardReport",
    "condense_feedback",
    "fallback_note",
    "gate_verdict_summary",
    "guard_execution",
    "guard_feedback",
    "guard_perception",
    "guard_plan",
    "normalize_stage",
    "reflect_note",
]
