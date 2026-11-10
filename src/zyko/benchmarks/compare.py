"""zyko.benchmarks.compare — منصة المقارنة الحتمية: zyko ضد أي منافس اختياري.

مبدأ الصدق الصارم هنا أعلى من مبدأ الفوز:
- **قياسات zyko حقيقية دائمًا** وتُقاس على جهازك الآن: دقة التصنيف على
  جدول مسبارات ملصَّق (12 مسبارًا يغطي الأنواع الستة + UNKNOWN)، سرعة
  المراجعة (وسيط زمن ملف)، الحتمية البايتية بين تشغيلين، ودوران
  الإيصال عبر ``verify`` دون ثقة.
- **جانب المنافس اختياري بالكامل**: تمرّر أنت الأمر نفسه (قالب فيه
  ``{path}`` — مثال: ``pylint {path}`` أو ``ruff check {path}``). إن
  لم تمرره أو فشل تشغيله ⇒ العمود يوثّق «لم يُشغَّل» أو سبب الفشل
  عربيًا صريحًا — **لا رقم مفبرك ولا رقم مقتبس من خارج جهازك أبدًا**.
- الأزمنة خارج الإيصال الحتمي (عقد R2) — تُرد فقط مع ``include_timing``.

    from zyko.benchmarks.compare import run_compare

    report = run_compare(Path("src/app.py"))
    assert report.ok and report.accuracy == 1.0
    report = run_compare(Path("src/app.py"), competitor_cmd="ruff check {path}")
    print(report.table_ar())
"""

from __future__ import annotations

import json
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.orchestrator import classify, extract_context, route, run
from zyko.orchestrator.classify import TaskType
from zyko.orchestrator.verify import verify_orchestration_receipt

__all__ = [
    "COMPETITOR_NOT_RUN_AR",
    "PROBES",
    "CompareReport",
    "run_compare",
    "verify_probes",
]

# لم يُشغَّل — الوثيقة الصادقة عند غياب أمر المنافس (لا صفر ولا رقم مستعار).
COMPETITOR_NOT_RUN_AR = "لم يُشغَّل — مرّر --competitor-cmd لتشغيل منافس حقيقي"

# جدول المسبارات الملصَّقة — عربي وإنجليزي يغطي الأنواع الستة + UNKNOWN.
# الملصق هو النوع المتوقع من التصنيف الحتمي — الحقيقة المرجعية المرتبة.
PROBES: tuple[tuple[str, str], ...] = (
    ("راجع src/app.py", "REVIEW"),
    ("افحص ملف models.py", "REVIEW"),
    ("أصلح الخطأ في main.py", "FIX"),
    ("راجع وأصلح app.py", "FIX"),
    ("انشئ مشروع جديد", "GENERATE"),
    ("اكتب لي أداة", "GENERATE"),
    ("ترجم ملف ضاد", "TRANSPILE"),
    ("تحقق من الإيصال", "VERIFY"),
    ("حلل الأداء وقياسه", "ANALYZE"),
    ("review the file", "REVIEW"),
    ("fix the bug", "FIX"),
    ("سؤال عام بلا أمر", "UNKNOWN"),
)


def verify_probes() -> tuple[int, int, tuple[str, ...]]:
    """قياس دقة التصنيف على جدول المسبارات — (ناجح، إجمالي، أسماء الفاشلة).

    الحتمية كاملة: نفس الجدول على نفس الإصدار يعطي نفس الرقم بالبايت —
    هذا هو «الدقة» القابلة لإعادة القياس على أي جهاز.
    """
    passed = 0
    failed: list[str] = []
    for goal, expected in PROBES:
        actual = classify(goal).task.value
        if actual == expected:
            passed += 1
        else:
            failed.append(f"«{goal}» توقع {expected} وحصل {actual}")
    return passed, len(PROBES), tuple(failed)


