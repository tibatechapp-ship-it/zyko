"""zyko.guardian — المحرّس المستقل: قرار ALLOW/DENY/REVIEW على أي اقتراح نموذج.

المرحلة A: طبقة الحماية التي ستحكم كل اقتراح لاحق — من أي نموذج
(سحابي أو محلي عبر Ollama أو وهمي للاختبار). مستقلة بنيويًا عن بقية
المنصة، بلا اعتماديات جديدة، وتعيد استخدام أدوات zyko الحتمية الموجودة
(zyko.tools.pii_ar و zyko.tools.rtl) بدل إعادة اختراعها.

الاستخدام:
    from zyko.guardian import DefaultGuardian
    guardian = DefaultGuardian()
    decision = await guardian.check("اقتراح ما")
    decision.verdict       # "ALLOW" | "DENY" | "REVIEW"
    decision.fingerprint   # بصمة sha256 حتمية
    decision.reason_ar     # سبب مختصر بالعربية
"""

from zyko.guardian.contracts import (
    Decision,
    Gate,
    GateResult,
    Guardian,
    Verdict,
    compute_fingerprint,
)
from zyko.guardian.core import DefaultGuardian
from zyko.guardian.gates import (
    MAX_PROPOSAL_CHARS,
    PII_DENY_TYPES,
    PIIGate,
    RTLGate,
    StructuralGate,
    default_gates,
)

__all__ = [
    "Decision",
    "Gate",
    "GateResult",
    "Guardian",
    "Verdict",
    "compute_fingerprint",
    "DefaultGuardian",
    "MAX_PROPOSAL_CHARS",
    "PII_DENY_TYPES",
    "PIIGate",
    "RTLGate",
    "StructuralGate",
    "default_gates",
]
