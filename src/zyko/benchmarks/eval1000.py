"""zyko.benchmarks.eval1000 — مختبر التقييم الكبير: 1000 حالة متنوعة تقيس قدرة zyko.

بعد اثني عشر موجة تطوير (0.24.0 → 0.36.0) احتاج المشروع إلى ما طالبه كل
تقييم جدّي للذكاء الاصطناعي: **عدّة قياس شاملة** تجيب على ثلاثة أسئلة
بأرقام لا بشعارات — أين نحن؟ ما نقاط القوة؟ وما نقاط الضعف التي تُعالج
في الموجة التالية؟

البنية:

  * **1000 حالة** موزعة على عشرين إمارة (category) تغطي كل ما بُني:
    كاشف الخصوصية العربي، محارف الاتجاه، البوابات الثلاث، عقود
    الصلاحيات، سجل التدقيق الموقّع، الرقع والتشغيل، العزل النووي،
    الانعكاس والميزانية، الذاكرة الموقعة العابرة للجلسات، التصنيف
    والتوجيه، المصنع الحتمي، المراجعة والإصلاح، البنية المهيكلة،
    السياسة والحجب، النواة والرسائل، والإيصالات واكتشاف الجلسة
    والخريطة الدلالية.
  * **حقيقة لا نموذج** — كل حالة تنادي كود zyko الحقيقي (بلا شبكة،
    بلا نموذج لغوي، بلا mock للطبقة المقيسة) وتحكم على العقد الموثق:
    نفس المدخل يعطي الحكم نفسه بالبايت.
  * **الفشل صادق** — الحالة الفاشلة تبقى فاشلة باسمها وسببها العربي
    في التقرير؛ لا تُخفى ولا تُعتذر، فهي خريطة الموجة القادمة.
  * **إيصال حتمي بالبايت** — التقرير بلا أزمنة، ببصمة سلسلة sha256
    فوق (المعرّف + الحكم + السبب) بترتيب ثابت، وجدول عربي يصنف كل
    إمارة: قوة (≥95%)، مراقبة (85–95%)، ضعف (<85%).

    from zyko.benchmarks.eval1000 import run_eval1000

    report = run_eval1000()
    assert report.total == 1000
    print(report.table_ar())

على سطر الأوامر::

    python -m zyko.benchmarks.eval1000 --count     # بنية العدّة بلا تشغيل
    python -m zyko.benchmarks.eval1000 --run       # تشغيل كامل + تقرير
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "CASES_TOTAL",
    "STRENGTH_THRESHOLD",
    "WATCH_THRESHOLD",
    "CATEGORY_LABELS",
    "EvalCase",
    "EvalReport",
    "build_eval_cases",
    "run_eval1000",
]

# العدد التعاقدي للعدّة — أي انحراف كسر موثق يرفضه الاختبار البنيوي
CASES_TOTAL = 1000

# عتبات التصنيف المعلنة — قوة لا تُشترى وتدنٍ لا يُخفى
STRENGTH_THRESHOLD = 0.95
WATCH_THRESHOLD = 0.85

# التسمية العربية لكل إمارة — تظهر في الجدول والإيصال
CATEGORY_LABELS: dict[str, str] = {
    "pii-phone": "الهواتف العربية",
    "pii-nid": "الهويات الوطنية",
    "pii-iban-cards": "آيبان وبطاقات",
    "pii-names": "أسماء وعناوين وبريد",
    "pii-redact": "الحجب والترقيم",
    "rtl": "اتجاه النص ومحارفه",
    "gates": "البوابات الثلاث",
    "contracts": "عقود الصلاحيات",
    "audit": "سجل التدقيق الموقّع",
    "patch-run": "الرقع والتشغيل",
    "jail": "العزل النووي",
    "reflect": "الانعكاس والميزانية",
    "ledger": "الذاكرة الموقعة",
    "classify-route": "التصنيف والتوجيه",
    "factory": "المصنع الحتمي",
    "review-fix": "المراجعة والإصلاح",
    "structured": "البنية المهيكلة",
    "policy": "السياسة والحجب",
    "kernel-core": "النواة والرسائل",
    "receipts": "الإيصالات والجلسة",
}

_CASE_FN = Callable[[], "tuple[bool, str]"]


@dataclass(frozen=True)
class EvalCase:
    """حالة تقييم واحدة: معرّف ثابت + إمارة + عنوان عربي + حكم تنفيذي.

    ``fn`` ينادي كود zyko الحقيقي ويعيد ``(نجاح، سبب_عربي)`` — الحكم
    على العقد الموثق لا على توقع متغير. المعرّف ``E-0001…E-1000`` ثابت
    بالبايت فأي انزياح في العدّة يُكتشف من بصمة السلسلة.
    """

    case_id: str
    category: str
    family: str
    title_ar: str
    fn: _CASE_FN

    def meta_dict(self) -> dict[str, Any]:
        """ممثل JSON للميتا بلا الدالة التنفيذية — حتمي بالبايت."""
        return {
            "case_id": self.case_id,
            "category": self.category,
            "family": self.family,
            "title_ar": self.title_ar,
        }


@dataclass(frozen=True)
class EvalRow:
    """نتيجة حالة واحدة: معرّف + إمارة + حكم + سبب عربي موثق."""

    case_id: str
    category: str
    family: str
    title_ar: str
    ok: bool
    detail_ar: str

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON حتمي — بلا أي زمن."""
        return {
            "case_id": self.case_id,
            "category": self.category,
            "family": self.family,
            "title_ar": self.title_ar,
            "ok": self.ok,
            "detail_ar": self.detail_ar,
        }


