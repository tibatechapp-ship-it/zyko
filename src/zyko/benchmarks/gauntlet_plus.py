"""zyko.benchmarks.gauntlet_plus — طبقة الشدّ فوق الفحص الكبير (حتمية بالبايت).

الـ Gauntlet القائم (``run_gauntlet``) يثبت أن المصنع يبني 1000 برنامجًا
صحيحًا. هذه الطبقة تضيف ثلاثة حراس يقيسون **القوة والسرعة والدقة** —
بلا لمس المصفوفة القائمة ولا قوالب المصنع (قراءة المصنع، لا تعديله):

1. **حارس الحتمية المتكررة** — المصفوفة تُبنى ``repeats`` مرات؛ بصمة
   السلسلة يجب أن تتطابق بالبايت كل مرة. أي انزلاق عشوائي أو زمني في
   التوليد يُكشف هنا فورًا — هذا عقد P6 تحت أقصى حمل.
2. **حارس السرعة** — زمن بناء كل برنامج يُقاس، والإحصاء (الوسيط، p95،
   الأعلى) يُقارن بميزانية صريحة. الأزمنة **خارج الإيصال الحتمي**
   دائمًا (عقد المصنع R2) — تُرد فقط مع ``include_timing=True``.
3. **المراجعة الذاتية** — ما يولّده المصنع لا ينزل عن خط أساس الجودة
   المرصود (``review_min_score``، الافتراضي 45 — انظر التعليق على
   الثابت): عيّنة حتمية من البرامج تُراجع ملفاً ملفًا بمحرك المراجعة،
   وأدنى درجة موثقة، وأي انحدار عن الخط ⇒ فشل صادق. المصنع الذي لا
   يجتاز مرآته لا يدّعي الجودة.
4. **تحقق الإيصال دون ثقة** — بصمة سلسلة تقرير الشدّ تُعاد حسابها من
   صفوفها نفسها (نفس عقد ``zyko verify``) فيكون التقرير قابلًا
   للتحقق بلا اتصال وبلا ثقة في من كتبه.

    from zyko.benchmarks.gauntlet_plus import run_stress_gauntlet

    report = run_stress_gauntlet(per_intent=100, repeats=3, review_sample=100)
    assert report.ok
    print(report.table_ar())
"""

from __future__ import annotations

import hashlib
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from zyko.benchmarks.gauntlet import GauntletReport, build_matrix, run_gauntlet
from zyko.coder.generate import build_all_files
from zyko.coder.plan import ProjectPlan
from zyko.reviewer.engine import ReviewEngine

__all__ = [
    "DEFAULT_REVIEW_MIN_SCORE",
    "DEFAULT_SPEED_BUDGET_MS",
    "StressReport",
    "run_stress_gauntlet",
]

# ميزانية سرعة البناء الافتراضية: وسيط زمن بناء البرنامج الواحد (ملي ثانية).
# القوالب صغيرة؛ 200ms وسطٌ متسامح يكشف انزلاقًا بمئة ضعف لا اهتزاز الآلة.
DEFAULT_SPEED_BUDGET_MS = 200.0
# عتبة المراجعة الذاتية الافتراضية: خط الأساس النسبي لا حد مطلق —
# أدنى درجة مرصودة اليوم على مخرجات المصنع الخام هي 48 (ملفات الاختبار
# المولَّدة تُميّر بقواعد asserts وdocstrings)، فالعتبة الافتراضية 45
# تحرس هذا الخط بهامش وتكشف أي انحدار مستقبلي فورًا. رفعها خيار صريح
# في كل نداء — ورفع جودة القوالب نفسها مهمة مستقلة موثقة.
DEFAULT_REVIEW_MIN_SCORE = 45


# --------------------------------------------------------------- الإحصاء
@dataclass(frozen=True)
class BuildStats:
    """إحصاء زمن البناء لكل برنامج — خارج الإيصال إلا بطلب صريح."""

    count: int
    median_ms: float
    p95_ms: float
    max_ms: float
    budget_ms: float

    @property
    def within_budget(self) -> bool:
        return self.median_ms <= self.budget_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "median_ms": round(self.median_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "budget_ms": self.budget_ms,
            "within_budget": self.within_budget,
        }


@dataclass(frozen=True)
class ReviewSampleRow:
    """نتيجة مراجعة برنامج واحد من العينة الحتمية."""

    name: str
    files: int
    min_score: int
    findings: int
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "files": self.files,
            "min_score": self.min_score,
            "findings": self.findings,
            "ok": self.ok,
        }


