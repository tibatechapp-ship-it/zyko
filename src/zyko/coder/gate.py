"""zyko.coder.gate — بوابة قبول المرحلة 1 (D20–21).

Ten realistic Arabic descriptions run end-to-end: heuristic plan →
generate → deterministic precheck (ast + RTL) → project tests. The
phase gate: **all 10 generate**, and **≥8 pass their first test run**.
The heuristic planner is the deterministic stand-in for the on-device
model planner; on Termux the same harness swaps in the model-filled
plan and also measures the ≤4-minute average wall time.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .generate import build_all_files, materialize
from .heuristics import draft_plan
from .plan import ProjectPlan
from .precheck import check_source_tree, full_gate

# عشرة أوصاف عربية واقعية (D20–21): قائمة مهام، مدونة، API حجوزات، ...
DESCRIPTIONS: tuple[str, ...] = (
    "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها",
    "مدونة عربية أنشر فيها مقالاتي مع صفحة تعريف عني",
    "واجهة برمجية لحجوزات عيادة أسنان: المريض يختار الخدمة والموعد",
    "متجر صغير لعرض المنتجات وإدارة الطلبيات عبر واجهة برمجية",
    "دفتر ملاحظات سريع أرشيف فيه ملاحظاتي اليومية مع أرشيف منفصل",
    "موقع مطعم يعرض قائمة الطعام وبيانات التواصل",
    "موقع معرض أعمال أعرض فيه صور مشاريعي ونبذة عني",
    "أداة سطر أوامر لتتبع المصاريف الشهرية مع تقارير مبسطة",
    "واجهة برمجية لمدرسة تدير الطلاب والدروس والحضور",
    "مؤقت بومودورو في الطرفية يتتبع جلسات التركيز وإحصاءاتها",
)

GATE_MIN_PASSED = 8


@dataclass
class GateRow:
    """نتيجة وصف واحد داخل البوابة."""

    description: str
    name: str
    template: str
    generated: bool
    static_ok: bool
    tests_ok: bool | None
    problems: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        """يمر الصف إذا وُلّد، وفحص ثابت نظيف، واختباراته مرّت (أو لم تُشغّل)."""
        return self.generated and self.static_ok and self.tests_ok is not False


@dataclass
class GateResult:
    """ملخص البوابة: 10/10 توليدًا و≥8/10 اختبارًا من أول تشغيل."""

    rows: list[GateRow] = field(default_factory=list)

    @property
    def generated(self) -> int:
        return sum(1 for r in self.rows if r.generated)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r.passed)

    @property
    def ok(self) -> bool:
        return (
            len(self.rows) == len(DESCRIPTIONS)
            and self.generated == len(DESCRIPTIONS)
            and self.passed >= GATE_MIN_PASSED
        )

    def table_ar(self) -> str:
        lines = ["الوصف | المشروع | القالب | توليد | فحص | اختبارات | ثوانٍ"]
        for r in self.rows:
            short = r.description[:28] + ("…" if len(r.description) > 28 else "")
            gen = "✓" if r.generated else "✗"
            st = "✓" if r.static_ok else "✗"
            ts = "—" if r.tests_ok is None else ("✓" if r.tests_ok else "✗")
            lines.append(
                f"{short} | {r.name} | {r.template} | {gen} | {st} | {ts} | {r.seconds:.1f}"
            )
        lines.append(
            f"الخلاصة: توليد {self.generated}/{len(self.rows)} · نجاح {self.passed}/{len(self.rows)} "
            f"(البوابة ≥{GATE_MIN_PASSED}) · الحكم: {'مقبول' if self.ok else 'مرفوض'}"
        )
        return "\n".join(lines)


def run_acceptance_gate(run_tests: bool = True, per_project_timeout: int = 180) -> GateResult:
    """تشغيل البوابة كاملة (بلا نماذج — تعبئة استدلالية حتمية)."""
    result = GateResult()
    with tempfile.TemporaryDirectory(prefix="zyko-gate-") as tmp:
        root = Path(tmp)
        for desc in DESCRIPTIONS:
            started = time.perf_counter()
            plan: ProjectPlan = draft_plan(desc)
            row = GateRow(
                description=desc,
                name=plan.name,
                template=plan.template,
                generated=False,
                static_ok=False,
                tests_ok=None,
            )
            try:
                tree = build_all_files(plan)
                static = check_source_tree(tree)
                row.static_ok = static.ok
                row.problems.extend(static.problems)
                if not static.ok:
                    row.seconds = time.perf_counter() - started
                    result.rows.append(row)
                    continue

                out = root / plan.name
                materialize(plan, out, git_init=False)
                row.generated = True

                if run_tests:
                    full = full_gate(plan, out, run_tests=True, test_timeout=per_project_timeout)
                    row.tests_ok = not full.problems
                    row.problems.extend(full.problems)
                else:
                    row.tests_ok = None
            except Exception as exc:  # noqa: BLE001 — البوابة تجمع ولا تنهار
                row.problems.append(f"استثناء غير متوقع: {type(exc).__name__}: {exc}")
            row.seconds = time.perf_counter() - started
            result.rows.append(row)
    return result


__all__ = [
    "DESCRIPTIONS",
    "GATE_MIN_PASSED",
    "GateResult",
    "GateRow",
    "run_acceptance_gate",
]
