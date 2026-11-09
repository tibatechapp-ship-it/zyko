"""zyko.workspace — المرحلة 5 (D73–90): المحرك على أرض الواقع.

مراجعة ← إصلاح **لمجلد بايثون قائم** — لا على شيفرة وَلَدَها المولّد
فحسب، بل على أي مشروع على قرصك. نفس عقود المراحل الأربع: حتمية
البايتات، فشل مهيكل لا انهيار، وكل ملاحظة تحمل ``suggestion_ar``
كما وردت من المراجع والمُصلِح. الحذر مع قرص المستخدم أولوية:

- الافتراضي **تجربة جافة**: لا يُكتب بايت واحد
- ``copy``: نسخة مُصلَحة إلى مجلد جديد فارغ (يُرفض المجلد غير الفارغ)
- ``inplace``: تعديل موضعي يتطلب تأكيدًا صريحًا (``--yes``)
- لا يُكتب ملف إلا إذا نجت صياغته النهائية من ``ast``

الوحدات:
- engine.py  : WorkspaceEngine — مجلد ⇒ WorkspaceResult (خروج 0/1/2)
- report.py  : مخرجات JSON/نصية عربية حتمية البايتات (zyko.workspace/1)
- gate.py    : بوابة القبول (تكامل/حتمية/اعتدال/تحسن/متانة/أداء)
- __main__.py: واجهة سطر الأوامر (run/gate/promise)
"""

from zyko.workspace.engine import (
    FILE_STATUS_AR,
    FILE_STATUS_CLEAN,
    FILE_STATUS_FIXED,
    FILE_STATUS_SKIPPED,
    MAX_FILES,
    MAX_ROUNDS,
    SCHEMA,
    STAGE_AR,
    STAGE_FIXER,
    STAGE_REVIEWER,
    STAGE_SCAN,
    STAGE_WORKSPACE,
    STAGE_WRITE,
    STAGES,
    VERDICT_ALL_SKIPPED,
    VERDICT_NO_PY,
    WRITE_COPY,
    WRITE_INPLACE,
    WRITE_NONE,
    WorkspaceEngine,
    WorkspaceResult,
)
from zyko.workspace.gate import ANCHORS, GateRow, Phase5GateResult, run_phase5_gate
from zyko.workspace.report import (
    workspace_payload_summary,
    workspace_promise_text,
    workspace_result_to_json,
    workspace_result_to_text,
    workspace_summary_line,
)

__all__ = [
    "ANCHORS",
    "FILE_STATUS_AR",
    "FILE_STATUS_CLEAN",
    "FILE_STATUS_FIXED",
    "FILE_STATUS_SKIPPED",
    "GateRow",
    "MAX_FILES",
    "MAX_ROUNDS",
    "MAX_SOURCE_BYTES",
    "Phase5GateResult",
    "SCHEMA",
    "STAGES",
    "STAGE_AR",
    "STAGE_FIXER",
    "STAGE_REVIEWER",
    "STAGE_SCAN",
    "STAGE_WORKSPACE",
    "STAGE_WRITE",
    "VERDICT_ALL_SKIPPED",
    "VERDICT_NO_PY",
    "WRITE_COPY",
    "WRITE_INPLACE",
    "WRITE_NONE",
    "WorkspaceEngine",
    "WorkspaceResult",
    "run_phase5_gate",
    "workspace_payload_summary",
    "workspace_promise_text",
    "workspace_result_to_json",
    "workspace_result_to_text",
    "workspace_summary_line",
]
