"""zyko.benchmarks.selection — مسطرة دقة اختيار الملف (الموجة 20).

درس العينة الواسعة الموثق (``docs/SWEBENCH_FULL_2026-11-13.md`` §5.3):
43/44 حالة اختار العقل ملفاً حقيقياً، لكن **الدقة لم تُقَس بعد** —
الاختيار الصحيح مساراً لا يعني الإصلاح الصحيح معنىً، وحالة 1376
(العقل أصرّ على ملف اختبار خارج شجرة المصدر) فشل سلوكي بلا مسطرة
تلتقطه بعدّا. هذه الوحدة هي المسطرة:

- **المقارنة بمسارات الرقعة الذهبية حصراً** — لا بمحتواها: ملف
  ``benchmarks/data/swe_bench_gold_paths.json`` يحمل المسارات فقط،
  بلا سطر واحد من الرقعة الذهبية نفسها (عقد الموجة 19: المقياس هو
  zyko لا الوحش). المسارات تُقرأ هنا **للقياس بعد الجولة** — لا تُلحق
  بطلب العقل ولا تمر عبر البوابات إلى أي مُقترح، فالجولة تعمل
  بمعزلها المعتاد والمسطرة تحكم بعد انتهائها.
- **دقة لكل حالة**: (المسارات المختارة ∩ الذهبية) ÷ المختارة، وأي
  إصابة واحدة عبر كل محاولات الحالة = إصابة أيقونية (hit_any).
- **الصمت الصادق**: بلا ملف مسارات أو بلا اختيارات، التقرير يعلن
  «غير مقاسة» وسببه — لا صفر مفبرك ولا ادعاء بلا عدّاد.

    from zyko.benchmarks.selection import load_gold_paths, selection_accuracy

    gold = load_gold_paths(Path("benchmarks/data/swe_bench_gold_paths.json"))
    report = selection_accuracy(results, gold)
    report.hit_rate  # نسبة الحالات التي أصاب العقل فيها مساراً ذهبياً
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["SelectionReport", "load_gold_paths", "selection_accuracy"]

DEFAULT_GOLD_PATHS = Path("benchmarks/data/swe_bench_gold_paths.json")

_UNMEASURED_AR = "غير مقاسة — {reason}"


@dataclass(frozen=True)
class SelectionReport:
    """تقرير دقة الاختيار — كل رقم من وثيقة نتائج لا من تقدير."""

    measured: bool
    reason_ar: str = ""
    cases_with_choice: int = 0
    cases_with_gold: int = 0
    hit_any: int = 0
    hit_rate: float = 0.0  # إصابة أيقونية على الحالات القابلة للقياس
    mean_precision: float = 0.0  # متوسط دقة المسارات المختارة لكل حالة
    misses: tuple[str, ...] = ()  # معرفات الحالات التي لم تصب أي مسار ذهبي — مرتبة

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "reason_ar": self.reason_ar,
            "cases_with_choice": self.cases_with_choice,
            "cases_with_gold": self.cases_with_gold,
            "hit_any": self.hit_any,
            "hit_rate": round(self.hit_rate, 4),
            "mean_precision": round(self.mean_precision, 4),
            "misses": list(self.misses),
        }


def load_gold_paths(path: Path) -> dict[str, tuple[str, ...]]:
    """اقرأ ملف المسارات الذهبية — مسارات حصراً، الرقعة نفسها غير موجودة أصلاً.

    الملف مخطط موثق: ``{"instances": {"<معرف>": ["مسار", …]}}`` — أي
    قيمة غير قائمة مسارات تُرفض لا تُسكت (البيانات الفاسدة عدو القياس).
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    raw = doc.get("instances")
    if not isinstance(raw, dict):
        raise ValueError("ملف المسارات الذهبية فاسد — المفتاح «instances» قاموس حصراً")
    gold: dict[str, tuple[str, ...]] = {}
    for instance_id, paths in raw.items():
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ValueError(f"مسارات «{instance_id}» ليست قائمة مسارات نصية — ملف فاسد")
        gold[instance_id] = tuple(sorted(dict.fromkeys(paths)))
    return gold


def selection_accuracy(
    results: list[dict[str, Any]],
    gold_map: dict[str, tuple[str, ...]] | None,
) -> SelectionReport:
    """حكم دقة الاختيار من وثيقة النتائج نفسها — بلا إعادة تشغيل ولا نموذج.

    ``results``: سجلات وثيقة المتسابق (كل سجل فيه ``instance_id`` و
    ``loop.file_choices``). الحالات بلا اختيار أو بلا مسارات ذهبية
    تُستثنى من القياس وتُعلن أسبابها — التشغيل المقطوع صادق أيضاً.
    """
    if not gold_map:
        return SelectionReport(
            measured=False, reason_ar=_UNMEASURED_AR.format(reason="لا ملف مسارات ذهبية")
        )
    measurable = 0
    hits = 0
    precisions: list[float] = []
    misses: list[str] = []
    cases_with_gold = 0
    for record in results:
        loop = record.get("loop") or {}
        choices = [c for c in loop.get("file_choices", []) or [] if c]
        gold = gold_map.get(record.get("instance_id", ""))
        if not gold:
            continue
        cases_with_gold += 1
        if not choices:
            continue
        chosen = set(choices)
        measurable += 1
        overlap = len(chosen & set(gold))
        if overlap > 0:
            hits += 1
            precisions.append(overlap / len(chosen))
        else:
            misses.append(record.get("instance_id", ""))
    if not measurable:
        return SelectionReport(
            measured=False,
            reason_ar=_UNMEASURED_AR.format(reason="لا حالة لها اختيار ومسارات ذهبية معاً"),
            cases_with_gold=cases_with_gold,
        )
    return SelectionReport(
        measured=True,
        reason_ar=f"مقاسة على {measurable} حالة من {len(gold_map)} ذهبية موثقة",
        cases_with_choice=measurable,
        cases_with_gold=cases_with_gold,
        hit_any=hits,
        hit_rate=hits / measurable,
        mean_precision=sum(precisions) / len(precisions),
        misses=tuple(sorted(misses)),
    )
