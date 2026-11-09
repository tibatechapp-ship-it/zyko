"""zyko.pipeline — المرحلة 4 (D59–72): حلقة التغذية الراجعة في أمر واحد.

توليد ← مراجعة ← إصلاح: تربط المحركات الثلاثة الحتمية في خط واحد،
فتعيد مشروعًا **مُصلَحًا** لا مشروعًا خامًا — بلا نموذج وبلا شبكة،
حتمية البايتات، وكل ملاحظة في تقريرها تحمل ``suggestion_ar`` عربيًا
كما وردت من المراجع والمُصلِح. ما يميز الحلقة عن تشغيل المراحل يدويًا:

- الأمر الواحد: وصف عربي ⇒ مشروع على القرص + تقرير عربي (JSON أو نص)
- التصحيح قبل التسليم: درجات قبل/بعد لكل ملف — لا ملف يتراجع أبدًا
- الفشل المهيكل: أي مدخل عدائي ⇒ نتيجة موقعة (failed_stage + سبب عربي)
- الحتمية: نفس الوصف ⇒ نفس البايتات (بوابة G2 تفرضها) والاعتدال (G3)

الوحدات:
- engine.py  : PipelineEngine — وصف ⇒ PipelineResult (خروج 0/1/2)
- report.py  : مخرجات JSON/نصية عربية حتمية البايتات (zyko.pipeline/1)
- gate.py    : بوابة القبول (تكامل/حتمية/اعتدال/تحسن/متانة/أداء)
- __main__.py: واجهة سطر الأوامر (run/gate/stages)
"""

from zyko.pipeline.engine import (
    MAX_DESCRIPTION_LEN,
    MAX_ROUNDS,
    SCHEMA,
    STAGE_AR,
    STAGE_CODER,
    STAGE_FIXER,
    STAGE_PIPELINE,
    STAGE_REVIEWER,
    STAGES,
    VERDICT_NO_PY,
    PipelineEngine,
    PipelineResult,
)
from zyko.pipeline.gate import ANCHORS, GateRow, Phase4GateResult, run_phase4_gate
from zyko.pipeline.report import (
    pipeline_payload_summary,
    pipeline_result_to_json,
    pipeline_result_to_text,
    pipeline_summary_line,
    stages_table_text,
)

__all__ = [
    "ANCHORS",
    "GateRow",
    "MAX_DESCRIPTION_LEN",
    "MAX_ROUNDS",
    "Phase4GateResult",
    "PipelineEngine",
    "PipelineResult",
    "SCHEMA",
    "STAGES",
    "STAGE_AR",
    "STAGE_CODER",
    "STAGE_FIXER",
    "STAGE_PIPELINE",
    "STAGE_REVIEWER",
    "VERDICT_NO_PY",
    "pipeline_payload_summary",
    "pipeline_result_to_json",
    "pipeline_result_to_text",
    "pipeline_summary_line",
    "run_phase4_gate",
    "stages_table_text",
]
