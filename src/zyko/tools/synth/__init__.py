"""zyko.tools.synth — المُقترِح الحتمي: برمجة بالبحث، بلا نموذج لغوي.

النظرة (جولة 15، 0.39.0): الحاكم الشكلي (0.38.0) يحكم العقود
سكونيًا ولا ينفّذ — والمُقترِح الحتمي هنا يكمل الثنائية: يقرأ
مهمة بعقود معلنة، يعدّد نحوًا مُغلقًا من المرشحين بترتيب ثابت
بالبايت، ينفّذ كل مرشح على نقاط المجال المعلن في مساحة أسماء
مبيّضة، ويُسلّم فائزه للحاكم للتحكيم الأخير. النتيجة: zyko يكتب
كوداً صحيحاً **بلا شبكة وبلا نموذج لغوي** — داخل صنف معلن بصدق،
وبإيصال حتمي بالبايت يفصح عن فضاء البحث وحدوده.

    from zyko.tools.synth import run

    receipt = run(SOURCE)
    assert receipt.ok
    print(receipt.winner_source)   # البرنامج المُركَّب
    print(receipt.chain_hash)      # بصمة السلسلة الحتمية

الأحكام الخمسة: synthesized / exhausted / budget / invalid_spec /
unverifiable — والصدق عقد: البرهان داخل الصنف المعلن فقط، وما
خارجه يُعلن «غير مكتمل» لا يُخفى.
"""

from __future__ import annotations

from zyko.tools.synth.engine import (
    EXIT_NOT_FOUND,
    EXIT_SPEC_BAD,
    EXIT_SYNTHESIZED,
    RECEIPT_KIND,
    SynthReceipt,
    run,
    search,
)
from zyko.tools.synth.grammar import (
    DEFAULT_BLOCK_BEAM,
    DEFAULT_BUDGET,
    DEFAULT_MAX_NODES,
    CandidateSpace,
    StructuralViolation,
    harvest_constants,
    structural_check,
)
from zyko.tools.synth.spec import (
    MAX_DOMAIN_POINTS,
    SpecVerdict,
    TaskSpec,
    parse_task,
)

__all__ = [
    "DEFAULT_BLOCK_BEAM",
    "DEFAULT_BUDGET",
    "DEFAULT_MAX_NODES",
    "EXIT_NOT_FOUND",
    "EXIT_SPEC_BAD",
    "EXIT_SYNTHESIZED",
    "MAX_DOMAIN_POINTS",
    "RECEIPT_KIND",
    "CandidateSpace",
    "SpecVerdict",
    "StructuralViolation",
    "SynthReceipt",
    "TaskSpec",
    "harvest_constants",
    "parse_task",
    "run",
    "search",
    "structural_check",
]
