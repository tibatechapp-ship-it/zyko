"""zyko.mind.core — حد العملية الموحد: القلب النموذجي خلف واجهة واحدة.

«القلب النموذجي (model core) واجهة واحدة عبر حد العملية» — عقد
``docs/MIND.md`` §6.1. كل ما فيه ذكاء نموذجي في الحلقة الإدراكية يمرّ
من هنا: ``ModelCore`` بروتوكول من عملية واحدة — ``respond`` — والاستبدال
(سحابي ↔ محلي ↔ وهمي حتمي) لا يلمس بقية الحلقة إطلاقًا.

التنفيذات الثلاثة المتعارف عليها:

  - ``DeterministicCore``: الافتراضي — بلا نموذج وبلا شبكة وبلا مفاتيح.
    يعتمد نصوصًا حتمية مشتقة من الطلب نفسه؛ هو ما يجعل الحلقة كاملة
    قابلة للاختبار في بيئة بلا شبكة (معيار إتمام المرحلة A).
  - ``BrainCore``: محوِّل يرفع أي عقل من طبقة ``zyko.ai`` (المخطط
    الحتمي، Ollama، Qwen، BestOf...) إلى حد العملية الموحد — نتيجة العقل
    المرفوضة تعود نصًا فارغًا ودليلًا موثقًا، لا استثناءً خارج.
  - ``ScriptedCore``: نموذج وهمي حتمي للاختبارات — جدول (مفتاح ⇒ رد)
    ثابت، بلا شبكة ولا عشوائية ولا حالة خفية.

قاعدة الحد الواحد: أي قلب يرفع استثناءً في ``respond`` يُبْتَلَع في
النقطة الواحدة التي تُستدعى فيها — فشل العقل دليلٌ يُوثَّق، لا انهيار
للحلقة. والبوابات (PII ← RTL) تقرر في ما بعد على أي نص عاد من أي قلب.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from zyko.ai.brains import Brain, GateVerdict, Proposal, check_proposal_gates
from zyko.mind.perception import normalize_goal


@runtime_checkable
class ModelCore(Protocol):
    """حد العملية الموحد: طلب نصّي ⇒ نصّ مقترح — لا شيء آخر يمرّ من الحد."""

    name: str
    deterministic: bool

    def respond(self, request: str, *, context: str = "") -> str: ...


# --------------------------------------------------------------- الأنوية
class DeterministicCore:
    """القلب الحتمي الافتراضي — بلا نموذج وبلا شبكة وبلا مفاتيح.

    نصوصه مشتقة حتميًا من الطلب نفسه: ملخص المخطط الهيكلي لمهام البناء
    (عبر ``draft_plan`` الذي يخدم ``zyko new`` نفسه)، ونص وصفي ثابت
    لغيرها. إن فشل المخطط لأي سبب فالنص المشتق الوصفي هو البديل —
    لا استثناء يخرج من الحد أبدًا.
    """

    name = "deterministic"
    deterministic = True

    def respond(self, request: str, *, context: str = "") -> str:
        """نص حتمي مشتق من الطلب — نفس الطلب يعطي نفس النص بالبايت."""
        goal = normalize_goal(request)
        if not goal:
            return ""
        try:
            from zyko.coder.heuristics import draft_plan

            plan = draft_plan(goal)
            return plan.summary_ar()
        except Exception:  # noqa: BLE001 — فشل المخطط لا يخرج من الحد
            return f"طلب: {goal}"


class BrainCore:
    """محوِّل عقول طبقة ``zyko.ai`` إلى حد العملية الموحد.

    أي كائن يحقق عقد ``Brain`` (``propose`` ⇒ ``Proposal``) يُرفَع من
    هنا: نص الاقتراح المقبول هو الرد، والمرفوض نص فارغ بدليل عربي
    يبقى في ``last_verdicts`` للتوثيق — والعقل نفسه لا يُستدعى مرتين.
    """

    def __init__(self, brain: Brain) -> None:
        self._brain = brain
        self.name = f"core:{getattr(brain, 'name', 'unknown')}"
        self.deterministic = bool(getattr(brain, "deterministic", False))
        self.last_verdicts: tuple[GateVerdict, ...] = ()

    def respond(self, request: str, *, context: str = "") -> str:
        """نص العقل إن قُبل، أو فارغ مع دليل موثّق — لا استثناء خارج."""
        self.last_verdicts = ()
        try:
            proposal: Proposal = self._brain.propose(str(request))
        except Exception as exc:  # noqa: BLE001 — فشل العقل دليل لا انهيار
            self.last_verdicts = (
                GateVerdict(
                    gate="core",
                    passed=False,
                    details_ar=f"العقل أثار خطأ عند الحد — {type(exc).__name__}",
                ),
            )
            return ""
        self.last_verdicts = tuple(getattr(proposal, "verdicts", ()) or ())
        text = str(getattr(proposal, "text", "") or "")
        return text if getattr(proposal, "accepted", False) else ""


class ScriptedCore:
    """نموذج وهمي حتمي للاختبارات: جدول (مفتاح ⇒ رد) ثابت بلا حالة خفية.

    الرد يُختار حتميًا: أول مفتاح يظهر في الطلب، وإلا ``default``. نفس
    الطلب يعطي نفس الرد بالبايت مهما تكرر — وعدّاد الاستدعاءات علني
    للاختبارات لا سرّية في الحالة.
    """

    def __init__(self, responses: dict[str, str], *, default: str = "") -> None:
        if not isinstance(responses, dict):
            raise ValueError("الردود يجب أن تكون جدول (مفتاح ⇒ رد)")
        self._responses = dict(responses)
        self._default = str(default)
        self.calls = 0
        self.name = "scripted"
        self.deterministic = True

    def respond(self, request: str, *, context: str = "") -> str:
        """رد حتمي من الجدول — بلا شبكة وبلا عشوائية."""
        self.calls += 1
        text = normalize_goal(request)
        for key, response in self._responses.items():
            if key and key in text:
                return response
        return self._default


def core_report(core: ModelCore) -> dict[str, Any]:
    """بطاقة القلب للحقل الموثّق في الإيصال — اسمه وحتميته فحسب."""
    return {
        "name": str(getattr(core, "name", "unknown")),
        "deterministic": bool(getattr(core, "deterministic", False)),
    }


__all__ = [
    "BrainCore",
    "DeterministicCore",
    "ModelCore",
    "ScriptedCore",
    "check_proposal_gates",
    "core_report",
]
