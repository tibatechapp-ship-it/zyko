"""zyko.orchestrator — العقل الحتمي: يقرّر «أي أداة» و«بأي ترتيب».

المبدأ الحاكم: العقل لا ينفّذ — يقرّر. الأدوات تنفّذ، البوابات تحكم،
العقل ينسّق. هذه الطبقة طبقة قرار حتمية بحتة: لا نموذج لغوي، لا شبكة،
لا `datetime` ولا `random` ولا `os.environ` في المسار الحتمي —
نفس المدخل يعطي نفس القرار بالبايت، دائماً.

المكوّنات (كلٌّ في PR منفصل):
    classify — ما نوع المهمة؟ (REVIEW/FIX/GENERATE/TRANSPILE/VERIFY/ANALYZE/UNKNOWN)
    route    — أي أداة بأي ترتيب؟ (Plan من خطوات محسوسة)
    run      — تنفيذ الخطة عبر الأدوات الفعلية مع إيصال sha256 موحّد
"""

from zyko.orchestrator.classify import (
    Classification,
    TaskType,
    classify,
)

__all__ = [
    "Classification",
    "TaskType",
    "classify",
]
