"""zyko.baseline.gate — بوابة قبول المرحلة 6: ست بوابات كمية أولًا بأول.

- W1 التكامل  : كل مرساة تُكمل (update ⇒ check) بلا فشل، بلا تراجع
- W2 الحتمية  : شجرتان متطابقتان ⇒ بايتات خط الأساس متطابقة تمامًا،
  وحمولة check متطابقة بعد توحيد حقل المسار
- W3 الكشف    : إفساد ملف عمدًا (eval) ⇒ check يكشف التراجع (خروج 1)
  ويسمّي الملف ويعدّ الملاحظات الجديدة
- W4 التحسن   : تنظيف النسخة (حذف أسوأ ملف) ⇒ check يعلن التحسن ويقترح
  تحديث خط الأساس (خروج 0)
- W5 المتانة  : مدخلات عدائية (12) ⇒ فشل مهيكل عربي أو حالة موثقة،
  بلا أي استثناء خارجي
- W6 الأداء   : دورة update+check كاملة لكل مرساة أسرع من الحد المعلن
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from zyko.baseline.engine import (
    F_IMPROVED,
    F_REGRESSED,
    STAGE_BASELINE,
    BaselineEngine,
)
from zyko.workspace.gate import ANCHORS as _WORKSPACE_ANCHORS

# مراسٍ البوابة: نفس أشجار المرحلة 5 الواقعية الثلاثة (مشروع مسطح،
# حزمة بمجلدات، وشجرة مختلطة بملفات فاسدة عمدًا) — إعادة استخدام كاملة
# كي يقيس الحارس نفس الواقع الذي يقيسه المحرك.
ANCHORS = _WORKSPACE_ANCHORS

# مدخلات W5 العدائية — كلها يجب أن تنتهي فشلًا مهيكلًا عربيًا (خروج 2).
_HOSTILE_LABELS: tuple[str, ...] = (
    "مجلد غير موجود",
    "ملف بدل مجلد",
    "مسار معدوم النوع",
    "مسار رقمي",
    "مسار بايتات",
    "خط أساس فاسد JSON",
    "خط أساس بترميز فاسد",
    "خط أساس قائمة",
    "مخطط غير معروف",
    "قسم ملفات غير صالح",
    "درجة نصية",
    "خط أساس مجلد لا ملف",
)
HOSTILE_TOTAL = len(_HOSTILE_LABELS)

_EVAL_LINE = '\n\ndef _gate_probe():\n    return eval("1 + 1")\n'


@dataclass
class GateRow:
    """نتيجة مرساة واحدة داخل بوابة المرحلة 6."""

    name: str
    description: str
    completed: bool = False
    deterministic: bool = False
    detects_regression: bool = False
    detects_improvement: bool = False
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.completed
            and self.deterministic
            and self.detects_regression
            and self.detects_improvement
        )


@dataclass
class Phase6GateResult:
    """نتيجة بوابة المرحلة 6 كاملة: صفوف المراسي + المتانة + الزمن."""

    rows: list[GateRow] = field(default_factory=list)
    robustness_passed: int = 0
    robustness_total: int = HOSTILE_TOTAL
    max_seconds: float = 5.0

    @property
    def ok(self) -> bool:
        rows_ok = all(r.passed for r in self.rows) and bool(self.rows)
        perf_ok = all(r.seconds < self.max_seconds for r in self.rows)
        return rows_ok and self.robustness_passed == self.robustness_total and perf_ok

    def table_ar(self) -> str:
        lines = [
            "بوابة المرحلة 6 — حارس الجودة (خط أساس + كشف تراجع وتحسن)",
            f"{'المرساة':<14}{'اكتمال':<9}{'حتمية':<8}{'كشف تراجع':<11}{'كشف تحسن':<10}{'ثوانٍ':>6}",
            "-" * 62,
        ]
        for r in self.rows:
            lines.append(
                f"{r.name:<14}"
                f"{'نعم' if r.completed else 'لا':<9}"
                f"{'نعم' if r.deterministic else 'لا':<8}"
                f"{'نعم' if r.detects_regression else 'لا':<11}"
                f"{'نعم' if r.detects_improvement else 'لا':<10}"
                f"{r.seconds:>6.2f}"
            )
            for p in r.problems:
                lines.append(f"  ↳ {p}")
        lines.append("-" * 62)
        lines.append(
            f"المتانة: {self.robustness_passed}/{self.robustness_total} مدخلًا عدائيًا فشل فشلًا مهيكلًا آمنًا"
        )
        lines.append("النتيجة: البوابة ناجحة ✅" if self.ok else "النتيجة: البوابة فاشلة ❌")
        return "\n".join(lines)


def _build_tree(root: Path, files: dict[str, "str | bytes"]) -> None:
    """يركّب شجرة مرساة في مجلد — بترتيب حتمي؛ bytes تُكتب كما هي."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8", newline="\n")


