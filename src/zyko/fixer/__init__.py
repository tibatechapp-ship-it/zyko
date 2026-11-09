"""zyko.fixer — المُصلِح الحتمي للمرحلة 3 (D41–58): توليد ← مراجعة ← **إصلاح**.

الإصلاح عربي النص، حتمي البايتات، خالٍ من النماذج والشبكة: 12 مسار إصلاح
آمنًا فوق قواعد المراجع الـ38، وكل ملاحظة — أُصلحت أم لا — تحمل
suggestion_ar عربيًا، وكل إصلاح مُتحقق منه بإعادة تحليل ast قبل القبول.
ما يميزنا عن مصلحي النماذج اللغوية:

- الحتمية: نفس المصدر ⇒ نفس البايتات (بوابة G3 تفرضها)
- الاعتدال: تشغيل المُصلِح على ناتجه ⇒ صفر تغيير (بوابة G2 تفرضها)
- عدم التلف: لا يُكتب نص لم يجتز إعادة التحليل، والقطع المتراكبة تُسقط
- العربية أولًا: لكل ملاحظة إجراء أو سبب عربي، والإصلاح المقترح دائمًا

الوحدات:
- edits.py   : قطع موقعة + تحويل إحداثيات بايت AST ⇄ حروف (فخ العربي)
- fixes.py   : سجل المسارات الـ12 + أسباب بقاء الـ15 يدوية بالعربية
- engine.py  : FixerEngine — مصدر ⇒ FixResult (مصائر الملاحظات + النص)
- report.py  : مخرجات JSON/نصية عربية حتمية البايتات (zyko.fix/1)
- gate.py    : بوابة القبول (إصلاح/عدم تلف/حتمية/متانة/أداء/تغطية)
- __main__.py: واجهة سطر الأوامر (fix/check/gate/rules)
"""

from zyko.fixer.edits import Edit, SourceText, apply_edits, parses
from zyko.fixer.engine import (
    MAX_PASSES,
    SCHEMA,
    STATUS_AR,
    STATUS_FIXED,
    STATUS_MANUAL,
    STATUS_OPEN,
    FixerEngine,
    FixOutcome,
    FixResult,
    review_of,
    summarize_fix,
)
from zyko.fixer.fixes import (
    ACTION_AR,
    AUTO_FIXABLE,
    FIX_PLANNERS,
    MANUAL_RULES,
    manual_reason_ar,
)
from zyko.fixer.gate import GateRow, Phase3GateResult, run_phase3_gate

__all__ = [
    "ACTION_AR",
    "AUTO_FIXABLE",
    "Edit",
    "FIX_PLANNERS",
    "MANUAL_RULES",
    "MAX_PASSES",
    "SCHEMA",
    "STATUS_AR",
    "STATUS_FIXED",
    "STATUS_MANUAL",
    "STATUS_OPEN",
    "FixContext",
    "FixOutcome",
    "FixResult",
    "FixerEngine",
    "GateRow",
    "Phase3GateResult",
    "SourceText",
    "apply_edits",
    "manual_reason_ar",
    "parses",
    "review_of",
    "run_phase3_gate",
    "summarize_fix",
]
