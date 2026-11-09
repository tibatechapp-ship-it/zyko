"""zyko.reviewer — المراجع الحتمي للمرحلة 2 (D22–40): توليد ثم مراجعة.

المراجعة عربية النص، حتمية البايتات، خالية من النماذج والشبكة: 27 قاعدة
AST في ثلاث فئات (معالجة الأخطاء، الأمن، الجودة)، درجة 0–100 وحكم عربي،
وبوابة قبول كمية أولًا بأول. ما يميزها عن مراجعي النماذج اللغوية:

- الحتمية: نفس المصدر ⇒ نفس البايتات (بوابة G3 تفرضها)
- عدم الهلوسة: كل ملاحظة موقعة بمعرف قاعدة وسطر وعمود قابل للتحقق
- العمل دون اتصال: صفر نداءات شبكة، صفر مفاتيح API، يصلح للهاتف
- العربية أولًا: رسائل وإصلاحات مقترحة عربية أصلية لا ترجمة آلية

الوحدات:
- rules.py   : سجل القواعد الـ 27 + Finding + RuleConfig
- engine.py  : ReviewEngine — مصدر ⇒ نتيجة موقعة (درجة + حكم)
- report.py  : مخرجات JSON/نصية عربية حتمية البايتات
- gate.py    : بوابة القبول (استرجاع/دقة/حتمية/متانة/أداء/تغطية)
- __main__.py: واجهة سطر الأوامر (review/gate/rules)
"""

from zyko.reviewer.engine import (
    ReviewEngine,
    ReviewResult,
    summarize,
    verdict_for_score,
)
from zyko.reviewer.gate import GateRow, Phase2GateResult, run_phase2_gate
from zyko.reviewer.rules import (
    CATEGORIES,
    CATEGORY_AR,
    RULES,
    RULES_BY_ID,
    SEVERITIES,
    SEVERITY_AR,
    SEVERITY_WEIGHT,
    Finding,
    Rule,
    RuleConfig,
)

__all__ = [
    "CATEGORIES",
    "CATEGORY_AR",
    "RULES",
    "RULES_BY_ID",
    "Finding",
    "GateRow",
    "Phase2GateResult",
    "ReviewEngine",
    "ReviewResult",
    "Rule",
    "RuleConfig",
    "SEVERITIES",
    "SEVERITY_AR",
    "SEVERITY_WEIGHT",
    "run_phase2_gate",
    "summarize",
    "verdict_for_score",
]
