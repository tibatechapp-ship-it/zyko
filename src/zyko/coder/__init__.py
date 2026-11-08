"""zyko.coder — محرك التوليد الحتمي للمرحلة 1 (D8–D21).

Deterministic project generation from a validated Arabic-description
plan. Models *fill* the plan on-device; everything else here is
model-free, byte-reproducible, and pytest-gated:

- plan.py       : ProjectPlan المتحقق — رفض صريح لأي حقل ناقص أو غير آمن
- templates.py  : القوالب الثلاثة (python-cli / fastapi-api / static-site)
- generate.py   : شجرة ملفات كاملة + git init والتزام عربي أول حتمي
- precheck.py   : ast.parse + compile + بوابة RTL + pytest قبل التسليم
- receipt.py    : RECEIPT.md — الوصل القابل للتحقق دون اتصال
- heuristics.py : مسوّدة مخطط حتمية من الوصف (بديل بلا نموذج)
- gate.py       : بوابة القبول — 10 أوصاف عربية، ≥8 تمر من أول تشغيل
- crew_prompts.py: طاقم التوليد الثلاثي عربي فوق zyko.crew (D15–16)
"""

from .gate import DESCRIPTIONS, GATE_MIN_PASSED, GateResult, GateRow, run_acceptance_gate
from .generate import GenerateResult, build_all_files, materialize
from .heuristics import draft_plan
from .plan import (
    TEMPLATES,
    PlanValidationError,
    ProjectPlan,
    package_name,
    safe_slug,
)
from .precheck import (
    PrecheckReport,
    check_directory,
    check_source_tree,
    full_gate,
    run_project_tests,
)
from .receipt import receipt_md
from .templates import BUILDERS, GenFile, build_tree

__all__ = [
    "BUILDERS",
    "DESCRIPTIONS",
    "GATE_MIN_PASSED",
    "TEMPLATES",
    "GenFile",
    "GateResult",
    "GateRow",
    "PlanValidationError",
    "PrecheckReport",
    "ProjectPlan",
    "GenerateResult",
    "build_all_files",
    "build_tree",
    "check_directory",
    "check_source_tree",
    "draft_plan",
    "full_gate",
    "materialize",
    "package_name",
    "receipt_md",
    "run_acceptance_gate",
    "run_project_tests",
    "safe_slug",
]
