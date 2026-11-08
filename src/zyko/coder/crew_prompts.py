"""zyko.coder.crew_prompts — طاقم التوليد الثلاثي (D15–16).

Three Arabic-prompted roles over the existing ``zyko.crew`` engine:

- **planner**: وصف عربي → ProjectPlan JSON — يُتحقق منه صرامةً عبر
  :meth:`zyko.coder.plan.ProjectPlan.from_dict` (structured output)؛
- **coder**: مخطط معتمد → ملفات إثراء JSON (فوق القوالب الحتمية؛
  المولّد القياسي لا ينتظر الشبكة أبدًا)؛
- **checker**: يقرأ تقرير الفحص الحتمي (D14) كمدخل طاقم مراجعة منفصل
  ويضيف رأيًا نوعيًا فوقه — الحتمي يسبق الذكي دائمًا.

على الجهاز (Termux + Ollama) يُبنى الطاقم براوتر حي. هنا تُختبر
البنية فقط: نصوص التوجيه، استخراج JSON، وتركيب الطاقم بمُوجِّه مزيف.

التوجيهات عربية عن قصد (D17–18: العربي أولًا) — تعليقات الكود داخل
المشاريع المولَّدة بالعربية اختياريًا.
"""

from __future__ import annotations

import json
import re

from .plan import TEMPLATES, ProjectPlan

PLANNER_SYSTEM = """أنت مخطِّط مشاريع برمجية عربي دقيق. دورك تحويل الوصف العربي إلى مخطط ProjectPlan بصيغة JSON فقط.

القواعد:
1. أخرج كائن JSON واحدًا فقط، بلا أي نص قبله أو بعده.
2. الحقول المطلوبة:
   - "name": اسم لاتيني صغير بشرطات مثل todo-cli (3-41 محرفًا، يبدأ بحرف)
   - "template": أحد python-cli أو fastapi-api أو static-site
   - "description": الوصف العربي الأصلي كما قدمه المستخدم
   - "modules": قائمة معرّفات لاتينية صغيرة مثل ["tasks", "reports"]
   - "dependencies": قائمة اعتماديات بصيغة PEP 508 مثل ["fastapi>=0.110"] (قد تكون [])
   - "run_commands": قائمة أوامر تشغيل قصيرة
   - "display_name": اسم عربي جميل للمشروع
3. اختر القالب: أداة سطر أوامر → python-cli، واجهة/خدمة ويب → fastapi-api،
   محتوى/عرض بلا منطق خادم → static-site.
4. الوحدات: من 1 إلى 12 وحدة، أسماؤها معرّفات بايثون آمنة.
5. لا تُخترع حقولًا خارج القائمة — أي حقل زائد يُرفض.
6. ممنوع إخراج أسئلة أو تنبيهات — إما JSON صالح أو لا شيء."""

CODER_SYSTEM = """أنت مبرمج عربي تكمل مشاريع مولَّدة بقوالب حتمية. القوالب بنَت الهيكل الكامل (ملفات، اختبارات، README) — دورك إثراء المحتوى فقط.

القواعد:
1. أخرج كائن JSON واحدًا: {"files": [{"path": "...", "content": "...", "reason": "..."}]}.
2. أضف ملفات محتوى فقط (بيانات أولية، أمثلة، صفحات HTML إضافية داخل static-site).
3. ممنوع تعديل ملفات البنية: pyproject.toml، tests/، RECEIPT.md، .gitignore،
   وملفات القالب الموجودة أصلًا — أي تعديل عليها يُرفض.
4. كل ملف بايثون تكتبه يجب أن يمر ast.parse — وإلا سيرفضه الفاحص الحتمي.
5. النصوص بالعربية، أسماء الملفات لاتينية آمنة."""

CHECKER_SYSTEM = """أنت مراجع كود عربي صارم. الفاحص الحتمي فحص الشيفرة أولًا (ast، RTL، بنية) ورفض المكسور — أنت تراجع ما تبقى فوق تقريره.

القواعد:
1. لا تكرّر ما قاله التقرير الحتمي — أضف ما لا تراه الأدوات: منطق الأعمال،
   الحالات الحدية، الأسماء المضللة، الثغرات التصميمية.
2. إن كان التقرير الحتمي يحوي مشاكل فالقرار "رفض" بلا نقاش.
3. أخرج JSON واحدًا: {"verdict": "approve" أو "reject", "notes": ["ملاحظة عربية", "..."]}.
4. الحد الأقصى 7 ملاحظات، مرتبة بالأشد أثرًا."""

