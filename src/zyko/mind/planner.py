"""zyko.mind.planner — وحدة التخطيط: تفكيك الهدف إلى خطوات بمعايير قبول.

وحدة «التخطيط» من ``docs/MIND.md`` §6.1-2: خطة صريحة — خطوات بمدخلات
ومعايير قبول — نصية منظمة قابلة للفحص والاختزال. البنية نفسها حتمية
محرَّضة من الإدراك (نوع المهمة ⇒ جدول خطوات ثابت)، والعقل — أي قلب
على حد العملية الموحد — يضيف **نصًا استشاريًا** يُفحص ببوابات المصنع
(PII ← RTL بالترتيب الثابت) قبل أن يدخل الخطة: العقل يضيف، والبوابات
تُقرِّر — لا استثناء ولا تجاوز، على مثال طبقة ``zyko.ai`` كلها.

جدول الخطوات الحتمي لكل نوع:

  - ``GENERATE``: توليد (محرك الحلقة) ← فحص المعايير ← خط أساس.
  - ``FIX`` على ملف قائم: تصنيف ← توجيه ← تنفيذ موثّق بإيصال المحدّد.
  - ``REVIEW``/``ANALYZE``/``VERIFY``/``TRANSPILE``: مسار ``zyko do``
    نفسه على الملف المستهدف.
  - غير مفهوم أو بلا ملف قائم: خطة مرفوضة بدليل عربي — لا خطوات.

الخطة المرفوضة لا تنتج أي خطوة تنفيذ — هذا عقد الحلقة عند بوابة الخطة.
"""

from __future__ import annotations

from dataclasses import dataclass

from zyko.ai.brains import GateVerdict, check_proposal_gates
from zyko.mind.core import ModelCore
from zyko.mind.perception import Perception
from zyko.orchestrator.classify import TaskType

# أسماء بوابات الخطة في الإيصال — بالترتيب الثابت نفسه
PLAN_GATE_TITLE = "بوابة الخطة (قلب ← PII ← RTL)"


@dataclass(frozen=True)
class MindStep:
    """خطوة خطة واحدة: عنوان عربي + الأداة المنفِّذة + معيار قبولها."""

    index: int
    title_ar: str
    tool: str
    acceptance_ar: str


@dataclass(frozen=True)
class MindPlan:
    """الخطة الكاملة: خطوات حتمية + نص القلب الاستشاري + أحكام بواباته."""

    goal: str
    kind: TaskType
    steps: tuple[MindStep, ...]
    advisory: str  # نص القلب الاستشاري بعد اجتياز البوابات (فارغ إن رُفض)
    core_name: str
    deterministic: bool
    verdicts: tuple[GateVerdict, ...]

    @property
    def accepted(self) -> bool:
        """القبول = خطوات غير فارغة + نص القلب اجتاز البوابات كلها."""
        return bool(self.steps) and bool(self.verdicts) and all(v.passed for v in self.verdicts)

    def text_ar(self) -> str:
        """نص الخطة المختصر — للعرض وللتوثيق، حتمي بالبايت."""
        lines = [f"خطة «{self.goal}» — النوع {self.kind.value} — القلب {self.core_name}"]
        for step in self.steps:
            lines.append(f"{step.index}. {step.title_ar} [{step.tool}] — قبول: {step.acceptance_ar}")
        if self.advisory:
            lines.append(f"استشارة القلب: {self.advisory}")
        return "\n".join(lines)


