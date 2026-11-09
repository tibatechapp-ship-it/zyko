"""سيناريوهات النموذج الوهمي — محددة سلفًا وحتمية، لا يُختلق منها شيء وقت التشغيل.

ثلاثة سيناريوهات حرفيًا كما حدد التكليف:
  clean      — كود نظيف بلا PII ونص سليم
  suspicious — كود فيه رقم هاتف
  hostile    — كود فيه PII + محرف اتجاه خفي (Bidi override)

ملاحظة أمنية: محرف الاتجاه الخفي يُبنى في المصدر بتسلسل هروب ASCII
(`\\u202e`) ولا يُكتب محرفًا خامًا أبدًا — بوابة RTL الذاتية على src ترفض
المحارف الخام (Trojan Source).

كل قالب يحمل الرمز `{prompt}` ويُستبدل بطلب المستخدم — الإخراج حتمي
بايت ببايت لنفس (السيناريو، الطلب).
"""

from __future__ import annotations

from dataclasses import dataclass

# رقم الهاتف التجريبي المشترك بين السيناريوهين suspicious و hostile
_PHONE = "+966501234567"

# محرف RLO (U+202E) — يُكتب هروبًا لا محرفًا خامًا في المصدر
_BIDI_OVERRIDE = "\u202e"


@dataclass(frozen=True)
class Scenario:
    """سيناريو واحد: اسمه واسمه العربي ووصفه وقالب اقتراحه الحتمي."""

    name: str
    name_ar: str
    description_ar: str
    template: str

    def render(self, prompt: str) -> str:
        """يبني الاقتراح النهائي — دالة حتمية بحتة للمدخل نفسه."""
        return self.template.replace("{prompt}", prompt)


SCENARIOS: dict[str, Scenario] = {
    "clean": Scenario(
        name="clean",
        name_ar="نظيف",
        description_ar="كود نظيف بلا بيانات شخصية ونص سليم بلا محارف خفية",
        template=(
            "# مقترح: دالة ترحيب بسيطة\n"
            "```python\n"
            "def greet(name: str) -> str:\n"
            '    return "مرحباً يا " + name\n'
            "```\n"
            "الطلب: {prompt}\n"
            "اقتراح نظيف: لا هواتف ولا هويات ولا آيبان ولا محارف اتجاه خفية."
        ),
    ),
    "suspicious": Scenario(
        name="suspicious",
        name_ar="مشبوه",
        description_ar="كود فيه رقم هاتف صريح لاختبار رفض بوابة الخصوصية",
        template=(
            "# مقترح: دالة تواصل\n"
            "```python\n"
            "def contact() -> str:\n"
            f'    return "اتصل بـ {_PHONE}"\n'
            "```\n"
            "الطلب: {prompt}\n"
            "ملاحظة: هذا الاقتراح يحمل رقم هاتف صريح — يفترض أن يرفضه المحرس."
        ),
    ),
    "hostile": Scenario(
        name="hostile",
        name_ar="عدائي",
        description_ar="كود فيه بيانات شخصية ومحرف اتجاه خفي لاختبار الدفاع الطبقي",
        template=(
            "# مقترح: بيانات عميل\n"
            "```python\n"
            "def contact() -> str:\n"
            f'    return "اتصل بـ {_PHONE}"\n'
            "```\n"
            "الطلب: {prompt}\n"
            f"ملاحظة: اقتراح عدائي — هاتف ومحرف اتجاه خفي ({_BIDI_OVERRIDE})"
            " لاختبار الدفاع الطبقي للمحرس."
        ),
    ),
}


def get_scenario(name: str) -> Scenario:
    """يعيد السيناريو المطلوب أو يرفع خطأ عربيًا واضحًا."""
    try:
        return SCENARIOS[name]
    except KeyError:
        available = "، ".join(sorted(SCENARIOS))
        raise ValueError(f"سيناريو غير معروف: {name!r}. المتاح: {available}") from None
