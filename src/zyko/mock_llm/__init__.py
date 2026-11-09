"""zyko.mock_llm — النموذج الوهمي المحكوم: حتمي، قابل للحقن بالسيناريوهات.

ثلاثة سيناريوهات محددة سلفًا:
  clean      — اقتراح نظيف يجتاز المحرس
  suspicious — اقتراح فيه رقم هاتف فيرفضه المحرس
  hostile    — اقتراح فيه PII ومحرف اتجاه خفي معًا

الاستخدام:
    from zyko.mock_llm import MockLLM
    llm = MockLLM("clean")
    proposal = await llm.propose("أضف دالة")
"""

from zyko.mock_llm.brain import MockLLM
from zyko.mock_llm.scenarios import SCENARIOS, Scenario, get_scenario

__all__ = ["MockLLM", "SCENARIOS", "Scenario", "get_scenario"]
