"""zyko.orchestrator — العقل الحتمي: يقرّر «أي أداة» و«بأي ترتيب».

المبدأ الحاكم: العقل لا ينفّذ — يقرّر. الأدوات تنفّذ، البوابات تحكم،
العقل ينسّق. هذه الطبقة طبقة قرار حتمية بحتة: لا نموذج لغوي، لا شبكة،
لا `datetime` ولا `random` ولا `os.environ` في المسار الحتمي —
نفس المدخل يعطي نفس القرار بالبايت، دائماً.

المكوّنات (كلٌّ في PR منفصل):
    classify — ما نوع المهمة؟ (REVIEW/FIX/GENERATE/TRANSPILE/VERIFY/ANALYZE/UNKNOWN)
    route    — أي أداة بأي ترتيب؟ (Plan من خطوات محسوسة)
    run      — تنفيذ الخطة عبر الأدوات الفعلية مع إيصال sha256 موحّد
    compress — هضم المستودع إلى سياق ضمن ميزانية رموز، بلا كتابة وبلا حذف صامت
    swarm    — مهام متوازية بحد أعلى، نتائج بترتيب المدخل وإيصال سرب موقّع
"""

from zyko.orchestrator.brain_route import (
    ALLOWED_TASKS,
    BRAIN_TOOLS,
    CLASSIFIABLE_TASKS,
    classify_with_brain,
    parse_brain_classification,
    parse_brain_plan,
    plan_with_brain,
    planner_prompt,
)
from zyko.orchestrator.classify import (
    Classification,
    TaskType,
    classify,
)
from zyko.orchestrator.compress import CompressedContext, FileSlice, compress
from zyko.orchestrator.context import extract_context
from zyko.orchestrator.route import Plan, Step, route
from zyko.orchestrator.run import RunResult, StepResult, run
from zyko.orchestrator.swarm import SwarmResult, TaskResult, swarm

__all__ = [
    "ALLOWED_TASKS",
    "BRAIN_TOOLS",
    "CLASSIFIABLE_TASKS",
    "Classification",
    "CompressedContext",
    "FileSlice",
    "Plan",
    "RunResult",
    "Step",
    "StepResult",
    "SwarmResult",
    "TaskResult",
    "TaskType",
    "classify",
    "classify_with_brain",
    "compress",
    "extract_context",
    "parse_brain_classification",
    "parse_brain_plan",
    "plan_with_brain",
    "planner_prompt",
    "route",
    "run",
    "swarm",
]
