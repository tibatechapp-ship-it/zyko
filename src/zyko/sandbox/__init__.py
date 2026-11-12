"""zyko.sandbox — طبقة تنفيذ الأدوات المعزولة (الأولوية 3 من خريطة الاستقلال).

الأولوية 3 تحوّل «الإصلاح الحتمي فقط» إلى **تنفيذ أدوات حقيقي تحت عقد
صلاحيات وسجل تدقيق**: ``patch_file`` يعدّل ملفات المشروع داخل جذور
مسموحة فقط وبكتابة ذرية، و``run_tests`` يشغّل اختبارات حقيقية بأوامر
من قائمة بيضاء وبيئة منقّاة من الأسرار ومهلة صارمة — وكل محاولة (مسموحة
أو مرفوضة) تُوقَّع في سجل تدقيق JSONL بسلسلة sha256 لا تُخترق صامتًا.

ركائز الطبقة الخمس، كلها حتمية بالبايت وبلا اعتمادية:

  1. **العقود** (``contracts``): صلاحيات معلنة لا حدس — جذور مسموحة،
     أدوات مفعّلة، أوامر مبيّحة، سقوف أحجام ومهل — والمدخل العدوي
     يُقيَّد إلى الحد الآمن لا يرمي استثناء.
  2. **التدقيق** (``audit``): سجل JSONL ملحق-فقط بسلسلة تجزئة، والزمن
     خارج السلسلة كما في إيصال العقل — أي عبث يُكشف بإعادة الحساب.
  3. **الرقعة** (``patcher``): تطابق وحيد للنص القديم ثم كتابة ذرية
     بملف مؤقت واستبدال — لا نص مبتور ولا ملف نصف مكتوب.
  4. **التشغيل** (``runner``): argv قائمة بلا صدفة، بيئة بيضاء دنيا،
     ومخرجات مسقوفة — فلا سر يعبر ولا حلقة لا نهائية.
  5. **العزل النواتي** (``jail``، الأولوية 5): على Linux ≥ 5.13 حصر
     كتابة كود الابن بـ Landlock قبل ``exec`` — بلا اعتمادية جديدة؛
     bwrap إن وُجد وعمل، ومستوى العزل يُعلن في التدقيق والإيصال
     دائماً — القوة تُكتشف لا تُدَّعى.

حد الصدقة المعلن: العقود تقيّد ما **يعبر** من البيئة إلى الابن
(أسرار، جذور، زمن)، والعزل النواتي يقيّد ما يفعله الابن *داخله*
كتابةً — لكن القراءة مفتوحة عمدًا (تشغيل اختبارات مشروع يتطلب قراءته
وكود المشغّل) والشبكة لا تُمس تحت Landlock ABI v1–v3 — فجوتان
موثقتان لا ثغرتان مخفيتان.
"""

from __future__ import annotations

from zyko.sandbox.audit import AUDIT_SCHEMA, AuditEntry, AuditLog, AuditVerifyReport
from zyko.sandbox.contracts import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_TIMEOUT_S,
    DENY_ARGV_CHARS,
    ENV_DENY_TOKENS,
    ENV_KEEP_KEYS,
    MAX_TIMEOUT_S,
    PermissionContract,
)
from zyko.sandbox.jail import (
    JAIL_LEVEL_BWRAP,
    JAIL_LEVEL_LANDLOCK,
    JAIL_LEVEL_NONE,
    jail_level,
    landlock_abi,
)
from zyko.sandbox.patcher import PatchResult, patch_file
from zyko.sandbox.runner import TestRunResult, run_tests
from zyko.sandbox.session import ToolSession

__all__ = [
    "AUDIT_SCHEMA",
    "AuditEntry",
    "AuditLog",
    "AuditVerifyReport",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_OUTPUT_CHARS",
    "DEFAULT_TIMEOUT_S",
    "DENY_ARGV_CHARS",
    "ENV_DENY_TOKENS",
    "ENV_KEEP_KEYS",
    "JAIL_LEVEL_BWRAP",
    "JAIL_LEVEL_LANDLOCK",
    "JAIL_LEVEL_NONE",
    "MAX_TIMEOUT_S",
    "PatchResult",
    "PermissionContract",
    "TestRunResult",
    "ToolSession",
    "jail_level",
    "landlock_abi",
    "patch_file",
    "run_tests",
]
