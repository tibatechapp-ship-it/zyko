"""zyko.ai — طبقة الذكاء المُجمَّعة فوق المصنع الحتمي (المرحلة 8).

المصنع (توليد ← مراجعة ← إصلاح ← حارس) آلة حتمية قابلة للتحقق؛ هذه
الطبقة تجمّع فوقه «ذكاءً» مقيّدًا بالبوابات: أي عقل — المخطط الحتمي
اليوم، ونماذج لغوية لاحقًا — لا يلمس المشروع مباشرة، بل يقترح،
واقتراحه يمرّ ببوابات المصنع (PII ثم RTL) قبل قبوله، وكل جلسة تُوثَّق
بإيصال أدلة موقّع بالبصمات — حتمي بالبايت مثل بقية المصنع.

    python -m zyko.ai run --goal "قائمة مهام" --out ./جديد
    python -m zyko.ai gate     # بوابة المرحلة 8 (12 بوابة على 3 مراسئ)
    python -m zyko.ai map      # خريطة طبقة الذكاء
"""

from zyko.ai.best_of_brain import BestOfBrain
from zyko.ai.brains import (
    Brain,
    GatedBrain,
    GateVerdict,
    PlannerBrain,
    Proposal,
    check_proposal_gates,
)
from zyko.ai.ollama_brain import DEFAULT_HOST, HOST_ENV, OllamaBrain, list_models
from zyko.ai.qwen_brain import QwenBrain
from zyko.ai.receipt import AIReceipt, StepRecord, hash_file, hash_text
from zyko.ai.session import AISession

__all__ = [
    "AIReceipt",
    "AISession",
    "BestOfBrain",
    "Brain",
    "DEFAULT_HOST",
    "GateVerdict",
    "GatedBrain",
    "HOST_ENV",
    "OllamaBrain",
    "PlannerBrain",
    "Proposal",
    "QwenBrain",
    "StepRecord",
    "check_proposal_gates",
    "hash_file",
    "hash_text",
    "list_models",
]