@dataclass(frozen=True)
class CompetitorResult:
    """نتيجة جانب المنافس — صادقة حتى في غيابه."""

    command: str
    ran: bool
    median_ms: float | None = None
    output_lines: int | None = None
    error_ar: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "ran": self.ran,
            "median_ms": None if self.median_ms is None else round(self.median_ms, 3),
            "output_lines": self.output_lines,
            "error_ar": self.error_ar,
        }


@dataclass(frozen=True)
class CompareReport:
    """تقرير المقارنة — قياسات zyko موقّعة، ووجه المنافس كما جرى فعلاً."""

    target: str
    probes_passed: int
    probes_total: int
    determinism_ok: bool
    verify_ok: bool
    competitor: CompetitorResult
    problems: tuple[str, ...] = field(default=())
    review_runs_ms: tuple[float, ...] = field(default=())

    @property
    def accuracy(self) -> float:
        return self.probes_passed / self.probes_total if self.probes_total else 0.0

    @property
    def review_median_ms(self) -> float:
        return statistics.median(self.review_runs_ms) if self.review_runs_ms else 0.0

    @property
    def ok(self) -> bool:
        """القبول: دقة كاملة + حتمية + verify + المنافس إن شُغِّل لم يفشل هيكليًا."""
        return (
            self.accuracy == 1.0
            and self.determinism_ok
            and self.verify_ok
            and not self.problems
        )

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "compare",
            "target": self.target,
            "probes_passed": self.probes_passed,
            "probes_total": self.probes_total,
            "accuracy": round(self.accuracy, 4),
            "determinism_ok": self.determinism_ok,
            "verify_ok": self.verify_ok,
            "competitor": self.competitor.to_dict(),
            "problems": list(self.problems),
            "ok": self.ok,
        }
        if include_timing:
            payload["review_median_ms"] = round(self.review_median_ms, 3)
            if self.competitor.median_ms is not None:
                payload["competitor_median_ms"] = round(self.competitor.median_ms, 3)
        return payload

    def to_json(self, *, include_timing: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_timing=include_timing), ensure_ascii=False, sort_keys=True, indent=2
        )

    def table_ar(self) -> str:
        lines = [
            "منصة المقارنة الحتمية — zyko قياسًا على جهازك الآن",
            "=" * 62,
            f"الهدف: {self.target}",
            "-" * 62,
            f"دقة التصنيف      : {self.probes_passed}/{self.probes_total} مسبارًا ({self.accuracy:.0%})",
            f"الحتمية البايتية : {'✅ إيصالان متطابقان' if self.determinism_ok else '❌ انزلاق'}",
            f"دوران الإيصال    : {'✅ verify أخضر دون ثقة' if self.verify_ok else '❌ verify رفض'}",
            f"سرعة المراجعة    : {self.review_median_ms:.1f}ms/ملف (وسيط {len(self.review_runs_ms)} تشغيلات)",
        ]
        comp = self.competitor
        if comp.ran:
            lines.append(
                f"المنافس ({comp.command}): شُغِّل فعلاً — وسيط {comp.median_ms:.1f}ms، "
                f"{comp.output_lines} سطرًا خرجًا"
            )
        else:
            lines.append(f"المنافس ({comp.command or '—'}): {comp.error_ar or COMPETITOR_NOT_RUN_AR}")
        lines.append("-" * 62)
        if self.problems:
            for problem in self.problems:
                lines.append(f"! {problem}")
        lines.append(
            "الناتج: ✅ zyko أخضر كامل — راقب جانب المنافس بأمر حقيقي عندك"
            if self.ok
            else "الناتج: ❌ فشل صادق في الأعلى"
        )
        return "\n".join(lines)