def _victim_file(files: dict[str, "str | bytes"]) -> str | None:
    """الملف الضحية الحتمي: أول ملف بايثون نصي بترتيب المسارات."""
    for path in sorted(files):
        if path.endswith(".py") and isinstance(files[path], str):
            return path
    return None


def _run_anchor(
    engine: BaselineEngine, label: str, files: dict[str, "str | bytes"], tmp: Path
) -> GateRow:
    row = GateRow(name=label, description="، ".join(sorted(files)))
    started = time.perf_counter()
    src1, src2 = tmp / f"{label}-1", tmp / f"{label}-2"
    _build_tree(src1, files)
    _build_tree(src2, files)

    # W1 التكامل: update ثم check على نفس الشجرة
    upd = engine.update(src1)
    if not upd.ok:
        row.problems.append(f"فشل التحديث في {upd.failed_stage}: {upd.error_ar}")
        row.seconds = time.perf_counter() - started
        return row
    if upd.reviewed == 0:
        row.problems.append("لم تُراقَب أي ملفات — المراسي يجب أن تحمل بايثون قابلاً للتحليل")
        row.seconds = time.perf_counter() - started
        return row
    first_check = engine.check(src1)
    if not first_check.ok:
        row.problems.append(f"فشل الفحص في {first_check.failed_stage}: {first_check.error_ar}")
        row.seconds = time.perf_counter() - started
        return row
    if first_check.regressed_files or first_check.exit_code != 0:
        row.problems.append("فحص الشجرة نفسها التي سُجلت أعاد تراجعًا — المقارنة غير مستقرة")
        row.seconds = time.perf_counter() - started
        return row
    row.completed = True

    # W3 كشف التراجع: أضف eval إلى ملف في النسخة الثانية ثم قارن
    victim = _victim_file(files)
    if victim is None:
        row.problems.append("لا ملف بايثون نصي في المرساة لكشف التراجع عليه")
        row.seconds = time.perf_counter() - started
        return row
    src_bad = tmp / f"{label}-bad"
    bad_files = dict(files)
    bad_files[victim] = (
        str(files[victim]) + _EVAL_LINE if isinstance(files[victim], str) else files[victim]
    )
    _build_tree(src_bad, bad_files)
    bad_check = engine.check(src_bad, baseline_path=src1 / ".zyko" / "baseline.json")
    if bad_check.ok and bad_check.regressed_files >= 1 and bad_check.exit_code == 1:
        row.detects_regression = True
        hit = next(
            (f for f in bad_check.per_file if f["path"] == victim and f["status"] == F_REGRESSED),
            None,
        )
        if hit is None:
            row.problems.append(f"كشف التراجع لم يسمّ الملف المفسود ({victim})")
            row.detects_regression = False
        elif hit["new_findings"] < 1:
            row.problems.append("التراجع كُشف دون عدّ ملاحظات جديدة")
            row.detects_regression = False
    else:
        row.problems.append(
            f"إفساد ملف عمدًا لم يُنتج تراجعًا (exit={bad_check.exit_code}, ok={bad_check.ok})"
        )

    # W4 التحسن: احذف الملف الضحية من النسخة الثانية — الحارس يجب أن يعلن
    # التحسن (درجة أعلى أو ملاحظات محسومة) أو اختفاء الملف المراقَب
    src_good = tmp / f"{label}-good"
    good_files = {k: v for k, v in files.items() if k != victim}
    _build_tree(src_good, good_files)
    good_check = engine.check(src_good, baseline_path=src1 / ".zyko" / "baseline.json")
    announced = [
        f
        for f in good_check.per_file
        if f["status"] in (F_IMPROVED, "gone") and f["path"] == victim
    ]
    if good_check.ok and announced and (good_check.improved_files + good_check.gone_files) >= 1:
        row.detects_improvement = True
    else:
        row.problems.append(
            f"تنظيف الشجرة لم يُعلن تحسنًا (exit={good_check.exit_code},"
            f" تحسّن={good_check.improved_files}, اختفت={good_check.gone_files})"
        )

    # W2 الحتمية: شجرة ثانية متطابقة ⇒ بايتات خط الأساس متطابقة تمامًا
    upd2 = engine.update(src2)
    base1 = src1 / ".zyko" / "baseline.json"
    base2 = src2 / ".zyko" / "baseline.json"
    if not upd2.ok:
        row.problems.append(f"التحديث على النسخة الثانية فشل: {upd2.error_ar}")
    elif base1.read_bytes() != base2.read_bytes():
        row.problems.append("شجرتان متطابقتان أعطيتا خطي أساس مختلفي البايتات")
    else:
        second_check = engine.check(src2, baseline_path=base2)
        d1, d2 = first_check.to_dict(), second_check.to_dict()
        d1["src"] = d2["src"] = "<anchor>"
        d1["baseline_path"] = d2["baseline_path"] = "<baseline>"
        if json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True):
            row.deterministic = True
        else:
            row.problems.append("حمولة check تختلف بين نسختين متطابقتين")

    row.seconds = time.perf_counter() - started
    return row