PLAN_INSTRUCTIONS = (
    "أخرج JSON مطابقًا للمخطط التالي بلا أي نص إضافي:\n"
    '{"name": "...", "template": "python-cli|fastapi-api|static-site", '
    '"description": "...", "modules": ["..."], "dependencies": ["..."], '
    '"run_commands": ["..."], "display_name": "..."}'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_plan_json(text: str) -> dict:
    """يستخرج أول كائن JSON من مخرجات النموذج (يتسامح مع أسوار ```json)."""
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    match = _JSON_RE.search(cleaned)
    if match is None:
        raise ValueError("لم يُعثر على كائن JSON في مخرجات المخطِّط")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON غير صالح من المخطِّط: {exc}") from exc


def parse_plan(model_output: str) -> ProjectPlan:
    """من نص النموذج إلى مخطط متحقق — أي انحراف يُرفض برسالة عربية."""
    data = extract_plan_json(model_output)
    return ProjectPlan.from_dict(data)


def planner_task(description: str) -> str:
    """مهمة المخطِّط: الوصف + تعليمات الصيغة."""
    return f"{PLAN_INSTRUCTIONS}\n\nالوصف العربي:\n{description.strip()}"


def coder_task(plan: ProjectPlan) -> str:
    """مهمة المبرمج: المخطط المعتمد (قابل للفحص) + حدود الإضافة."""
    return "أضف ملفات محتوى فوق القالب وفق القواعد.\nالمخطط المعتمد:\n" + json.dumps(
        plan.to_dict(), ensure_ascii=False, sort_keys=True
    )


def checker_task(precheck_summary: str) -> str:
    """مهمة المراجع: ملخص التقرير الحتمي + الملفات المعنية."""
    return f"تقرير الفحص الحتمي:\n{precheck_summary}\n\nراجع فوقه وفق القواعد."


def build_plan_crew(router, tracer=None, name: str = "zyko-coder-plan"):
    """طاقم التخطيط: planner → coder (خطوتان فوق zyko.crew.Crew).

    - ``planner``: يحول وصف الطاقم ({task}) إلى JSON مخطط؛
    - ``coder``: يقرأ {plan_json} ويقترح ملفات إثراء.

    المخرجات تحت مفاتيح ثابتة: ``plan_json`` و``files_json``. على
    الجهاز: مرّر مخرَج ``plan_json`` إلى ``ProjectPlan.from_dict`` بعد
    تحققه، وثبّت ملفات ``files_json`` يدويًا بعد فحصها.
    """
    from zyko.agents import Agent
    from zyko.crew import Crew

    planner = Agent(router, name="planner", system=PLANNER_SYSTEM, max_steps=1)
    coder = Agent(router, name="coder", system=CODER_SYSTEM, max_steps=1)

    crew = Crew(router=router, tracer=tracer, name=name)
    # أقواس نموذج JSON تُهرَّب ({{ }}) حتى لا تُقرأ placeholders في قالب الطاقم
    plan_sample = PLAN_INSTRUCTIONS.replace("{", "{{").replace("}", "}}")
    crew.add(
        planner,
        f"{plan_sample}\n\nالوصف العربي:\n{{task}}",
        output_key="plan_json",
    )
    crew.add(
        coder,
        "أضف ملفات محتوى فوق القالب وفق القواعد.\nالمخطط المعتمد:\n{plan_json}",
        output_key="files_json",
    )
    return crew


def build_check_crew(router, tracer=None, name: str = "zyko-coder-check"):
    """طاقم المراجعة: خطوة checker واحدة، مدخل الطاقم = ملخص D14.

    الترتيب هجين معكوس كما في الخطة: الفحص الحتمي أولًا (بلا نموذج)،
    ثم يمرر ملخصه لهذه الخطوة لإضافة ما لا تراه الأدوات.
    """
    from zyko.agents import Agent
    from zyko.crew import Crew

    checker = Agent(router, name="checker", system=CHECKER_SYSTEM, max_steps=1)
    crew = Crew(router=router, tracer=tracer, name=name)
    crew.add(checker, "{task}", output_key="verdict_json")
    return crew


def validate_templates_conform() -> None:
    """حارس اختباري: القوالب الثلاثة هي نفسها المذكورة في توجيه المخطِّط."""
    for t in TEMPLATES:
        if t not in PLANNER_SYSTEM:
            raise AssertionError(f"قالب {t} غير مذكور في توجيه المخطِّط")


__all__ = [
    "CHECKER_SYSTEM",
    "CODER_SYSTEM",
    "PLANNER_SYSTEM",
    "PLAN_INSTRUCTIONS",
    "build_check_crew",
    "build_plan_crew",
    "checker_task",
    "coder_task",
    "extract_plan_json",
    "parse_plan",
    "planner_task",
    "validate_templates_conform",
]