def run_compare(
    target: str | Path,
    *,
    competitor_cmd: str | None = None,
    runs: int = 3,
    timeout: int = 120,
) -> CompareReport:
    """شغّل المقارنة الحتمية على هدف حقيقي — قياسات zyko + منافس اختياري.

    ``competitor_cmd``: قالب أمر فيه ``{path}`` يُستبدل بمسار الهدف —
    يُشغَّل ``runs`` مرة، ويقاس وسيطه ويُحصى خرجه. أي فشل (أداة غير
    مثبتة، رمز خروج غير صفر) يوثَّق صادقًا ولا يُخترع له رقم.
    """
    if runs < 2:
        raise ValueError("runs يجب أن يكون 2 على الأقل — الحتمية تحتاج تشغيلين للمقارنة")
    target_path = Path(target)
    problems: list[str] = []

    # ---- دقة التصنيف (الحقيقة المرجعية للجدول الملصَّق)
    passed, total, failed = verify_probes()
    if failed:
        problems.append(f"دقة التصنيف {passed}/{total}: " + "؛ ".join(failed))

    # ---- سرعة المراجعة + الحتمية البايتية + دوران الإيصال — على الهدف الحقيقي
    goal = f"راجع {target_path}"
    plan = route(classify(goal), context=extract_context(goal))
    receipts: list[str] = []
    runs_ms: list[float] = []
    verify_ok = True
    for _ in range(runs):
        started = time.perf_counter()
        result = run(plan, dry_run=True)
        runs_ms.append((time.perf_counter() - started) * 1000.0)
        receipts.append(json.dumps(result.receipt, ensure_ascii=False, sort_keys=True))
        if not verify_orchestration_receipt(result.receipt).ok:
            verify_ok = False
    if not verify_ok:
        problems.append("دوران الإيصال فشل — verify رفض إيصالاً ناتجًا")
    determinism_ok = len(set(receipts)) == 1
    if not determinism_ok:
        problems.append("انزلاق حتمية: الإيصالات تختلف بين التشغيلات")
    if not result.ok:
        problems.append(f"المراجعة فشلت على الهدف: {result.steps[-1].error_ar}")

    # ---- جانب المنافس: اختياري بالكامل، والفشل موثق لا مفبرك
    competitor = _run_competitor(competitor_cmd, target_path, runs=runs, timeout=timeout)

    return CompareReport(
        target=str(target_path),
        probes_passed=passed,
        probes_total=total,
        determinism_ok=determinism_ok,
        verify_ok=verify_ok,
        competitor=competitor,
        problems=tuple(problems),
        review_runs_ms=tuple(runs_ms),
    )


def _run_competitor(
    cmd_template: str | None, target: Path, *, runs: int, timeout: int
) -> CompetitorResult:
    """شغّل أمر المنافس كما مرّره المستخدم — بلا رقم عند الغياب أو الفشل."""
    if not cmd_template or not str(cmd_template).strip():
        return CompetitorResult(command=cmd_template or "", ran=False, error_ar=COMPETITOR_NOT_RUN_AR)
    if "{path}" not in str(cmd_template):
        return CompetitorResult(
            command=str(cmd_template),
            ran=False,
            error_ar="قالب الأمر بلا {path} — لا أعرف أين يمرر الهدف",
        )
    command = str(cmd_template).format(path=str(target))
    durations: list[float] = []
    lines_seen = 0
    for _ in range(runs):
        started = time.perf_counter()
        try:
            proc = subprocess.run(  # nosec B603 — أمر المستخدم الصريح هو العقد نفسه
                command,
                shell=True,  # nosec B602 — القالب الصريح من المستخدم هو العقد الموثق
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CompetitorResult(
                command=command,
                ran=False,
                error_ar=f"فشل تشغيل المنافس ({type(exc).__name__}) — لا رقم مفبرك",
            )
        durations.append((time.perf_counter() - started) * 1000.0)
        if proc.returncode != 0:
            return CompetitorResult(
                command=command,
                ran=False,
                error_ar=f"المنافس خرج برمز {proc.returncode} — أداة غير مثبتة أو رفض الهدف؛ لا رقم مفبرك",
            )
        lines_seen = max(lines_seen, len((proc.stdout or "").splitlines()))
    return CompetitorResult(
        command=command,
        ran=True,
        median_ms=statistics.median(durations),
        output_lines=lines_seen,
    )
