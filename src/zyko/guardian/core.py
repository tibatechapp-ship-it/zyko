"""المحرّس الافتراضي — يشغّل البوابات بترتيب ثابت ويجمع قرارًا موثّقًا.

قاعدتا جمع القرار:
  1) أي فشل → DENY والسبب العربي يذكر أول بوابة فاشلة بالترتيب المقدّس.
  2) أي استثناء في بوابة → REVIEW (حالة آمنة تُحال إلى مراجعة بشرية)
     ولا يُسمح بسقوط الحلقة صامتًا.
  3) غير ذلك → ALLOW.
كل البوابات تُشغَّل دائمًا حتى بعد أول فشل — تدقيق كامل في الإيصال.
"""

from __future__ import annotations

from collections.abc import Sequence

from zyko.guardian.contracts import Decision, Gate, GateResult, compute_fingerprint
from zyko.guardian.gates import default_gates


def _build_reason_ar(verdict: str, results: list[GateResult]) -> str:
    """سبب مختصر بالعربية — يذكر أول بوابة فاشلة عند الرفض."""
    if verdict == "ALLOW":
        return f"مقبول: اجتاز جميع البوابات ({len(results)})"
    if verdict == "REVIEW":
        failed = [r for r in results if not r.passed]
        if failed:
            return f"يحتاج مراجعة بشرية: {failed[0].reason_ar}"
        return "يحتاج مراجعة بشرية"
    first_fail = next(r for r in results if not r.passed)
    return f"مرفوض ({first_fail.gate_name}): {first_fail.reason_ar}"


class DefaultGuardian:
    """المحرّس الجاهز: البوابات الثلاث بترتيبها المقدّس وقرار حتمي موثّق.

    المعامل gates يسمح بحقن بوابات مخصصة في الاختبارات فقط — الافتراضي
    هو البوابات الثلاث القياسية بترتيبها الثابت.
    """

    def __init__(self, gates: Sequence[Gate] | None = None) -> None:
        self._gates: list[Gate] = list(gates) if gates is not None else default_gates()

    async def check(self, proposal: str, *, context: dict | None = None) -> Decision:
        """تقييم الاقتراح عبر كل البوابات بالترتيب ثم إصدار قرار موثّق.

        المعامل context محجوز لسياق الجلسة ولا يدخل البصمة حاليًا.
        """
        results: list[GateResult] = []
        errored = False
        for gate in self._gates:
            name = getattr(gate, "gate_name", type(gate).__name__)
            try:
                results.append(await gate.check(proposal))
            except Exception as exc:
                errored = True
                results.append(
                    GateResult(
                        gate_name=name,
                        passed=False,
                        reason_ar=(
                            f"تعذّر إتمام الفحص في البوابة ({type(exc).__name__})"
                            " — يحتاج مراجعة بشرية"
                        ),
                        details={"error_type": type(exc).__name__},
                    )
                )
        if errored:
            verdict = "REVIEW"
        elif any(not r.passed for r in results):
            verdict = "DENY"
        else:
            verdict = "ALLOW"
        return Decision(
            verdict=verdict,
            gate_results=results,
            fingerprint=compute_fingerprint(proposal, results),
            reason_ar=_build_reason_ar(verdict, results),
        )
