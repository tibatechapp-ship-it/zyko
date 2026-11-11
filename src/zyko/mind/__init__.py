"""zyko.mind — نواة العقل المستقل: الحلقة الإدراكية الكاملة (المرحلة A).

التجميع الموثق في ``docs/MIND.md`` §6.1 — الوحدات الست فوق حد العملية
الموحد، وكل انتقال بينها بوابة موثقة في إيصال حتمي:

    from zyko.mind import MindLoop, DeterministicCore, ScriptedCore
    receipt = MindLoop().run("قائمة مهام مع واجهة سطر أوامر", "./جديد")
    print(receipt.ok, receipt.chain_hash[:16])

العقد الحاكم نفسه في كل مكان: **العقل يضيف، والبوابات تُقرِّر، والإيصال
يروي القصة كاملة** — حتمي بالبايت، بلا شبكة في المسار الحتمي الافتراضي،
وبلا استثناء يخرج من الحلقة أبدًا.
"""

from zyko.mind.autodetect import CandidateRecord, CoreDecision, select_core
from zyko.mind.core import BrainCore, DeterministicCore, ModelCore, ScriptedCore
from zyko.mind.critic import CriticFinding, CriticReport, critique
from zyko.mind.loop import MindLoop, MindReceipt, MindStepRecord
from zyko.mind.memory import MindMemory
from zyko.mind.perception import Perception, SuccessCriterion, perceive
from zyko.mind.planner import MindPlan, MindStep, build_plan

__all__ = [
    "BrainCore",
    "CandidateRecord",
    "CoreDecision",
    "CriticFinding",
    "CriticReport",
    "DeterministicCore",
    "MindLoop",
    "MindMemory",
    "MindPlan",
    "MindReceipt",
    "MindStep",
    "MindStepRecord",
    "ModelCore",
    "Perception",
    "ScriptedCore",
    "SuccessCriterion",
    "build_plan",
    "critique",
    "perceive",
    "select_core",
]
