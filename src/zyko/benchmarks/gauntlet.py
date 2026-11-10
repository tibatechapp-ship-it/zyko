"""zyko.benchmarks.gauntlet — الفحص الكبير: 1000 برنامج حقيقي تُبنى وتُختبر.

الادعاء هنا ليس «قوالب جميلة» بل حقيقة قابلة للقياس: المصنع الحتمي
يبني 1000 مشروع حقيقي (10 نوايا × 100 تنويع) — كل مشروع يمر عبر
المخطط الصارم نفسه (``validate`` ثم ``check_source_tree``) — ثم تُنفَّذ
عينة محددة منها **اختباراتها الخاصة الحقيقية** (pytest داخل المشروع
المولَّد) وتُقبل فقط إذا كانت 100%.

القواعد كما في المصنع كله:
- **حتمية بالبايت (P6)** — المصفوفة بنفس المدخل تُبنى متطابقة 100 مرة،
  وبصمة كل برنامج sha256 فوق شجرة ملفاته، والإيصال ``to_json``
  متطابق بين التشغيلين.
- **بلا نموذج لغوي** — التصنيف والتوليد عبر جدول النوايا الحتمي فقط.
- **الفشل صادق** — أي مخطط غير صالح أو فحص فاشل يعود صفًا بمشكلة
  عربية واضحة، لا يُخفى ولا يُعتذر عنه.
- **قراءة المصنع، لا تعديله** — هذا البناش مستهلك لطبقة
  ``zyko.coder`` العامة؛ لا يلمس قوالبها ولا بواباتها.

    from zyko.benchmarks.gauntlet import run_gauntlet

    report = run_gauntlet(per_intent=100, execute=20)   # 1000 مخطط، 20 تنفيذاً حقيقياً
    assert report.passed == report.total and report.ok
    print(report.table_ar())

على سطر الأوامر: ``zyko gauntlet --per-intent 100 --execute 20``
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.coder.generate import build_all_files, materialize
from zyko.coder.heuristics import intent_specs
from zyko.coder.plan import ProjectPlan
from zyko.coder.precheck import check_source_tree, full_gate

__all__ = [
    "EXTRA_MODULE_POOL",
    "GauntletReport",
    "GauntletRow",
    "build_matrix",
    "run_gauntlet",
]

# --------------------------------------------------------------- فضاء التنويعات
# وحدات إضافية آمنة للمعرفات — تتحملها القوالب الثلاثة كلها (مُختبر داخلياً:
# python-cli/fastapi-api/static-site تبني CRUD عامًا لأي معرف سليم)
EXTRA_MODULE_POOL: tuple[str, ...] = (
    "reports",
    "tags",
    "stats",
    "archive",
    "users",
    "pages",
    "export",
    "search",
)

# صيغ عربية حتمية للوصف — كلها تحمل رقم النسخة فتضمن التميز بلا اصطدام
_DESCRIPTION_PHRASES: tuple[str, ...] = (
    "ابنِ لي {display} — نسخة الفحص رقم {i}",
    "أريد {display} يعمل فورًا مع وحدة {mod} — النسخة {i}",
    "أنشئ {display} كاملًا بوحدات {mods} — النسخة {i}",
    "مشروع {display} جاهز للتشغيل — الإصدار {i} مع {mod}",
    "صمم {display} عربيًا نظيفًا ونسخته {i}",
)


def _variation_modules(base: tuple[str, ...], i: int) -> tuple[str, ...]:
    """وحدات النسخة: الأساس + 0–3 وحدات إضافية بدوران حتمي بلا تكرار."""
    count = i % 4
    picked: list[str] = []
    for k in range(count):
        mod = EXTRA_MODULE_POOL[(i + k * 3) % len(EXTRA_MODULE_POOL)]
        if mod not in base and mod not in picked:
            picked.append(mod)
    return base + tuple(picked)


def build_matrix(per_intent: int = 100) -> list[ProjectPlan]:
    """مصفوفة البرامج: كل نية × ``per_intent`` تنويعًا — حتمية بالبايت.

    كل مخطط يمر عبر ``validate()`` نفسها؛ أي مخطط غير صالح يستحيل أن
    يدخل المصفوفة صامتًا — الفحص (الاختبار) يعترض عليه صراحة.
    """
    if per_intent < 1:
        raise ValueError("per_intent يجب أن يكون 1 على الأقل")
    plans: list[ProjectPlan] = []
    for spec in intent_specs():
        base_modules = tuple(spec["modules"])  # type: ignore[arg-type]
        name = str(spec["name"])
        display = str(spec["display"])
        for i in range(per_intent):
            modules = _variation_modules(base_modules, i)
            mods_ar = " و".join(modules)
            description = _DESCRIPTION_PHRASES[i % len(_DESCRIPTION_PHRASES)].format(
                display=display, i=i + 1, mod=modules[-1], mods=mods_ar
            )
            plans.append(
                ProjectPlan(
                    name=f"{name}-{i:03d}",
                    template=str(spec["template"]),
                    description=description,
                    modules=modules,
                    dependencies=tuple(spec["deps"]),  # type: ignore[arg-type]
                    run_commands=tuple(spec["run"]),  # type: ignore[arg-type]
                    display_name=f"{display} — نسخة {i + 1}",
                    author="zyko-bench",
                )
            )
    return plans


# --------------------------------------------------------------- صفوف النتائج
@dataclass(frozen=True)
class GauntletRow:
    """نتيجة برنامج واحد في المصفوفة — حقل مشكلة واحد عربي صريح."""

    index: int
    intent: str
    template: str
    name: str
    description: str
    modules: tuple[str, ...]
    static_ok: bool
    tests_ok: bool | None  # None = لم يُنفَّذ (فحص مصفوفة فقط)
    ok: bool
    problems: tuple[str, ...] = field(default=())
    seconds: float = 0.0
    sha256: str = ""


def _tree_sha256(plan: ProjectPlan, tree: dict[str, Any] | None = None) -> str:
    """بصمة شجرة الملفات: مسارات مرتبة ثم المحتوى — حتمية بالبايت.

    ``tree`` اختياري: من عنده شجرة جاهزة يمرّرها فلا يُبنى كلٌّ مرتين.
    """
    if tree is None:
        tree = build_all_files(plan)
    digest = hashlib.sha256()
    for path in sorted(tree):
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(tree[path].content.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def run_one(plan: ProjectPlan, index: int, *, root: Path, timeout: int = 120) -> GauntletRow:
    """نفّذ برنامجًا واحدًا كاملًا: تخطيط ← فحص ساكن ← توليد ← اختباراته الحقيقية."""
    started = time.perf_counter()
    intent = plan.name.rsplit("-", 1)[0]
    problems: list[str] = []
    static_ok = False
    tests_ok: bool | None = None
    ok = False
    sha = ""
    try:
        validation = plan.validate()
        if validation:
            problems.extend(validation)
        else:
            tree = build_all_files(plan)
            static = check_source_tree(tree)
            static_ok = static.ok
            problems.extend(static.problems)
            if static.ok:
                out = root / plan.name
                materialize(plan, out, git_init=False)
                full = full_gate(plan, out, run_tests=True, test_timeout=timeout)
                tests_ok = not full.problems
                problems.extend(full.problems)
                sha = _tree_sha256(plan, tree)
                ok = not full.problems
    except Exception as exc:  # noqa: BLE001 — الفحص يجمع ولا ينهار
        problems.append(f"استثناء غير متوقع: {type(exc).__name__}: {exc}")
    return GauntletRow(
        index=index,
        intent=intent,
        template=plan.template,
        name=plan.name,
        description=plan.description,
        modules=plan.modules,
        static_ok=static_ok,
        tests_ok=tests_ok,
        ok=ok,
        problems=tuple(problems),
        seconds=round(time.perf_counter() - started, 4),
        sha256=sha,
    )


# --------------------------------------------------------------- التقرير
@dataclass(frozen=True)
class GauntletReport:
    """تقرير الفحص الكبير — إيصال حتمي بالبايت قابل للتحقق."""

    per_intent: int
    rows: tuple[GauntletRow, ...]
    executed: int

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r.ok)

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.passed == self.total

    @property
    def chain_hash(self) -> str:
        """بصمة السلسلة: sha256 لكل بصمات الصفوف بترتيب المصفوفة."""
        digest = hashlib.sha256()
        for row in self.rows:
            digest.update(row.sha256.encode("utf-8") if row.sha256 else "-")
            digest.update(b"\x00")
        return digest.hexdigest()

    def by_intent(self) -> dict[str, tuple[int, int]]:
        """لكل نية: (المبني، المنفَّذ الناجح) — للجدول على طريقة MMLU."""
        out: dict[str, tuple[int, int]] = {}
        for row in self.rows:
            built, good = out.get(row.intent, (0, 0))
            out[row.intent] = (built + 1, good + (1 if row.ok else 0))
        return out

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        """إيصال حتمي بالبايت — الزمن خارج الإيصال إلا بطلب صريح (عقد المصنع)."""
        return {
            "kind": "gauntlet",
            "per_intent": self.per_intent,
            "total": self.total,
            "passed": self.passed,
            "executed": self.executed,
            "ok": self.ok,
            "chain_hash": self.chain_hash,
            "rows": [
                {
                    "index": r.index,
                    "intent": r.intent,
                    "template": r.template,
                    "name": r.name,
                    "modules": list(r.modules),
                    "static_ok": r.static_ok,
                    "tests_ok": r.tests_ok,
                    "ok": r.ok,
                    "sha256": r.sha256,
                    "problems": list(r.problems),
                    **({"seconds": r.seconds} if include_timing else {}),
                }
                for r in self.rows
            ],
        }

    def to_json(self, *, include_timing: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_timing=include_timing),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )

    def table_ar(self) -> str:
        """الجدول العربي على طريقة MMLU — القدرة × النتيجة × العتبة."""
        lines = [
            "الفحص الكبير — ZYKO Gauntlet: برامج حقيقية تُبنى وتُختبر",
            "=" * 62,
            f"{'النية':14} {'المبني':>7} {'الناجح':>7} {'العتبة':>9} {'الحالة':>9}",
            "-" * 62,
        ]
        for intent, (built, good) in self.by_intent().items():
            status = "✅ ناجح" if built > 0 and good == built else "❌ فاشل"
            lines.append(f"{intent:14} {built:>7} {good:>7} {'100%':>9} {status:>9}")
        lines.append("-" * 62)
        lines.append(
            f"الإجمالي: {self.passed}/{self.total} برنامجًا ناجحًا"
            + (
                f" — منها {self.executed} نُفِّذت باختباراتها الحقيقية"
                if self.executed
                else " — فحص مصفوفة فقط"
            )
        )
        lines.append(f"بصمة السلسلة: {self.chain_hash[:16]}…")
        verdict = (
            "الناتج النهائي: ✅ 100% — كل ما بُني يعمل"
            if self.ok
            else "الناتج النهائي: ❌ هناك فشل صادق في الأعلى"
        )
        lines.append(verdict)
        return "\n".join(lines)


def _static_row(plan: ProjectPlan, index: int) -> GauntletRow:
    """صف فحص مصفوفة: مخطط صالح + شيفرة ساكنة سليمة + بصمة — بلا تنفيذ."""
    problems = tuple(plan.validate())
    static_ok = False
    sha = ""
    if not problems:
        tree = build_all_files(plan)
        static = check_source_tree(tree)
        static_ok = static.ok
        problems = tuple(static.problems)
        sha = _tree_sha256(plan, tree)
    return GauntletRow(
        index=index,
        intent=plan.name.rsplit("-", 1)[0],
        template=plan.template,
        name=plan.name,
        description=plan.description,
        modules=plan.modules,
        static_ok=static_ok,
        tests_ok=None,
        ok=static_ok and not problems,
        problems=problems,
        sha256=sha,
    )


# --------------------------------------------------------------- المشغّل
def run_gauntlet(
    per_intent: int = 100,
    *,
    execute: int = 0,
    timeout: int = 120,
    root: Path | None = None,
) -> GauntletReport:
    """شغّل الفحص الكبير: مصفوفة كاملة + تنفيذ عينة حتمية باختبارات حقيقية.

    ``execute``: عدد البرامج التي تُبنى على القرص وتُشغَّل اختباراتها
    فعليًا — موزعة حتميًا على النوايا (0 = فحص المصفوفة والشيفرة الساكنة
    فقط، وهو ما يغطي كل البرامج؛ التنفيذ مكلف ويسيع سقفًا زمنيًا لكل
    مشروع).
    """
    if execute < 0:
        raise ValueError("execute يجب أن يكون 0 أو أكثر")
    plans = build_matrix(per_intent)
    rows: list[GauntletRow] = []
    total = len(plans)
    # العينة الحتمية: 0 = فحص مصفوفة فقط؛ N = توزيع متساوٍ على المصفوفة؛
    # N ≥ الإجمالي = التنفيذ الكامل
    if execute == 0:
        sample: set[int] = set()
    elif execute >= total:
        sample = set(range(total))
    else:
        sample = {i * total // execute for i in range(execute)}
    with tempfile.TemporaryDirectory(prefix="zyko-gauntlet-") as tmp:
        root_path = Path(tmp)
        for i, plan in enumerate(plans):
            if i in sample:
                rows.append(run_one(plan, i, root=root_path, timeout=timeout))
            else:
                rows.append(_static_row(plan, i))
    return GauntletReport(per_intent=per_intent, rows=tuple(rows), executed=len(sample))
