"""zyko.ai.brains — عقول طبقة الذكاء: كل اقتراح يمرّ بوابة قبل قبوله.

القاعدة الذهبية للمرحلة 8: العقل — حتميًا كان (المخطط) أو نموذجًا
لغويًا لاحقًا — لا يلمس المشروع مباشرة. اقتراحه نصّ يُفحص ببوابتي
المصنع الحتميتين (PII ثم RTL — نفس ترتيب المراحل دائمًا)، ولا يُقبل
إلا إذا اجتازهما. العقل «يضيف»، والبوابات «تحكم» — لا استثناء ولا
تجاوز، وهذا هو العقد الذي سيُجمَّع فوقه ZYKO AI الأقوى لاحقًا.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from zyko.coder.heuristics import draft_plan
from zyko.tools.pii_ar import scan as pii_scan
from zyko.tools.rtl.core import RTLChecker


# --------------------------------------------------------------- العقود
@dataclass(frozen=True)
class GateVerdict:
    """حكم بوابة واحدة على اقتراح: هل اجتازها؟ وما الدليل؟"""

    gate: str  # "planner" | "pii" | "rtl"
    passed: bool
    details_ar: str = ""  # دليل عربي قصير يُنسخ في الإيصال كما هو


@dataclass(frozen=True)
class Proposal:
    """اقتراح عقل: نص + مصدره + حتميته + أحكام بواباته بالترتيب."""

    text: str
    brain: str
    deterministic: bool
    verdicts: tuple[GateVerdict, ...] = ()

    @property
    def accepted(self) -> bool:
        """القبول = نص غير فارغ + اجتياز كل البوابات المُسجَّلة."""
        return bool(self.text.strip()) and bool(self.verdicts) and all(
            v.passed for v in self.verdicts
        )


@runtime_checkable
class Brain(Protocol):
    """عقد العقل الأدنى: طلب نصّي ⇒ اقتراح مفحوص البوابات."""

    name: str
    deterministic: bool

    def propose(self, request: str) -> Proposal: ...


# --------------------------------------------------------------- البوابات
def check_proposal_gates(text: str) -> tuple[GateVerdict, ...]:
    """بوابتا المصنع على أي اقتراح نصي — الترتيب ثابت: PII ثم RTL.

    - PII: أي بيان شخصي مكتشف (هاتف، بريد، هوية...) ⇒ رفض قاطع.
    - RTL: خطأ اتجاه (severity=error) ⇒ رفض؛ التحذيرات والمعلومات
      تُسجَّل في الدليل ولا تمنع القبول (النص العربي الممزوج
      بمعرّفات لاتينية حالة طبيعية في خطط المشاريع).
    """
    pii_hits = pii_scan(text)
    if pii_hits:
        kinds = ", ".join(sorted({h.type for h in pii_hits}))
        pii = GateVerdict(
            gate="pii",
            passed=False,
            details_ar=f"مرفوض: عُثر على {len(pii_hits)} بيانًا شخصيًا ({kinds})",
        )
        rtl = GateVerdict(gate="rtl", passed=False, details_ar="لم يُفحص — رفض سابق في بوابة PII")
        return (pii, rtl)

    pii = GateVerdict(gate="pii", passed=True, details_ar="نظيف — لا بيانات شخصية")
    rtl_errors = [
        f
        for f in RTLChecker().check_source(text, "text", "proposal.txt")
        if f.severity == "error"
    ]
    if rtl_errors:
        rtl = GateVerdict(
            gate="rtl",
            passed=False,
            details_ar=f"مرفوض: {len(rtl_errors)} خطأ اتجاه ({rtl_errors[0].rule})",
        )
    else:
        rtl = GateVerdict(gate="rtl", passed=True, details_ar="اجتياز — لا أخطاء اتجاه")
    return (pii, rtl)


# --------------------------------------------------------------- العقول
class PlannerBrain:
    """العقل الافتراضي الحتمي: مخطط ``zyko.coder`` — بلا نموذج وبلا شبكة.

    يولّد خطة مشروع من وصف عربي عبر المخطط الحتمي نفسه الذي يغذّي
    ``zyko new``، ثم يفحص خطته وملخصه بالبوابتين قبل التسليم.
    """

    name = "planner"
    deterministic = True

    def propose(self, request: str) -> Proposal:
        text = str(request).strip() if request is not None else ""
        try:
            plan = draft_plan(text)
        except Exception as exc:  # لا استثناء خارج طبقة الذكاء أبدًا
            return Proposal(
                text="",
                brain=self.name,
                deterministic=self.deterministic,
                verdicts=(
                    GateVerdict(
                        gate="planner",
                        passed=False,
                        details_ar=f"فشل التخطيط الهيكلي — {type(exc).__name__}",
                    ),
                ),
            )
        problems = plan.validate()
        planner = GateVerdict(
            gate="planner",
            passed=not problems,
            details_ar="مخطط صالح" if not problems else "؛ ".join(problems),
        )
        summary = plan.summary_ar()
        return Proposal(
            text=summary,
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=(planner,) + check_proposal_gates(summary),
        )


class GatedBrain:
    """غلاف يفرض بوابات المصنع على أي عقل يُمرَّر له.

    هكذا سيُوصل نموذج لغوي لاحقًا: ``GatedBrain(OllamaBrain(...))`` —
    نصّ النموذج لا يُقبل قبل بوابة PII وبوابة RTL، والجلسة ترفض
    الاقتراح كاملًا عند أول رفض. العقل يُضاف، والبوابات لا تُزال.
    """

    def __init__(self, brain: Brain) -> None:
        self._brain = brain
        self.name = f"gated:{getattr(brain, 'name', 'unknown')}"
        self.deterministic = bool(getattr(brain, "deterministic", False))

    def propose(self, request: str) -> Proposal:
        try:
            raw = self._brain.propose(str(request))
        except Exception as exc:  # خطأ العقل نفسه لا يتجاوز البوابة
            return Proposal(
                text="",
                brain=self.name,
                deterministic=self.deterministic,
                verdicts=(
                    GateVerdict(
                        gate="brain",
                        passed=False,
                        details_ar=f"العقل أثار خطأ — {type(exc).__name__}",
                    ),
                ),
            )
        text = str(getattr(raw, "text", "") or "")
        verdicts = check_proposal_gates(text)
        # تُسبقها أحكام العقل نفسه إن وُجدت (الترتيب: عقل ← PII ← RTL)
        own = tuple(getattr(raw, "verdicts", ()) or ())
        return Proposal(
            text=text,
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=own + verdicts,
        )