# --------------------------------------------------------------- التقرير
@dataclass(frozen=True)
class StressReport:
    """تقرير طبقة الشدّ — الحتمية والسرعة والمراجعة الذاتية في إيصال واحد."""

    per_intent: int
    repeats: int
    matrix_hashes: tuple[str, ...]
    determinism_ok: bool
    build_stats: BuildStats | None
    review_rows: tuple[ReviewSampleRow, ...]
    review_min_score: int
    gauntlet: GauntletReport | None = None
    problems: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        """القبول: حتمية متكررة سليمة + سرعة ضمن الميزانية + عينة المراجعة كلها فوق العتبة."""
        if not self.determinism_ok:
            return False
        if self.build_stats is not None and not self.build_stats.within_budget:
            return False
        if any(not row.ok for row in self.review_rows):
            return False
        return True

    @property
    def review_chain_hash(self) -> str:
        """بصمة سلسلة عينة المراجعة — من صفوفها نفسها، قابلة لإعادة الحساب دون ثقة."""
        digest = hashlib.sha256()
        for row in self.review_rows:
            digest.update(f"{row.name}|{row.files}|{row.min_score}|{row.findings}".encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        """إيصال حتمي بالبايت — الأزمنة خارج الإيصال إلا بطلب صريح."""
        payload: dict[str, Any] = {
            "kind": "gauntlet_stress",
            "per_intent": self.per_intent,
            "repeats": self.repeats,
            "determinism_ok": self.determinism_ok,
            "matrix_hashes": list(self.matrix_hashes),
            "review_min_score": self.review_min_score,
            "review_rows": [row.to_dict() for row in self.review_rows],
            "review_chain_hash": self.review_chain_hash,
            "problems": list(self.problems),
            "ok": self.ok,
        }
        if self.build_stats is not None and include_timing:
            payload["build_stats"] = self.build_stats.to_dict()
        if self.gauntlet is not None:
            payload["gauntlet"] = {
                "total": self.gauntlet.total,
                "passed": self.gauntlet.passed,
                "chain_hash": self.gauntlet.chain_hash,
            }
        return payload

    def to_json(self, *, include_timing: bool = False) -> str:
        import json

        return json.dumps(
            self.to_dict(include_timing=include_timing), ensure_ascii=False, sort_keys=True, indent=2
        )

    def table_ar(self) -> str:
        """الجدول العربي: ثلاثة حراس × نتيجة × الدليل."""
        lines = [
            "طبقة الشدّ — ZYKO Gauntlet+: الحتمية × السرعة × المراجعة الذاتية",
            "=" * 62,
            f"{'الحارس':26} {'النتيجة':>9}  الدليل",
            "-" * 62,
            (
                f"{'الحتمية المتكررة':26} {'✅':>9}  {self.repeats} بناءً متطابقة بالبايت"
                if self.determinism_ok
                else f"{'الحتمية المتكررة':26} {'❌':>9}  انزلاق بين البناءات — انظر problems"
            ),
        ]
        if self.build_stats is not None:
            stats = self.build_stats
            mark = "✅" if stats.within_budget else "❌"
            lines.append(
                f"{'حارس السرعة':26} {mark:>9}  وسيط البناء {stats.median_ms:.1f}ms "
                f"(p95 {stats.p95_ms:.1f}ms) — الميزانية {stats.budget_ms:.0f}ms"
            )
        if self.review_rows:
            worst = min(row.min_score for row in self.review_rows)
            bad = sum(1 for row in self.review_rows if not row.ok)
            mark = "✅" if bad == 0 else "❌"
            lines.append(
                f"{'المراجعة الذاتية':26} {mark:>9}  {len(self.review_rows)} برنامجًا — "
                f"أدنى درجة {worst} ≥ العتبة {self.review_min_score}"
                if bad == 0
                else f"{'المراجعة الذاتية':26} {mark:>9}  {bad} برنامجًا دون العتبة {self.review_min_score}"
            )
        if self.gauntlet is not None:
            lines.append(
                f"{'البناء والتنفيذ':26} {'✅' if self.gauntlet.ok else '❌':>9}  "
                f"{self.gauntlet.passed}/{self.gauntlet.total}"
            )
        lines.append("-" * 62)
        lines.append(f"بصمة عينة المراجعة: {self.review_chain_hash[:16]}…")
        lines.append(
            "الناتج النهائي: ✅ كل الحراس خضراء" if self.ok else "الناتج النهائي: ❌ فشل صادق في الأعلى"
        )
        return "\n".join(lines)


# --------------------------------------------------------------- المشغّل
def run_stress_gauntlet(
    per_intent: int = 100,
    *,
    repeats: int = 3,
    review_sample: int = 100,
    speed_budget_ms: float = DEFAULT_SPEED_BUDGET_MS,
    review_min_score: int = DEFAULT_REVIEW_MIN_SCORE,
    execute: int = 0,
    root: Any = None,
) -> StressReport:
    """شغّل طبقة الشدّ: حتمية متكررة + إحصاء سرعة + مراجعة ذاتية حتمية.

    ``repeats``: عدد مرات بناء المصفوفة الكاملة للمطابقة البايتية.
    ``review_sample``: عدد البرامج المراجَعة ذاتيًا — عينة حتمية موزعة
    على المصفوفة (نفس منطق توزيع عينة التنفيذ في الـ Gauntlet القائم).
    ``execute``: يُمرَّر للفحص القائم إن رغبت بتضمين البناء والتنفيذ.
    """
    if repeats < 1:
        raise ValueError("repeats يجب أن يكون 1 على الأقل")
    if review_sample < 0:
        raise ValueError("review_sample يجب أن يكون 0 أو أكثر")

    problems: list[str] = []

    # ---- الحارس 1: الحتمية المتكررة (المصفوفة كاملة كل مرة)
    hashes: list[str] = []
    plans: list[ProjectPlan] | None = None
    for _ in range(repeats):
        current = build_matrix(per_intent)
        plans = current
        digest = hashlib.sha256()
        for plan in current:
            digest.update(plan.name.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(plan.description.encode("utf-8"))
            digest.update(b"\x00")
            digest.update("،".join(plan.modules).encode("utf-8"))
            digest.update(b"\x00")
        hashes.append(digest.hexdigest())
    determinism_ok = len(set(hashes)) == 1
    if not determinism_ok:
        problems.append(f"انزلاق حتمية: {len(set(hashes))} بصمات مختلفة عبر {repeats} بناءً")
    assert plans is not None  # repeats ≥ 1 يضمن ذلك

    # ---- الحارس 2: سرعة البناء (زمن قياس خارج الإيصال)
    build_ms: list[float] = []
    trees: dict[int, dict[str, Any]] = {}
    for index, plan in enumerate(plans):
        started = time.perf_counter()
        tree = build_all_files(plan)
        build_ms.append((time.perf_counter() - started) * 1000.0)
        trees[index] = tree
    stats = BuildStats(
        count=len(plans),
        median_ms=statistics.median(build_ms) if build_ms else 0.0,
        p95_ms=_p95(build_ms),
        max_ms=max(build_ms) if build_ms else 0.0,
        budget_ms=float(speed_budget_ms),
    )
    if not stats.within_budget:
        problems.append(
            f"وسيط البناء {stats.median_ms:.1f}ms يتجاوز الميزانية {stats.budget_ms:.0f}ms"
        )

    # ---- الحارس 3: المراجعة الذاتية — عينة حتمية موزعة على المصفوفة
    total = len(plans)
    if review_sample >= total:
        sample = set(range(total))
    elif review_sample > 0:
        sample = {i * total // review_sample for i in range(review_sample)}
    else:
        sample = set()
    engine = ReviewEngine()
    review_rows: list[ReviewSampleRow] = []
    for index in sorted(sample):
        plan = plans[index]
        scores: list[int] = []
        findings_count = 0
        for path, item in sorted(trees[index].items()):
            if not path.endswith(".py"):
                continue
            result = engine.review_source(item.content, f"{plan.name}/{path}")
            scores.append(result.score)
            findings_count += len(result.findings)
        min_score = min(scores) if scores else 0
        review_rows.append(
            ReviewSampleRow(
                name=plan.name,
                files=len(scores),
                min_score=min_score,
                findings=findings_count,
                ok=min_score >= review_min_score,
            )
        )
    bad_review = [row.name for row in review_rows if not row.ok]
    if bad_review:
        problems.append(
            f"{len(bad_review)} برنامجًا دون عتبة المراجعة {review_min_score}: " + "، ".join(bad_review[:5])
        )

    # ---- الفحص القائم اختياريًا (بناء وتنفيذ باختبارات حقيقية)
    gauntlet_report: GauntletReport | None = None
    if execute > 0:
        gauntlet_report = run_gauntlet(per_intent, execute=execute)

    return StressReport(
        per_intent=per_intent,
        repeats=repeats,
        matrix_hashes=tuple(hashes),
        determinism_ok=determinism_ok,
        build_stats=stats,
        review_rows=tuple(review_rows),
        review_min_score=review_min_score,
        gauntlet=gauntlet_report,
        problems=tuple(problems),
    )


def _p95(values: list[float]) -> float:
    """المئين 95 حتمي — فرز ثم موضع بسيط؛ قائمة فارغة ⇒ 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(0.95 * len(ordered)))
    return ordered[index]