def _check_robustness(engine: BaselineEngine, tmp: Path) -> tuple[int, int, list[str]]:
    """W5: كل مدخل عدائي ⇒ فشل مهيكل عربي (خروج 2) بلا أي استثناء."""
    passed = 0
    problems: list[str] = []
    good = tmp / "good-proj"
    _build_tree(good, {"mod.py": "X = 1\n"})

    # خط أساس سليم للمقارنات العدائية (يرفع عدّاد التشغيل كأثر جانبي فقط)
    engine.update(good)

    corrupt = tmp / "corrupt.json"
    corrupt.write_text("{ليس json", encoding="utf-8")
    badenc = tmp / "badenc.json"
    badenc.write_bytes('{"schema": "zyko.baseline/1"}'.encode("utf-16"))
    list_base = tmp / "list.json"
    list_base.write_text("[1, 2, 3]\n", encoding="utf-8")
    wrong_schema = tmp / "schema.json"
    wrong_schema.write_text('{"schema": "zyko.baseline/9", "files": {}}\n', encoding="utf-8")
    bad_files = tmp / "badfiles.json"
    bad_files.write_text(
        '{"schema": "zyko.baseline/1", "files": ["ليست قاموسًا"]}\n', encoding="utf-8"
    )
    bad_score = tmp / "badscore.json"
    bad_score.write_text(
        '{"schema": "zyko.baseline/1", "files": {"a.py": {"score": "عالٍ",'
        ' "findings": [], "sha256": "x"}}}\n',
        encoding="utf-8",
    )
    dir_base = tmp / "dir-baseline"
    dir_base.mkdir(parents=True, exist_ok=True)

    plain_file = tmp / "plain.txt"
    plain_file.write_text("ملف لا مجلد", encoding="utf-8")

    cases: tuple[tuple[str, object, object], ...] = (
        ("مجلد غير موجود", tmp / "لا-يوجد", None),
        ("ملف بدل مجلد", plain_file, None),
        ("مسار معدوم النوع", None, None),
        ("مسار رقمي", 42, None),
        ("مسار بايتات", b"/tmp/bytes", None),
        ("خط أساس فاسد JSON", good, corrupt),
        ("خط أساس بترميز فاسد", good, badenc),
        ("خط أساس قائمة", good, list_base),
        ("مخطط غير معروف", good, wrong_schema),
        ("قسم ملفات غير صالح", good, bad_files),
        ("درجة نصية", good, bad_score),
        ("خط أساس مجلد لا ملف", good, dir_base),
    )
    for label, src, baseline in cases:
        try:
            result = engine.check(src, baseline_path=baseline)
        except Exception as exc:  # noqa: BLE001 — البوابة تُحصي الانهيار كفشل
            problems.append(f"«{label}» رفع استثناء {type(exc).__name__} — يجب فشل مهيكل")
            continue
        structured = (
            not result.ok
            and result.exit_code == 2
            and result.failed_stage in (STAGE_BASELINE, "scan", "reviewer")
            and bool(result.error_ar)
        )
        if structured:
            passed += 1
        else:
            problems.append(
                f"«{label}» لم يُنتج فشلًا مهيكلاً (ok={result.ok}, exit={result.exit_code})"
            )
    return passed, len(cases), problems


def run_phase6_gate(
    anchors: tuple[tuple[str, dict[str, "str | bytes"]], ...] | None = None,
    *,
    max_seconds: float = 5.0,
    tmp_root: str | Path | None = None,
) -> "Phase6GateResult":
    """تشغيل بوابة المرحلة 6 كاملة — حتمية الحكم، بلا شبكة وبلا نموذج."""
    cases = anchors or ANCHORS
    engine = BaselineEngine()
    result = Phase6GateResult(max_seconds=max_seconds)
    with tempfile.TemporaryDirectory(prefix="zyko-p6-gate-", dir=tmp_root) as td:
        tmp = Path(td)
        for label, files in cases:
            result.rows.append(_run_anchor(engine, label, files, tmp))
        result.robustness_passed, result.robustness_total, rb = _check_robustness(engine, tmp)
    for p in rb:
        result.rows.append(GateRow(name="متانة", description="", problems=[p]))
    return result


# توافق تسمية المراحل السابقة: نفس البوابة بالاسم الرقمي للمرحلة
run_phase_gate = run_phase6_gate

__all__ = [
    "ANCHORS",
    "GateRow",
    "HOSTILE_TOTAL",
    "Phase6GateResult",
    "run_phase6_gate",
    "run_phase_gate",
]
