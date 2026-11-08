"""zyko.coder.plan — مخطط المشروع المتحقق (D10–11).

ProjectPlan is a strict, dependency-free dataclass describing what the
generator will build. A model (or a human, or the offline heuristics)
fills it from an Arabic description; validation then *rejects the whole
plan* when anything is missing or unsafe — no silent defaults.

القواعد:
- الاسم: slug لاتيني آمن ``[a-z][a-z0-9-]{1,40}`` (يُشتق منه اسم الحزمة).
- القالب: أحد ``python-cli`` / ``fastapi-api`` / ``static-site``.
- الوحدات: معرّفات بايثون آمنة صغيرة (تُبنى منها ملفات وأصناف).
- الاعتماديات: مواصفات PEP 508 مبسطة (اسم + مُحدِّد إصدار اختياري).
- أوامر التشغيل: نصوص قصيرة غير فارغة.
- الوصف: النص العربي الأصلي غير الفارغ (يُطبع في RECEIPT.md كما هو).

``from_dict`` يقبل قاموس النموذج (structured outputs) ويرفض المفاتيح
المجهولة والأرقام حيث يُنتظر نص — لتُكتشف انحرافات النموذج مبكرًا.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field, fields

TEMPLATES: tuple[str, ...] = ("python-cli", "fastapi-api", "static-site")

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")
# PEP 508 مبسط: اسم + extras اختياري + مُحدِّد إصدار اختياري مثل ">=1.2,<2"
_DEP_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9._-]*\s*(\[[A-Za-z0-9._,-]+\])?\s*"
    r"(\*\s*|[<>=!~]=?\s*[0-9][A-Za-z0-9._*!+-]*(\s*,\s*[<>=!~]=?\s*[0-9][A-Za-z0-9._*!+-]*)*)?$"
)

_PY_PROBLEM_HINT = "استخدم حروفًا لاتينية صغيرة وأرقامًا وشرطات فقط"

_MAX_MODULES = 12
_MAX_DEPS = 24
_MAX_RUN_CMDS = 8


class PlanValidationError(ValueError):
    """يرفع عند رفض المخطط — يحمل كل المشاكل دفعة واحدة بالعربية."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        bullet = "\n  - ".join(self.problems)
        super().__init__(f"رُفض المخطط ({len(self.problems)} مشكلة):\n  - {bullet}")


def _is_str(x: object) -> bool:
    return isinstance(x, str)