def _steps_for(perception: Perception) -> tuple[MindStep, ...]:
    """جدول الخطوات الحتمي حسب النوع — نفس الإدراك يعطي نفس الخطوات."""
    task = perception.kind
    if task is TaskType.GENERATE:
        return (
            MindStep(
                index=1,
                title_ar="توليد المشروع عبر محرك الحلقة (مراجعة ← إصلاح)",
                tool="pipeline",
                acceptance_ar="أدنى درجة مراجعة ≥ الحد بعد الإصلاح",
            ),
            MindStep(
                index=2,
                title_ar="نقد الناتج على معايير النجاح المُدرَكة",
                tool="critic",
                acceptance_ar="كل معايير النجاح مثبتة على القرص",
            ),
            MindStep(
                index=3,
                title_ar="تسجيل خط الأساس وفحصه",
                tool="baseline",
                acceptance_ar="لا تراجع بعد التسجيل",
            ),
        )
    if task is TaskType.FIX:
        target = perception.target_path or "الملف المستهدف"
        return (
            MindStep(
                index=1,
                title_ar=f"تصنيف وتوجيه مهمة الإصلاح على {target}",
                tool="orchestrator",
                acceptance_ar="خطة موثقة بأدوات حتمية بالترتيب",
            ),
            MindStep(
                index=2,
                title_ar="تنفيذ الخطة على الملف الفعلي",
                tool="orchestrator",
                acceptance_ar="كل الخطوات نجحت وسلسلة الأدلة موقعة",
            ),
            MindStep(
                index=3,
                title_ar="نقد الناتج على معايير النجاح المُدرَكة",
                tool="critic",
                acceptance_ar="درجة الملف ≥ الحد والملف سليم",
            ),
        )
    if task in (TaskType.REVIEW, TaskType.ANALYZE, TaskType.VERIFY, TaskType.TRANSPILE):
        target = perception.target_path or "الملف المستهدف"
        return (
            MindStep(
                index=1,
                title_ar=f"تنفيذ مسار الفحص الحتمي على {target}",
                tool="orchestrator",
                acceptance_ar="الخطوات نجحت والتقرير مكتمل",
            ),
            MindStep(
                index=2,
                title_ar="نقد الناتج على معايير النجاح المُدرَكة",
                tool="critic",
                acceptance_ar="كل معايير النجاح مثبتة",
            ),
        )
    return ()


def build_plan(perception: Perception, core: ModelCore) -> MindPlan:
    """ابنِ الخطة: خطوات حتمية + استشارة القلب خلف البوابات — بلا استثناء.

    نص القلب يُفحص PII ثم RTL (الترتيب الثابت)؛ رفض أي بوابة يجعل الخطة
    مرفوضة كاملة بكل الأحكام موثقة، ومهمة غير مفهومة تُرفض قبل استشارة
    أي قلب — فشل هيكلي آمن لا يلمس القرص.
    """
    steps = _steps_for(perception)
    if not steps:
        return MindPlan(
            goal=perception.goal,
            kind=perception.kind,
            steps=(),
            advisory="",
            core_name=str(getattr(core, "name", "unknown")),
            deterministic=bool(getattr(core, "deterministic", False)),
            verdicts=(
                GateVerdict(
                    gate="planner",
                    passed=False,
                    details_ar=(
                        f"نوع المهمة {perception.kind.value} بلا مسار تنفيذ حتمي — "
                        "اكتب وصفًا لمشروع جديد أو حدد ملفًا قائمًا بالمهمة المطلوبة"
                    ),
                ),
            ),
        )
    # استشارة القلب: نص استشاري فقط — لا يلمس الخطوات الحتمية ولا القرص
    plan_request = (
        f"الهدف: {perception.goal}\nالنوع: {perception.kind.value}\n"
        f"الخطوات الحتمية: {len(steps)} — اقترح ملاحظات تخطيط عربية موجزة."
    )
    try:
        advisory = core.respond(plan_request, context=perception.goal)
    except Exception as exc:  # noqa: BLE001 — فشل القلب دليل لا انهيار
        advisory = ""
        verdicts = (
            GateVerdict(
                gate="core",
                passed=False,
                details_ar=f"القلب أثار خطأ عند بوابة الخطة — {type(exc).__name__}",
            ),
        )
        return MindPlan(
            goal=perception.goal,
            kind=perception.kind,
            steps=steps,
            advisory="",
            core_name=str(getattr(core, "name", "unknown")),
            deterministic=bool(getattr(core, "deterministic", False)),
            verdicts=verdicts,
        )
    if not isinstance(advisory, str):
        advisory = str(advisory)
    core_verdict = GateVerdict(
        gate="core",
        passed=bool(advisory.strip()),
        details_ar=(
            f"استشارة {core.name}: {len(advisory)} محرفًا"
            if advisory.strip()
            else "القلب أعاد نصًا فارغًا — الخطة تُرفض حتى لا تُبنى على صمت"
        ),
    )
    if not advisory.strip():
        return MindPlan(
            goal=perception.goal,
            kind=perception.kind,
            steps=steps,
            advisory="",
            core_name=str(getattr(core, "name", "unknown")),
            deterministic=bool(getattr(core, "deterministic", False)),
            verdicts=(core_verdict,),
        )
    verdicts = (core_verdict,) + check_proposal_gates(advisory)
    return MindPlan(
        goal=perception.goal,
        kind=perception.kind,
        steps=steps,
        advisory=advisory,
        core_name=str(getattr(core, "name", "unknown")),
        deterministic=bool(getattr(core, "deterministic", False)),
        verdicts=verdicts,
    )


__all__ = ["MindPlan", "MindStep", "PLAN_GATE_TITLE", "build_plan"]
