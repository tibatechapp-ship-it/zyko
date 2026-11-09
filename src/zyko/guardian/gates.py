"""البوابات الثلاث الثابتة — الترتيب مقدّس: PII ثم RTL ثم البنيوية.

كل بوابة حتمية 100% وتعيد GateResult واحدة، وتعتمد الأدوات الموجودة
بدل إعادة اختراعها:
  PIIGate        → zyko.tools.pii_ar.scan (هاتف، هوية وطنية، آيبان)
  RTLGate        → zyko.tools.rtl.BIDI_CONTROL_RE (محارف اتجاه خفية)
  StructuralGate → فحص طول ومحارف تحكم (مكتبة قياسية فقط)

ملاحظة: بوابة RTL ترفض محارف الاتجاه الخفية التسعة (U+202A–U+202E
وU+2066–U+2069) أما علامات LRM/RLM فهي إصلاح مشروع وفق توثيق zyko_rtl
ولا تُرفض.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from zyko.guardian.contracts import GateResult
from zyko.tools.pii_ar import TYPE_LABELS, scan
from zyko.tools.rtl import BIDI_CONTROL_RE

# الأنواع التي ترفضها بوابة PII — حصرًا كما حدد التكليف:
# هواتف وهويات وطنية وآيبان (الكاشف يتحقق رياضيًا: mod97 للآيبان وقواعد
# المقدمات للهواتف — لا إيجابيات كاذبة على أي سلسلة أرقام عابرة).
PII_DENY_TYPES: tuple[str, ...] = ("phone", "national_id", "iban")

# الحد الأقصى لطول الاقتراح بالمحارف
MAX_PROPOSAL_CHARS = 100_000

# محارف التحكم المعفاة من الرفض البنيوي (سطر جديد وجدولة وعودة)
_ALLOWED_CONTROLS = frozenset("\t\n\r")


@dataclass(frozen=True)
class PIIGate:
    """ترفض الاقتراح إذا ظهرت بيانات شخصية عربية: هاتف أو هوية أو آيبان.

    التفاصيل تحمل العدّ حسب النوع فقط — لا تُسرد القيم المكتشفة نفسها
    حفاظًا على الخصوصية داخل الإيصال.
    """

    gate_name: str = "PIIGate"

    async def check(self, proposal: str) -> GateResult:
        findings = scan(proposal, types=list(PII_DENY_TYPES))
        if not findings:
            return GateResult(self.gate_name, True, "لا بيانات شخصية مكتشفة", {})
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.type] = counts.get(f.type, 0) + 1
        label_ar = "، ".join(f"{TYPE_LABELS.get(t, t)} ×{n}" for t, n in sorted(counts.items()))
        return GateResult(
            self.gate_name,
            False,
            f"اكتُشف PII: {label_ar}",
            {"counts": counts, "total": len(findings)},
        )


@dataclass(frozen=True)
class RTLGate:
    """ترفض الاقتراح إذا احتوى محارف اتجاه خفية — تلاعب بعرض النص."""

    gate_name: str = "RTLGate"

    async def check(self, proposal: str) -> GateResult:
        hidden = BIDI_CONTROL_RE.findall(proposal)
        if not hidden:
            return GateResult(self.gate_name, True, "لا محارف اتجاه خفية", {"hidden_count": 0})
        return GateResult(
            self.gate_name,
            False,
            f"محارف اتجاه خفية ({len(hidden)}) — تلاعب بعرض النص",
            {"hidden_count": len(hidden)},
        )


@dataclass(frozen=True)
class StructuralGate:
    """ترفض الاقتراح الفارغ أو المتجاوز للحد أو المحتوي على محارف تحكم."""

    gate_name: str = "StructuralGate"

    async def check(self, proposal: str) -> GateResult:
        if not proposal.strip():
            return GateResult(
                self.gate_name,
                False,
                "الاقتراح فارغ",
                {"length": 0},
            )
        if len(proposal) > MAX_PROPOSAL_CHARS:
            return GateResult(
                self.gate_name,
                False,
                f"الاقتراح يتجاوز الحد الأقصى ({MAX_PROPOSAL_CHARS} محرفًا)",
                {"length": len(proposal), "limit": MAX_PROPOSAL_CHARS},
            )
        control = sum(
            1 for ch in proposal if unicodedata.category(ch) == "Cc" and ch not in _ALLOWED_CONTROLS
        )
        if control:
            return GateResult(
                self.gate_name,
                False,
                f"محارف تحكم غير مسموحة ({control})",
                {"control_chars": control},
            )
        return GateResult(
            self.gate_name,
            True,
            "البنية سليمة",
            {"length": len(proposal)},
        )


def default_gates() -> list:
    """البوابات الثلاث بترتيبها المقدّس: PII ثم RTL ثم البنيوية."""
    return [PIIGate(), RTLGate(), StructuralGate()]