def _category_stats(rows: tuple[EvalRow, ...]) -> dict[str, dict[str, Any]]:
    """إحصاء لكل إمارة: المجموع، الناجح، النسبة، والتصنيف المعلن."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        stat = out.setdefault(row.category, {"total": 0, "passed": 0})
        stat["total"] += 1
        stat["passed"] += 1 if row.ok else 0
    for stat in out.values():
        stat["rate"] = round(stat["passed"] / stat["total"], 4) if stat["total"] else 0.0
        rate = stat["rate"]
        stat["verdict_ar"] = (
            "قوة" if rate >= STRENGTH_THRESHOLD
            else "مراقبة" if rate >= WATCH_THRESHOLD
            else "ضعف"
        )
    return out


@dataclass(frozen=True)
class EvalReport:
    """تقرير التقييم الكبير — إيصال حتمي بالبايت قابل للتحقق."""

    cases: tuple[EvalCase, ...]
    rows: tuple[EvalRow, ...]

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r.ok)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def ok(self) -> bool:
        return self.total == len(self.cases) == CASES_TOTAL and self.passed == self.total

    @property
    def by_category(self) -> dict[str, dict[str, Any]]:
        return _category_stats(self.rows)

    @property
    def chain_hash(self) -> str:
        """بصمة السلسلة: sha256 فوق (المعرّف + الحكم + السبب) بترتيب العدّة."""
        digest = hashlib.sha256()
        for row in self.rows:
            digest.update(row.case_id.encode("utf-8"))
            digest.update(b"\x1f")
            digest.update(b"1" if row.ok else b"0")
            digest.update(b"\x1f")
            digest.update(row.detail_ar.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def failures(self) -> tuple[EvalRow, ...]:
        """الحالات الفاشلة بترتيبها — خريطة الموجة القادمة."""
        return tuple(r for r in self.rows if not r.ok)

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        """إيصال حتمي بالبايت — الزمن خارج الإيصال إلا بطلب صريح."""
        return {
            "kind": "eval1000",
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "ok": self.ok,
            "chain_hash": self.chain_hash,
            "thresholds": {
                "strength": STRENGTH_THRESHOLD,
                "watch": WATCH_THRESHOLD,
            },
            "by_category": self.by_category,
            "rows": [row.to_dict() for row in self.rows],
        }

    def to_json(self, *, include_timing: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_timing=include_timing),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )

    def table_ar(self) -> str:
        """الجدول العربي: كل إمارة × نسبتها × تصنيفها المعلن."""
        width = 46
        lines = [
            "مختبر التقييم الكبير — ZYKO Eval-1000: أين نحن بالأرقام",
            "=" * width,
            f"{'الإمارة':26} {'المجموع':>7} {'الناجح':>7} {'النسبة':>8} {'الحكم':>6}",
            "-" * width,
        ]
        for cat in CATEGORY_LABELS:
            stat = self.by_category.get(cat)
            if stat is None:
                continue
            label = CATEGORY_LABELS[cat][:26]
            lines.append(
                f"{label:26} {stat['total']:>7} {stat['passed']:>7} "
                f"{stat['rate'] * 100:>7.1f}% {stat['verdict_ar']:>6}"
            )
        lines.append("-" * width)
        lines.append(
            f"الإجمالي: {self.passed}/{self.total} حالة ناجحة — بصمة السلسلة: {self.chain_hash[:16]}…"
        )
        failures = self.failures()
        if not failures:
            lines.append("الناتج النهائي: ✅ 100% — كل العدّة تجتاز عقودها")
        else:
            lines.append(f"الناتج النهائي: ⚠ {self.failed} حالة فاشلة — خريطة الموجة القادمة:")
            for row in failures[:20]:
                lines.append(f"  ✗ {row.case_id} [{row.category}] {row.title_ar}")
                lines.append(f"      {row.detail_ar[:110]}")
            if len(failures) > 20:
                lines.append(f"  … و{len(failures) - 20} حالة أخرى في الإيصال الكامل")
        return "\n".join(lines)


def build_eval_cases() -> tuple[EvalCase, ...]:
    """ابنِ العدّة الكاملة (1000 حالة) — حتمية بالبايت في الترتيب والمعرّفات.

    البناة الحتمية في ``eval1000_cases`` تنتج قوائم ثابتة؛ الترقيم
    ``E-0001…`` يوزع بالترتيب المعلن، وأي انحراف عن العقد (1000 حالة،
    عشرون إمارة) يرفض هنا فلا يدخل تقرير مبتور السلسلة.
    """
    from zyko.benchmarks.eval1000_cases import CASE_BUILDERS, CATEGORY_ORDER

    cases: list[EvalCase] = []
    for category in CATEGORY_ORDER:
        builder = CASE_BUILDERS[category]
        for family, title_ar, fn in builder():
            index = len(cases) + 1
            cases.append(
                EvalCase(
                    case_id=f"E-{index:04d}",
                    category=category,
                    family=family,
                    title_ar=title_ar,
                    fn=fn,
                )
            )
    if len(cases) != CASES_TOTAL:
        raise ValueError(
            f"عقد العدّة مكسور: المبني {len(cases)} حالة والمتعاقد {CASES_TOTAL} — "
            "الترقيم وبصمة السلسلة تنكسران مع أي انزياح"
        )
    missing = [c for c in CATEGORY_ORDER if c not in {x.category for x in cases}]
    if missing:
        raise ValueError(f"إمارات بلا حالات: {missing}")
    return tuple(cases)


def run_eval1000(
    *,
    cases: tuple[EvalCase, ...] | None = None,
    stop_on_first_fail: bool = False,
) -> EvalReport:
    """شغّل العدّة الكاملة — كل حالة على كود zyko الحقيقي بلا شبكة.

    الاستثناء في حالة ما هو فشل حالة لا انهيار عدّة: الحالة تعود
    فاشلة بتفصيل عربي موثق، والسلسلة تكمل حتى آخر حالة — الفحص يجمع
    لا ينهار، والميزانية الزمنية داخل كل حالة (سقوف العقد نفسها).
    ``stop_on_first_fail`` باب تشخيصي صريح للتطوير لا للتقييم.
    """
    if cases is None:
        cases = build_eval_cases()
    rows: list[EvalRow] = []
    for case in cases:
        try:
            ok, detail = case.fn()
        except Exception as exc:  # noqa: BLE001 — الفحص يجمع ولا ينهار
            ok, detail = False, f"استثناء غير متوقع: {type(exc).__name__}: {exc}"
        rows.append(
            EvalRow(
                case_id=case.case_id,
                category=case.category,
                family=case.family,
                title_ar=case.title_ar,
                ok=bool(ok),
                detail_ar=str(detail),
            )
        )
        if stop_on_first_fail and not ok:
            break
    if not stop_on_first_fail:
        with tempfile.TemporaryDirectory(prefix="zyko-eval1000-") as _tmp:
            pass  # المجلدات المؤقتة تُدار داخل كل حالة — لا حالة مشتركة
    return EvalReport(cases=cases, rows=tuple(rows))


# --------------------------------------------------------------- المشغّل
def main(argv: list[str] | None = None) -> int:
    """سطر الأوامر: ``--count`` بنية العدّة، ``--run`` تقييم كامل."""
    parser = argparse.ArgumentParser(
        prog="python -m zyko.benchmarks.eval1000",
        description="مختبر التقييم الكبير — 1000 حالة على كود zyko الحقيقي",
    )
    parser.add_argument("--run", action="store_true", help="شغّل العدّة كاملة واطبع التقرير")
    parser.add_argument("--count", action="store_true", help="اطبع بنية العدّة بلا تشغيل")
    parser.add_argument("--json", type=str, default="", help="اكتب الإيصال JSON في مسار")
    args = parser.parse_args(argv)

    cases = build_eval_cases()
    if args.count or not args.run:
        print(f"العدّة التعاقدية: {len(cases)} حالة على {len(CATEGORY_LABELS)} إمارة")
        per: dict[str, int] = {}
        for case in cases:
            per[case.category] = per.get(case.category, 0) + 1
        for category in CATEGORY_ORDER:
            print(f"  {CATEGORY_LABELS[category]:26} {per.get(category, 0):>5} حالة")
        print(f"بصمة بنية العدّة: {hashlib.sha256(''.join(c.case_id + c.category for c in cases).encode()).hexdigest()[:16]}…")
        return 0

    report = run_eval1000(cases=cases)
    print(report.table_ar())
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_json(), encoding="utf-8")
        print(f"الإيصال كُتب: {path}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    from zyko.benchmarks.eval1000_cases import CATEGORY_ORDER  # noqa: F401 — للطباعة فقط

    raise SystemExit(main())
