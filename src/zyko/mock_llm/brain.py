"""النموذج الوهمي المحكوم — بديل حتمي للنموذج اللغوي في اختبارات الحلقة.

يستجيب لمدخلات محددة بمخرجات محددة: نفس (السيناريو، الطلب) يعطي دائمًا
نفس الاقتراح بايت ببايت — بلا شبكة ولا عشوائية ولا حالة خفية.

الفرق عن PlannerBrain وأقرانه: هذا ليس "مخططًا بخطوات ثابتة" بل نموذج
قابل للحقن بسلوك محدد لكل سيناريو (نظيف/مشبوه/عدائي) لاختبار المحرس
على مدخلات عدائية فعليًا.
"""

from __future__ import annotations

from zyko.mock_llm.scenarios import SCENARIOS, Scenario, get_scenario


class MockLLM:
    """نموذج وهمي حتمي — يستجيب لمدخلات محددة بمخرجات محددة.

    السيناريو يحدد «عيب» الاقتراح (لا شيء أو هاتف أو هاتف مع محرف اتجاه
    خفي) والطلب يُدمج في الاقتراح كما هو.
    """

    def __init__(self, scenario: str = "clean") -> None:
        get_scenario(scenario)  # تحقق مبكر بخطأ عربي واضح
        self.scenario = scenario
        self.calls = 0  # عدّاد استدعاءات علني للاختبارات والملاحظة

    async def propose(self, prompt: str, *, context: dict | None = None) -> str:
        """يعيد اقتراحًا حتميًا بحسب السيناريو — الطلب نفسه يعطي النص نفسه.

        المعامل context محجوز لمحاكاة سياق الجلسة في الخطوات القادمة —
        لا يؤثر في المخرج الحالي.
        """
        self.calls += 1
        return self._scenario().render(prompt)

    def health(self) -> bool:
        """النموذج الوهمي جاهز دائمًا — بلا شبكة ولا مفاتيح."""
        return True

    def _scenario(self) -> Scenario:
        return SCENARIOS[self.scenario]
