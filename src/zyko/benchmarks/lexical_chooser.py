"""zyko.benchmarks.lexical_chooser — مختار معجمي حتمي: مسطرة قيمة الخريطة بلا نموذج.

الموجة 21 (الفجوة الثالثة الموثقة — تقرير 0.43.0 §7): الخريطة الدلالية
موجودة منذ جولة 11، واختيارات العقل الحقيقي مرساة 74.42% على العينة
الواسعة. لكن الحكم على **قيمة ترقية الخريطة نفسها** لا يقبل الاستقراء:
نموذج حقيقي جديد هو تشغيل الموجة 22 — وقبل تشغيله يلزم عدّة تقيس
بلا تقلب النموذج: **كم من المعلومة في الخريطة يكفي مُختارًا حتميًا
بلا أي ذكاء ليصيب المسار الذهبي؟**

العقود:
- **حتمي بالبايت**: نفس الاستعلام ونفس الشجرة ونفس الخريطة ⇒ نفس
  الترتيب — الفرز (الدرجة، المسار) عقد لا تفضيل.
- **بلا شبكة وبلا نموذج**: معجم وتقاطعات حصراً — القياس يعيد إنتاجه
  أي جهاز بأي نواة بأي وقت.
- **مقارنة معلنة**: الخريطة مطفأة (مسارات حصراً) مقابل الخريطة
  (رموز + توقيعات) — الفرق قيمة الخريطة المنصّة لا ادعاء.

الأداة لا تحل محل العقل: رقمها حَدٌّ **أدنى** لمعلومات الخريطة
(مختار معجمي لا يفهم المعنى)، وأي مختار ذكي فوقها يستثمر الرصيد
نفسه. مرساة العقل (74.42%) تبقى المرجع الذي يُقارن عليه التشغيل
الحقيقي للموجة 22.

    from zyko.benchmarks.lexical_chooser import rank_files

    ranked = rank_files(query, tree, map_lines=map_lines)
    ranked[0]  # المسار الأعلى درجة — حتمي بالبايت
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["rank_files", "tokenize", "query_tokens"]

#: كلمات وظيفية إنجليزية تُهمل — أسماء النطاق (response، session…) لا تُلمس
_STOPWORDS: frozenset[str] = frozenset(
    """a about after all also an and any are as at be because been before being both but by
    can could did do does done during each else for from had has have if in into is it its
    just like may might more most must need needs no not of on only or other our out over
    per same should so some such than that the their them then there these they this those
    to too under until up upon use used using very want was we were what when which while
    who will with within without would you your""".split()
)

_TOKEN_RX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u0600-\u06FF]+")

#: عقدة اختبار «tests/test_x.py::TestY::test_z» تتكرر كما هي — نأخذ طرفها الأخير
_NODE_RX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tokenize(text: str) -> frozenset[str]:
    """رموز معجمية: كلمات لاتينية وعربية بلا علامات — كلمات الوظيف تُهمل."""
    return frozenset(
        tok.lower() for tok in _TOKEN_RX.findall(text) if tok.lower() not in _STOPWORDS
    )


def query_tokens(problem: str, fail_to_pass: tuple[str, ...] | list[str]) -> frozenset[str]:
    """رموز الاستعلام: التقرير + أطراف عقد الفشل (ملف العقدة واختبارها)."""
    tokens: set[str] = set(tokenize(problem))
    for node in fail_to_pass:
        for part in str(node).split("::"):
            tokens |= set(_NODE_RX.findall(part))
    return frozenset(tok.lower() for tok in tokens if tok.lower() not in _STOPWORDS)


def _line_tokens(line: str) -> frozenset[str]:
    return tokenize(line)


def rank_files(
    query: str,
    tree: tuple[str, ...],
    map_lines: tuple[str, ...] | list[str] | None = None,
    fail_to_pass: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    """الترتيب الحتمي للشجرة: (درجة التقاطع مع الاستعلام، المسار) تنازلياً.

    درجة الملف: تقاطع رموز الاستعلام مع رموز مساره (أساس ×1) ومع رموز
    سطر خريطته إن وجد (رموز ×2 — التوقيع الدلالي أثقل من اسم الشارع) —
    والأزواج المتساوية تُفروز بالمسار، فالحتمية عقد.
    """
    q = query_tokens(query, fail_to_pass)
    map_by_path: dict[str, str] = {}
    for line in map_lines or ():
        if "::" in line:
            path, _, rest = line.partition(" :: ")
            map_by_path[path] = rest
    scored: list[tuple[float, str]] = []
    for path in tree:
        path_toks = tokenize(path)
        score = 2.0 * len(path_toks & q)
        sym_toks = _line_tokens(map_by_path.get(path, ""))
        score += 2.0 * len(sym_toks & q)
        scored.append((-score, path))
    scored.sort()
    return tuple(path for _, path in scored)


def case_hit(
    ranked: tuple[str, ...],
    gold_paths: tuple[str, ...],
    top_k: int = 1,
) -> bool:
    """إصابة أيقونية: أي مسار ذهبي ضمن أول ``top_k`` من الترتيب الحتمي."""
    if not gold_paths or not ranked:
        return False
    head = set(ranked[:top_k])
    return bool(head & set(gold_paths))


def precision_at_k(
    ranked: tuple[str, ...],
    gold_paths: tuple[str, ...],
    top_k: int = 1,
) -> float | None:
    """دقة أعلى ``top_k``: (المضروب ∩ الذهبي) ÷ top_k — بلا اختيار تُعاد None."""
    if not gold_paths or not ranked:
        return None
    head = ranked[:top_k]
    return len(set(head) & set(gold_paths)) / max(len(head), 1)


def summarize_hits(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """خلاصة عدّة القياس من سجلات كل حالة — بلا ادعاء: ما قيس قيس وما سقط موثق."""
    measurable = [r for r in records if r.get("measured")]
    if not measurable:
        return {"measured": False, "reason_ar": "لا حالة قابلة للقياس — بلا ذهبي ولا ترتيب"}

    def _rate(key: str) -> float:
        return sum(1 for r in measurable if r[key]) / len(measurable)

    return {
        "measured": True,
        "measurable_cases": len(measurable),
        "hit_top1_map": round(_rate("hit_top1_map"), 4),
        "hit_top1_no_map": round(_rate("hit_top1_no_map"), 4),
        "hit_top3_map": round(_rate("hit_top3_map"), 4),
        "misses_top1_map": sorted(r["instance_id"] for r in measurable if not r["hit_top1_map"]),
        "gained_by_map": sorted(
            r["instance_id"] for r in measurable if r["hit_top1_map"] and not r["hit_top1_no_map"]
        ),
    }