def safe_slug(candidate: str, fallback: str = "my-app") -> str:
    """ينظف اسمًا مقترحًا إلى slug آمن أو يعيد الافتراضي إن فرغ.

    هذا لا يُستخدم أبدًا لتجميل مخطط مرفوض — بل لمساعدة المُخطِّط
    (النموذج أو الإنسان) قبل التحقق، ولتنظيف مدخلات ``--name``.
    """
    s = (candidate or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s or not _NAME_RE.match(s):
        return fallback if _NAME_RE.match(fallback) else "my-app"
    return s


def package_name(slug: str) -> str:
    """اسم حزمة بايثون من الـ slug: ``todo-cli`` -> ``todo_cli``."""
    return slug.replace("-", "_")


@dataclass(frozen=True)
class ProjectPlan:
    """مخطط مشروع مُتحقق — نفس الكائن يغذّي المولّد وRECEIPT.md."""

    name: str
    template: str
    description: str
    modules: tuple[str, ...] = field(default=())
    dependencies: tuple[str, ...] = field(default=())
    run_commands: tuple[str, ...] = field(default=())
    display_name: str = ""
    author: str = "zyko-coder"

    # ---------- التحقق ----------

    def validate(self) -> list[str]:
        """يرجع قائمة مشاكل عربية (فارغة = المخطط صالح)."""
        p: list[str] = []

        if not _is_str(self.name) or not self.name.strip():
            p.append("الاسم ناقص — حدّد slugًا لاتينيًا مثل todo-cli")
        elif not _NAME_RE.match(self.name):
            p.append(f"الاسم «{self.name}» غير آمن — {_PY_PROBLEM_HINT} (3–41 محرفًا ويبدأ بحرف)")

        if not _is_str(self.template) or not self.template.strip():
            p.append(f"القالب ناقص — اختر أحد: {', '.join(TEMPLATES)}")
        elif self.template not in TEMPLATES:
            p.append(
                f"القالب «{self.template}» غير معروف — القوالب المتاحة: {', '.join(TEMPLATES)}"
            )

        if not _is_str(self.description) or len(self.description.strip()) < 5:
            p.append(
                "الوصف ناقص — اكتب وصفًا عربيًا للمشروع (5 أحرف على الأقل) فهو يُوثَّق في RECEIPT.md"
            )

        mods = self.modules
        if not mods:
            p.append("الوحدات ناقصة — حدّد وحدة واحدة على الأقل (مثل: tasks, reports)")
        elif len(mods) > _MAX_MODULES:
            p.append(
                f"الوحدات كثيرة ({len(mods)}) — الحد {_MAX_MODULES} لتظل الشيفرة قابلة للمراجعة"
            )
        else:
            seen: set[str] = set()
            for m in mods:
                if not _is_str(m) or not _IDENT_RE.match(m):
                    p.append(f"الوحدة «{m}» ليست معرّفًا آمنًا — حروف لاتينية صغيرة وأرقام و_ فقط")
                elif keyword.iskeyword(m):
                    p.append(f"الوحدة «{m}» كلمة محجوزة في بايثون — اختر اسمًا آخر")
                elif m in seen:
                    p.append(f"الوحدة «{m}» مكررة")
                seen.add(m if _is_str(m) else "")

        deps = self.dependencies
        if len(deps) > _MAX_DEPS:
            p.append(f"الاعتماديات كثيرة ({len(deps)}) — الحد {_MAX_DEPS}")
        for d in deps:
            if not _is_str(d) or not _DEP_RE.match(d.strip()):
                p.append(
                    f"الاعتمادية «{d}» بصيغة غير مفهومة — استخدم اسم حزمة مع مُحدِّد اختياري مثل fastapi>=0.110"
                )

        rcs = self.run_commands
        if len(rcs) > _MAX_RUN_CMDS:
            p.append(f"أوامر التشغيل كثيرة ({len(rcs)}) — الحد {_MAX_RUN_CMDS}")
        for c in rcs:
            if not _is_str(c) or not c.strip() or len(c) > 160:
                p.append("أمر تشغيل فارغ أو أطول من 160 محرفًا")

        if self.display_name and not _is_str(self.display_name):
            p.append("display_name يجب أن يكون نصًا")
        if not _is_str(self.author) or not self.author.strip():
            p.append("author فارغ — اكتب اسمًا للمُنشئ (يظهر في pyproject وRECEIPT)")

        return p

    # ---------- البناء من قاموس النموذج ----------

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectPlan":
        """يبني المخطط من قاموس (مخرجات النموذج) ويرفض بصرامة.

        - المفاتيح المجهولة تُرفض (تكشف انحراف النموذج).
        - القوائم المطلوبة تقبل tuple/list فقط.
        - كل مشاكل التحقق تُرجع دفعة واحدة عبر PlanValidationError.
        """
        if not isinstance(data, dict):
            raise PlanValidationError(["المخطط ليس كائن JSON — أرسل قاموسًا بالحقول المطلوبة"])

        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        problems: list[str] = [
            f"مفتاح مجهول «{k}» — الحقول المقبولة: {', '.join(sorted(known))}" for k in unknown
        ]

        def _tup(key: str) -> tuple[str, ...]:
            v = data.get(key)
            if v is None:
                return ()
            if isinstance(v, (tuple, list)) and all(_is_str(x) for x in v):
                return tuple(str(x).strip() for x in v)
            problems.append(f"الحقل «{key}» يجب أن يكون قائمة نصوص")
            return ()

        plan = cls(
            name=data.get("name") if _is_str(data.get("name")) else "",
            template=data.get("template") if _is_str(data.get("template")) else "",
            description=data.get("description") if _is_str(data.get("description")) else "",
            modules=_tup("modules"),
            dependencies=_tup("dependencies"),
            run_commands=_tup("run_commands"),
            display_name=data.get("display_name") if _is_str(data.get("display_name")) else "",
            author=data.get("author") if _is_str(data.get("author")) else "zyko-coder",
        )
        problems.extend(plan.validate())
        if problems:
            raise PlanValidationError(problems)
        return plan

    # ---------- المخرجات ----------

    def to_dict(self) -> dict:
        """قاموس قابل للتفريخ إلى JSON (للعرض وRECEIPT والاختبارات)."""
        return {
            "name": self.name,
            "template": self.template,
            "description": self.description,
            "modules": list(self.modules),
            "dependencies": list(self.dependencies),
            "run_commands": list(self.run_commands),
            "display_name": self.display_name,
            "author": self.author,
        }

    @property
    def pkg(self) -> str:
        return package_name(self.name)

    def summary_ar(self) -> str:
        """سطر عرض قصير بالعربية لواجهة الموافقة (zyko new --plan)."""
        disp = self.display_name or self.name
        mods = "، ".join(self.modules)
        deps = "، ".join(self.dependencies) if self.dependencies else "لا شيء"
        return (
            f"المشروع: {disp} ({self.name})\n"
            f"القالب: {self.template}\n"
            f"الوحدات: {mods}\n"
            f"الاعتماديات: {deps}\n"
            f"الوصف: {self.description.strip()[:120]}"
        )
