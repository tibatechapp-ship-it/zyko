"""zyko.reviewer.report — المخرجات: JSON مهيكل + تقرير نصي عربي RTL.

الإخراجان حتميان بافتراض include_timing=False (الافتراضي): نفس النتيجة
⇒ نفس البايتات تمامًا. الوقت يظهر فقط عند طلبه صراحة (التقارير البشرية
في الطرفية)، وتبقى حمولات CI والاختبارات والبوابات موقّعة بايتيًا.
"""

from __future__ import annotations

import json
from typing import Any

from zyko.reviewer.engine import ReviewResult, summarize
from zyko.reviewer.rules import SEVERITIES, SEVERITY_AR

_LINE = "-" * 46


def result_to_json(result: ReviewResult, *, include_timing: bool = False) -> str:
    """حمولة JSON واحدة حتمية (بدون مسافات زائدة، ASCII عربي أصيل)."""
    return json.dumps(
        result.to_dict(include_timing=include_timing),
        ensure_ascii=False,
        indent=2,
    )


def results_to_json(results: list[ReviewResult], *, include_timing: bool = False) -> str:
    """حمولة دفعة (مجلد): كل ملف + ملخص — حتمية بايتيًا."""
    payload = {
        "schema": summarize(results)["schema"],
        "files": [r.to_dict(include_timing=include_timing) for r in results],
        "summary": summarize(results),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def result_to_text(result: ReviewResult) -> str:
    """تقرير عربي مقروء لملف واحد — بلا رموز ثنائية الاتجاه إطلاقًا."""
    lines: list[str] = []
    lines.append(f"الملف: {result.path}")
    if result.parse_error is not None:
        lines.append(f"الحكم: {result.verdict_ar} — {result.parse_error}")
        return "\n".join(lines)
    counts_ar = "، ".join(
        f"{SEVERITY_AR[s]} {result.counts.get(s, 0)}" for s in SEVERITIES if result.counts.get(s, 0)
    )
    lines.append(f"الدرجة: {result.score}/100 — الحكم: {result.verdict_ar}")
    lines.append(f"الملاحظات: {len(result.findings)}" + (f" — {counts_ar}" if counts_ar else ""))
    if result.findings:
        lines.append(_LINE)
        for f in result.findings:
            detail = f" ({f.detail_ar})" if f.detail_ar else ""
            lines.append(
                f"[{SEVERITY_AR[f.severity]}] سطر {f.line} عمود {f.col + 1} "
                f"{f.rule_id}: {f.message_ar}{detail}"
            )
            lines.append(f"    الإصلاح: {f.suggestion_ar}")
    return "\n".join(lines)


def results_to_text(results: list[ReviewResult]) -> str:
    """تقرير دفعة: تقرير كل ملف ثم خلاصة عربية."""
    blocks = [result_to_text(r) for r in results]
    summary = summarize(results)
    counts_ar = "، ".join(
        f"{SEVERITY_AR[s]} {summary['counts'][s]}" for s in SEVERITIES if summary["counts"][s]
    )
    header = f"مراجعة {summary['files']} ملفًا — مجموع الملاحظات {summary['total_findings']}" + (
        f" — {counts_ar}" if counts_ar else ""
    )
    footer = "أسوأ الملفات: " + (
        "، ".join(f"{w['path']} ({w['score']})" for w in summary["worst_files"]) or "لا شيء"
    )
    return "\n\n".join(blocks + [header, footer])


def rules_table_text(rules: Any) -> str:
    """جدول القواعد للعرض: المعرف، الخطورة، الفئة، الرسالة."""
    from zyko.reviewer.rules import CATEGORY_AR

    lines = ["المعرف | الخطورة | الفئة | الرسالة"]
    for r in rules:
        lines.append(
            f"{r.rule_id} | {SEVERITY_AR[r.severity]} | {CATEGORY_AR[r.category]} | {r.message_ar}"
        )
    return "\n".join(lines)


__all__ = [
    "result_to_json",
    "result_to_text",
    "results_to_json",
    "results_to_text",
    "rules_table_text",
]
