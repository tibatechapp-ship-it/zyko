"""zyko.guarded — الحلقة الموثّقة الكاملة للمرحلة A.

    طلب → محرس → نموذج وهمي → محرس → إيصال sha256

الاستخدام:
    from zyko.guardian import DefaultGuardian
    from zyko.mock_llm import MockLLM
    from zyko.guarded import GuardedLoop

    loop = GuardedLoop(DefaultGuardian(), MockLLM("clean"))
    result = await loop.run("أنشئ دالة")
    result.applied        # True إذا اجتاز الاقتراح المحرس
    result.receipt["chain_hash"]  # بصمة حتمية للحلقة كاملة
"""

from zyko.guarded.loop import RECEIPT_SCHEMA, GuardedLoop, GuardedResult

__all__ = ["GuardedLoop", "GuardedResult", "RECEIPT_SCHEMA"]
