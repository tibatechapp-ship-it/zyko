"""hybrid — نظام المراجعة الهجين (الموجة 27): الثابت أولاً والتفكير موجه.

المعمارية المعلنة (خمس بنيات، اختبارات لكل مرحلة قبل التالية):

1. **باني السياق** (`context.py`): لا نرسل الكود كاملاً لأي محرك تفكير؛
   نستخرج من مخرجات المراجع الحتمي (AST + Taint) الأسطر المشبوهة فقط
   ونحيطها بمقتطف مضبوط ونحوّلها إلى سياق منظم يجيب: ما المتغير؟ من
   أين أتى؟ إلى أين يذهب؟
2. **واجهة التفكير** (`reasoning.py`): عقد مجرد لأي محرك خارجي —
   يجيب أسئلة محددة فقط (هل التدفق ثغرة؟ ما أقل إصلاح؟) — الجسر يُبنى
   لا يُنسخ، والمحرك محقون لا معتمد.
3. **التحقق الذاتي** (`verify.py`): لا ثقة أبداً بإصلاح محرك تفكير —
   البوابة الثابتة تعيد تشغيل القواعد على المصدر المصلح وتقبل ما لم
   يكسر شيئاً وعالج ما قصد.
4. **التوجيه الذكي** (`reasoning.py`): الملف النظيف (100 بلا ملاحظات)
   لا يلمس محرك التفكير أبداً، والفئات الميكانيكية (quality) تبقى
   ثابتة خالصة — الموارد تُنفق على الأمني والمنطقي فقط.
5. **التلوث بين الإجرائيات** (`taintx.py`): رسم دوال داخل الملف وانتشار
   تلويث المعاملات والعوائد بينها حتى الثبات.

كل طبقة: حتمية بالبايت، بلا شبكة في القاعدة، رفض معلن لا تخمين،
وإيصال موقّع sha16 على تقرير المراجعة الهجينة.
"""

from zyko.reviewer.hybrid.context import StructuredContext, build_contexts
from zyko.reviewer.hybrid.reasoning import (
    QUESTIONS,
    HybridReport,
    HybridReviewer,
    ReasoningAnswer,
    ReasoningEngine,
    RemoteReasoningEngine,
    StaticReasoningEngine,
    route_file,
    select_findings,
)
from zyko.reviewer.hybrid.verify import FixVerdict, FixVerifier

__all__ = [
    "FixVerdict",
    "FixVerifier",
    "HybridReport",
    "HybridReviewer",
    "QUESTIONS",
    "ReasoningAnswer",
    "ReasoningEngine",
    "RemoteReasoningEngine",
    "StaticReasoningEngine",
    "StructuredContext",
    "build_contexts",
    "route_file",
    "select_findings",
]
