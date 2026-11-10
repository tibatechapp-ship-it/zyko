"""zyko.ai.best_of_brain — تعدد العقول: المرشحون يتنافسون، والبوابات تحكم.

القاعدة الذهبية لا تتغير: **العقل يضيف، والبوابات تقرر**. هنا تُكمَل
الخطوة التالية في التجميع: عدة عقول تُستشار على الهدف نفسه **بالترتيب**،
وكل مرشح يُغلَّف ``GatedBrain`` تلقائيًا فلا يمرّ نصّه قبل بوابة PII
ثم بوابة RTL، وأول مرشح **مقبول من بواباته** يفوز — ومن بعده تتوقف
المنافسة. الإيصال يوثّق القصة كاملة: حكم كل مرشح جُرّب، ولماذا رُفض،
ومن فاز ومرتبته.

لا حتمية زائدة: ``deterministic`` للعقل المركّب هي اتحاد حتمية
مرشحيه — نموذج واحد غير حتمي يجعل الجلسة كلها تُوثَّق غير حتمية،
بصريح العبارة وبلا تجميل.

    from zyko.ai.best_of_brain import BestOfBrain
    from zyko.ai.brains import GatedBrain, PlannerBrain
    from zyko.ai.ollama_brain import OllamaBrain
    from zyko.ai.session import AISession

    session = AISession(brain=GatedBrain(BestOfBrain(
        [OllamaBrain("qwen2.5:7b"), PlannerBrain()],
    )))
    receipt = session.run("قائمة مهام", "./جديد")
    # النموذج المحلي أولًا؛ إن تعطّل أو رفضته البوابات ⇒ المخطط الحتمي ينقذ الجلسة
"""

from __future__ import annotations

from typing import Sequence

from zyko.ai.brains import Brain, GatedBrain, GateVerdict, Proposal

# أسماء بوابات هذا العقل في الإيصال
GATE_NAME = "bestof"


class BestOfBrain:
    """عقل مركّب: مرشحون بالترتيب، كل واحد خلف البوابات، وأول مقبول يفوز.

    - ``name = "bestof:<عقل1>+<عقل2>+…"`` — يظهر في الإيصال بعد الغلاف:
      ``gated:bestof:…``.
    - ``deterministic = كل المرشحين حتميون`` — بلا تجميل.
    - لا يرفع استثناءً في ``propose`` أبدًا: فشل مرشح دليلٌ يُوثَّق
      والمنافسة تُكمل مع المرشح التالي؛ وفشل الجميع اقتراح مرفوض
      بدليل عربي يجمع ردود كل مرشح.
    - المرشحون يُغلَّفون ``GatedBrain`` تلقائيًا عند البناء — فمرّروا
      العقول الخام (``PlannerBrain()``، ``OllamaBrain(…)``) لا المغلَّفة.
    """

    def __init__(self, brains: Sequence[Brain], *, name: str | None = None) -> None:
        candidates = tuple(brains) if brains is not None else ()
        if not candidates:
            raise ValueError(
                "مطلوب عقل واحد على الأقل — مثال: BestOfBrain([OllamaBrain('m'), PlannerBrain()])"
            )
        # كل مرشح خلف بوابات المصنع — بلا استثناء ولا تجاوز
        self._candidates = tuple(GatedBrain(brain) for brain in candidates)
        inner = "+".join(getattr(brain, "name", "مجهول") for brain in candidates)
        self.name = f"{GATE_NAME}:{inner}" if name is None else str(name)
        self.deterministic = all(
            bool(getattr(brain, "deterministic", False)) for brain in candidates
        )

    # ------------------------------------------------------------ المنافسة
    def propose(self, request: str) -> Proposal:
        """استشهد المرشحين بالترتيب — أول مقبول من بواباته يفوز.

        أحكام الاقتراح الفائز كلها خضراء (قبول الاقتراح شرطه ذلك)،
        وقصة المرشحين الذين رُفضوا قبله تُطوى داخل خلاصة المنافسة
        كدليل عربي موجز — لا يُزوَّر حكم ولا يُخفى فشل. أما إذا فشل
        الجميع فأحكام مرشحين تُدرى أولًا بأول ثم خلاصة الرفض.
        """
        goal = str(request).strip() if request is not None else ""
        if not goal:
            return self._rejected(
                ("الهدف فارغ — لا شيء يُعرض على المرشحين",),
                (),
            )

        tried: list[GateVerdict] = []  # أحكام المرشحين الرافضين — دليل
        failures: list[str] = []  # قصة الرفض المختصرة للخلاصة
        for rank, candidate in enumerate(self._candidates, start=1):
            proposal = candidate.propose(goal)  # GatedBrain: لا استثناء خارج
            if proposal.accepted:
                story = (
                    f" (رُفض قبله {len(failures)}: {'؛ '.join(failures)})"
                    if failures
                    else " (من المحاولة الأولى)"
                )
                summary = GateVerdict(
                    gate=GATE_NAME,
                    passed=True,
                    details_ar=(
                        f"فاز المرشح {rank} من {len(self._candidates)} "
                        f"«{proposal.brain}»{story}"
                    ),
                )
                return Proposal(
                    text=proposal.text,
                    brain=self.name,
                    deterministic=self.deterministic,
                    verdicts=tuple(proposal.verdicts) + (summary,),
                )
            failed = next((v for v in proposal.verdicts if not v.passed), None)
            detail = failed.details_ar if failed is not None else "اقتراح مرفوض"
            tried.append(
                GateVerdict(
                    gate=f"{GATE_NAME}:{rank}:{proposal.brain}",
                    passed=False,
                    details_ar=detail,
                )
            )
            failures.append(detail)

        return self._rejected(
            (f"فشل جميع المرشحين ({len(self._candidates)}) — لا اقتراح مقبول من أي عقل",),
            tuple(tried),
        )

    # ------------------------------------------------------------ المرشحون
    @property
    def candidates(self) -> tuple[str, ...]:
        """أسماء المرشحين المُغلَّفين بالترتيب — للتوثيق والفحص."""
        return tuple(candidate.name for candidate in self._candidates)

    # ------------------------------------------------------------ داخلي
    def _rejected(self, summary_parts: tuple[str, ...], verdicts: tuple[GateVerdict, ...]) -> Proposal:
        """اقتراح مرفوض: نص فارغ، وأحكام المرشحين ثم خلاصة المنافسة."""
        summary = GateVerdict(gate=GATE_NAME, passed=False, details_ar="؛ ".join(summary_parts))
        return Proposal(
            text="",
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=verdicts + (summary,),
        )
