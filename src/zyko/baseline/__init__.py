"""zyko.baseline — المرحلة 6: حارس الجودة عبر الزمن.

خط أساس حتمي (``.zyko/baseline.json``) يسجّل حالة القرص الفعلية لمشروعك
بأرقام المراجع نفسها (38 قاعدة AST ⇒ درجة 0–100 وملاحظات لكل ملف)، ثم
كل ``check`` لاحق يقارن الوضع الحالي به ويعلن بالأرقام: ما التراجع؟
ما التحسن؟ وما الجديد؟ — بنفس عقود المراحل: حتمية البايتات، فشل مهيكل
لا انهيار، وقراءة فقط في الفحص.

تقسيم الصلاحيات على القرص:

- ``update``: يكتب ملفًا واحدًا فقط (خط الأساس) — لا يلمس أي ملف مشروع
- ``check`` / ``show``: قراءة فقط دائمًا — لا يكتبان بايتًا واحدًا
- تقرير HTML يُكتب فقط عند طلب ``--html`` صراحةً

الوحدات:
- engine.py  : BaselineEngine — update/check ⇒ نتائج موقعة (خروج 0/1/2)
- report.py  : JSON/نص/HTML عربي RTL — حتمي البايتات (zyko.baseline/1)
- gate.py    : بوابة القبول (تكامل/حتمية/كشف تراجع/كشف تحسن/متانة/أداء)
- __main__.py: واجهة سطر الأوامر (update/check/show/gate/promise)
"""

from zyko.baseline.engine import (
    BASELINE_DIRNAME,
    BASELINE_FILENAME,
    F_GONE,
    F_IMPROVED,
    F_NEW,
    F_REGRESSED,
    F_SKIPPED,
    F_UNCHANGED,
    FILE_STATUS_AR,
    HISTORY_CAP,
    SCHEMA,
    STAGE_AR,
    STAGE_BASELINE,
    STAGE_REVIEWER,
    STAGE_SCAN,
    VERDICT_MISSING,
    VERDICT_NO_PY,
    BaselineCheckResult,
    BaselineEngine,
    BaselineUpdateResult,
    default_baseline_path,
)
from zyko.baseline.gate import ANCHORS, GateRow, Phase6GateResult, run_phase6_gate
from zyko.baseline.report import (
    baseline_check_summary_line,
    baseline_check_to_html,
    baseline_check_to_json,
    baseline_check_to_text,
    baseline_payload_summary,
    baseline_promise_text,
    baseline_update_summary_line,
    baseline_update_to_json,
    baseline_update_to_text,
)

__all__ = [
    "ANCHORS",
    "BASELINE_DIRNAME",
    "BASELINE_FILENAME",
    "BaselineCheckResult",
    "BaselineEngine",
    "BaselineUpdateResult",
    "FILE_STATUS_AR",
    "F_GONE",
    "F_IMPROVED",
    "F_NEW",
    "F_REGRESSED",
    "F_SKIPPED",
    "F_UNCHANGED",
    "GateRow",
    "HISTORY_CAP",
    "Phase6GateResult",
    "SCHEMA",
    "STAGE_AR",
    "STAGE_BASELINE",
    "STAGE_REVIEWER",
    "STAGE_SCAN",
    "VERDICT_MISSING",
    "VERDICT_NO_PY",
    "baseline_check_summary_line",
    "baseline_check_to_html",
    "baseline_check_to_json",
    "baseline_check_to_text",
    "baseline_payload_summary",
    "baseline_promise_text",
    "baseline_update_summary_line",
    "baseline_update_to_json",
    "baseline_update_to_text",
    "default_baseline_path",
    "run_phase6_gate",
]
