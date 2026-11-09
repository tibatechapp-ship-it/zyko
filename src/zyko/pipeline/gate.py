"""zyko.pipeline.gate — بوابة قبول المرحلة 4: ست بوابات كمية أولًا بأول.

- G1 التكامل   : كل مرساة تُكمل الحلقة (توليد ← مراجعة ← إصلاح) بلا فشل
- G2 الحتمية   : تشغيلان بنفس الوصف ⇒ حمولتان متطابقتان بايت-ببايت
- G3 الاعتدال  : المُصلِح على ناتج الحلقة النهائي ⇒ صفر تغيير
- G4 التحسن    : لا ملف يتراجع (score_after ≥ score_before) وإصلاحات > 0
- G5 المتانة   : مدخلات عدائية (8) ⇒ فشل مهيكل عربي، لا استثناءات
- G6 الأداء    : الحلقة الكاملة لكل مرساة أسرع من الحد المعلن
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from zyko.fixer.engine import FixerEngine
from zyko.pipeline.engine import (
    MAX_ROUNDS,
    STAGE_PIPELINE,
    STAGES,
    PipelineEngine,
    PipelineResult,
)

# مراسٍ البوابة: (الاسم، وصف عربي واقعي) — ثلاثة قوالب وأربعة نوايا.
ANCHORS: tuple[tuple[str, str], ...] = (
    (
        "todo-cli",
        "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها",
    ),
    ("blog-site", "مدونة عربية أنشر فيها مقالاتي مع صفحة تعريف عني"),
    (
        "bookings-api",
        "واجهة برمجية لحجوزات عيادة أسنان: المريض يختار الخدمة والموعد",
    ),
    (
        "expenses-cli",
        "أداة سطر أوامر لتتبع المصاريف الشهرية مع تقارير مبسطة",
    ),
)

# مدخلات G5 العدائية — كلها يجب أن تعيد فشلًا مهيكلًا عربيًا (خروج 2).
# كل مدخل: (الوسم، معاملات run) — occupied يعني مجلدًا فيه ملف قائم.
_HOSTILE: tuple[tuple[str, dict[str, object]], ...] = (
    ("وصف فارغ", {"description": ""}),
    ("مسافات فقط", {"description": "   \n\t  "}),
    ("وصف غير نصي", {"description": 42}),
    ("وصف معدوم", {"description": None}),
    ("وصف ضخم", {"description": "ا" * 5000}),
    ("جولات سالبة", {"description": "قائمة مهام", "rounds": -1}),
    ("جولات نصية", {"description": "قائمة مهام", "rounds": "كثيرة"}),
    ("جولات منطقية", {"description": "قائمة مهام", "rounds": True}),
    ("مجلد غير فارغ", {"description": "قائمة مهام", "occupied": True}),
)


@dataclass
class GateRow:
    """نتيجة مرساة واحدة داخل البوابة (أو سطر مشكلة متانة بوصف فارغ)."""

    name: str
    description: str
    completed: bool = False
    deterministic: bool = False
    idempotent: bool = False
    improved: bool = False
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.completed and self.deterministic and self.idempotent and self.improved


@dataclass
class Phase4GateResult:
    """نتيجة البوابة كاملة: صفوف المراسي + المتانة + الزمن."""

    rows: list[GateRow] = field(default_factory=list)
    robustness_passed: int = 0
    robustness_total: int = 0
    max_seconds: float = 5.0

    @property
    def ok(self) -> bool:
        rows_ok = all(r.passed for r in self.rows) and bool(self.rows)
        perf_ok = all(r.seconds < self.max_seconds for r in self.rows)
        return rows_ok and self.robustness_passed == self.robustness_total and perf_ok

    def table_ar(self) -> str:
        lines = [
            "بوابة المرحلة 4 — حلقة التغذية الراجعة (توليد ← مراجعة ← إصلاح)",
            f"{'المرساة':<14}{'اكتمال':<9}{'حتمية':<8}{'اعتدال':<8}{'تحسن':<7}{'ثوانٍ':>6}",
            "-" * 56,
        ]
        for r in self.rows:
            lines.append(
                f"{r.name:<14}"
                f"{'نعم' if r.completed else 'لا':<9}"
                f"{'نعم' if r.deterministic else 'لا':<8}"
                f"{'نعم' if r.idempotent else 'لا':<8}"
                f"{'نعم' if r.improved else 'لا':<7}"
                f"{r.seconds:>6.2f}"
            )
            for p in r.problems:
                lines.append(f"  ↳ {p}")
        lines.append("-" * 56)
        lines.append(
            f"المتانة: {self.robustness_passed}/{self.robustness_total} مدخلًا عدائيًا فشل فشلًا مهيكلًا آمنًا"
        )
        lines.append("النتيجة: البوابة ناجحة ✅" if self.ok else "النتيجة: البوابة فاشلة ❌")
        return "\n".join(lines)


def _final_sources(result: PipelineResult) -> dict[str, str]:
    return result.final_sources


def _check_idempotence(result: PipelineResult) -> list[str]:
    """G3: تمرير ناتج الحلقة النهائي على مُصلِح جديد ⇒ لا تغيير إطلاقًا."""
    problems: list[str] = []
    fixer = FixerEngine()
    for path, source in sorted(_final_sources(result).items()):
        again = fixer.fix_source(source, path)
        if again.changed:
            problems.append(f"الاعتدال مكسور في {path}: المُصلِح غيّر ناتج الحلقة")
    return problems


def _run_anchor(engine: PipelineEngine, label: str, desc: str, tmp: Path) -> GateRow:
    row = GateRow(name=label, description=desc)
    started = time.perf_counter()
    out1, out2 = tmp / f"{label}-1", tmp / f"{label}-2"
    first = engine.run(desc, out1, write=False, rounds=1)
    row.seconds = time.perf_counter() - started

    # G1 التكامل
    if not first.ok:
        row.problems.append(f"فشل في {first.failed_stage}: {first.error_ar}")
        return row
    row.completed = True
    if not first.files:
        row.problems.append("لم تُولَّد أي ملفات")
        return row

    # G4 التحسن: لا تراجع في أي ملف + إصلاحات فعلية
    regressions = [f["path"] for f in first.per_file if f["score_after"] < f["score_before"]]
    if regressions:
        row.problems.append(f"ملفات تراجعت درجتها: {', '.join(regressions)}")
    if first.fixed_total == 0:
        row.problems.append("لا إصلاحات — المراسي يجب أن تُظهر قيمة الحلقة")
    row.improved = not regressions and first.fixed_total > 0

    # G3 الاعتدال
    idem = _check_idempotence(first)
    row.problems.extend(idem)
    row.idempotent = not idem

    # G2 الحتمية: تشغيل ثانٍ ⇒ نفس البايتات
    second = engine.run(desc, out2, write=False, rounds=1)
    a = json.dumps(first.to_dict(), ensure_ascii=False, indent=2)
    b = json.dumps(second.to_dict(), ensure_ascii=False, indent=2)
    row.deterministic = a == b
    if not row.deterministic:
        row.problems.append("تشغيلان بنفس الوصف أعطيا حمولتين مختلفتين — الحتمية مكسورة")
    return row


def _check_robustness(engine: PipelineEngine, tmp: Path) -> tuple[int, int, list[str]]:
    """G5: كل مدخل عدائي ⇒ فشل مهيكل عربي (خروج 2) بلا أي استثناء."""
    passed = 0
    problems: list[str] = []
    total = len(_HOSTILE)
    for label, kwargs in _HOSTILE:
        options = dict(kwargs)
        occupied = bool(options.pop("occupied", False))
        out: str | Path = tmp / "hostile"
        if occupied:
            occ = tmp / "occupied"
            occ.mkdir(parents=True, exist_ok=True)
            (occ / "يوجد-ملف.txt").write_text("لا تمسّني", encoding="utf-8")
            out = occ
        try:
            result = engine.run(
                options.get("description"),
                out,  # type: ignore[arg-type]
                write=bool(options.get("write", occupied)),
                rounds=options.get("rounds", 1),  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001 — البوابة تُحصي الانهيار كمدخل فاشل
            problems.append(f"«{label}» رفع استثناء {type(exc).__name__} — يجب فشل مهيكل")
            continue
        structured = (
            not result.ok
            and result.exit_code == 2
            and result.failed_stage in (*STAGES, STAGE_PIPELINE)
            and bool(result.error_ar)
        )
        if structured:
            passed += 1
        else:
            problems.append(
                f"«{label}» لم يُنتج فشلًا مهيكلاً (ok={result.ok}, exit={result.exit_code})"
            )
    return passed, total, problems


def run_phase4_gate(
    descriptions: tuple[tuple[str, str], ...] | None = None,
    *,
    max_seconds: float = 5.0,
    tmp_root: str | Path | None = None,
) -> Phase4GateResult:
    """تشغيل البوابة كاملة — حتمية في الحكم، بلا شبكة وبلا نموذج."""
    anchors = descriptions or ANCHORS
    engine = PipelineEngine()
    result = Phase4GateResult(max_seconds=max_seconds)
    with tempfile.TemporaryDirectory(prefix="zyko-p4-gate-", dir=tmp_root) as td:
        tmp = Path(td)
        for label, desc in anchors:
            result.rows.append(_run_anchor(engine, label, desc, tmp))
        result.robustness_passed, result.robustness_total, rb = _check_robustness(engine, tmp)
    # مشاكل المتانة تُعرض في جدول البوابة دون أن تفسد صفوف المراسي —
    # فشلها محسوب أصلًا في robustness_passed مقابل robustness_total.
    for p in rb:
        result.rows.append(GateRow(name="متانة", description="", problems=[p]))
    return result


__all__ = [
    "ANCHORS",
    "GateRow",
    "MAX_ROUNDS",
    "Phase4GateResult",
    "run_phase4_gate",
]
