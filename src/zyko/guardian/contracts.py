"""عقود المحرّس المستقل — البروتوكولات وأنواع القرار والبصمة الحتمية.

المرحلة A: طبقة حماية مستقلة بنيويًا تقيّم أي اقتراح قادم من نموذج لغوي
(سحابي أو محلي) قبل تبنّيه. لا استيراد من أي وحدة أخرى داخل zyko هنا،
ولا اعتماديات جديدة — مكتبة قياسية فقط.

القرار ثلاثي:
  ALLOW  — اجتاز جميع البوابات.
  DENY   — رفضت بوابية واحدة على الأقل.
  REVIEW — عجزت بوابية عن إتمام الفحص (استثناء) → يحال إلى مراجعة بشرية.

البصمة: sha256 للاقتراح + نتائج البوابات بترتيبها الثابت — نفس المدخل
يعطي نفس البصمة دائمًا، بلا طوابع زمنية ولا عشوائية.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

Verdict = Literal["ALLOW", "DENY", "REVIEW"]


@dataclass
class GateResult:
    """نتيجة بوابة واحدة على الاقتراح."""

    gate_name: str
    passed: bool
    reason_ar: str
    details: dict = field(default_factory=dict)


@dataclass
class Decision:
    """قرار المحرّس النهائي الموثّق ببصمة sha256 حتمية."""

    verdict: Verdict
    gate_results: list[GateResult] = field(default_factory=list)
    fingerprint: str = ""
    reason_ar: str = ""


@runtime_checkable
class Gate(Protocol):
    """عقد البوابة الواحدة: اسم ثابت وفحص غير متزامن يعيد GateResult."""

    gate_name: str

    async def check(self, proposal: str) -> GateResult: ...


@runtime_checkable
class Guardian(Protocol):
    """عقد المحرّس: تقييم اقتراح وإعادة قرار حتمي موثّق.

    المعامل context محجوز لتمرير سياق الجلسة في الخطوات القادمة —
    لا يدخل البصمة حاليًا.
    """

    async def check(self, proposal: str, *, context: dict | None = None) -> Decision: ...


def compute_fingerprint(proposal: str, gate_results: list[GateResult]) -> str:
    """بصمة sha256 حتمية: الاقتراح ثم نتائج البوابات بترتيبها الثابت.

    نفس المدخل يعطي نفس البصمة دائمًا — بلا طوابع زمنية ولا عشوائية.
    """
    parts = [proposal]
    for g in gate_results:
        parts.append(f"{g.gate_name}={'1' if g.passed else '0'}:{g.reason_ar}")
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
