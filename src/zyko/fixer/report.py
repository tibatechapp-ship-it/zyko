"""zyko.fixer.report — المخرجات: JSON مهيكل + تقرير نصي عربي RTL.

الإخراجان حتميان بافتراض include_timing=False (الافتراضي): نفس النتيجة
⇒ نفس البايتات تمامًا. بلا رموز ثنائية الاتجاه إطلاقًا (بوابة RTL).
"""

from __future__ import annotations

import json
from typing import Any

from zyko.fixer.engine import FixResult, summarize_fix
from zyko.reviewer.rules import SEVERITIES, SEVERITY_AR

_LINE = "-" * 46


def fix_result_to_json(result: FixResult, *, include_timing: bool = False) -> str:
    """حمولة JSON واحدة حتمية (عربي أصيل بلا تهريب)."""
    return json.dumps(result.to_dict(include_timing=include_timing), ensure_ascii=False, indent=2)


def fix_results_to_json(results: list[FixResult], *, include_timing: bool = False) -> str:
    """حمولة دفعة (مجلد): كل ملف + ملخص — حتمية بايتيًا."""
    payload = {
        "schema": summarize_fix(results)["schema"],
        "files": [r.to_dict(include_timing=include_timing) for r in results],
        "summary": summarize_fix(results),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def fix_result_to_text(result: FixResult) -> str:
    """تقرير عربي مقروء لملف واحد — كل ملاحظة تحمل الإصلاح المقترح."""
    lines: list[str] = []
    if result.parse_error is not None:
        lines.append(f"الملف: {result.path}")
        lines.append(f"الحالة: غير قابل للإصلاح — {result.parse_error}")
        return "\n".join(lines)
    state = "عُدِّل" if result.changed else "لم يتغير"
    lines.append(
        f"الملف: {result.path} — الدرجة {result.score_before}/100 → "
        f"{result.score_after}/100 — {state}"
    )
    lines.append(
        f"الملاحظات: {len(result.outcomes)} — أُصلح آليًا {result.fixed_count}، "
        f"يدوي {result.manual_count}، مفتوح {result.open_count}"
    )
    if result.outcomes:
        lines.append(_LINE)
        for o in result.outcomes:
            detail = f" [{o.status_ar}]"
            lines.append(f"{detail} سطر {o.line} عمود {o.col + 1} {o.rule_id}: {o.message_ar}")
            if o.status == "fixed":
                lines.append(f"    الإجراء: {o.action_ar}")
            else:
                lines.append(f"    السبب: {o.action_ar}")
            lines.append(f"    الإصلاح: {o.suggestion_ar}")
    return "\n".join(lines)


def fix_results_to_text(results: list[FixResult]) -> str:
    """تقرير دفعة: تقرير كل ملف ثم خلاصة عربية."""
    blocks = [fix_result_to_text(r) for r in results]
    s = summarize_fix(results)
    header = (
        f"إصلاح {s['files']} ملفًا — عُدِّل {s['changed_files']} — "
        f"أُصلح آليًا {s['fixed']}، يدوي {s['manual']}، مفتوح {s['open']}"
    )
    footer = f"أدنى درجة بعد الإصلاح: {s['min_score_after']}/100"
    return "\n\n".join(blocks + [header, footer])


def fix_rules_table_text() -> str:
    """جدول مسارات الإصلاح: المعرف، النمط، الفئة، الإجراء."""
    from zyko.fixer.fixes import ACTION_AR, AUTO_FIXABLE, MANUAL_RULES
    from zyko.reviewer.rules import CATEGORY_AR, RULES_BY_ID

    lines = ["المعرف | النمط | الفئة | الإجراء"]
    for rid in AUTO_FIXABLE:
        rule = RULES_BY_ID[rid]
        lines.append(f"{rid} | آلي | {CATEGORY_AR[rule.category]} | {ACTION_AR[rid]}")
    for rid in MANUAL_RULES:
        rule = RULES_BY_ID[rid]
        lines.append(f"{rid} | يدوي | {CATEGORY_AR[rule.category]} | {rule.suggestion_ar}")
    return "\n".join(lines)


def fix_summary_line(results: list[FixResult]) -> str:
    """سطر خلاصة واحد للطرفية (وضع summary)."""
    s = summarize_fix(results)
    return (
        f"الملفات: {s['files']} — عُدِّل {s['changed_files']} — "
        f"أُصلح آليًا {s['fixed']}، يدوي {s['manual']}، مفتوح {s['open']} — "
        f"أدنى درجة بعد الإصلاح {s['min_score_after']}"
    )


def severity_breakdown(counts: dict[str, int]) -> str:
    """تفصيل عربي بعدد الملاحظات لكل خطورة (للحمولات النصية)."""
    parts = [f"{SEVERITY_AR[s]} {counts.get(s, 0)}" for s in SEVERITIES if counts.get(s, 0)]
    return "، ".join(parts) if parts else "لا شيء"


def batch_header(results: list[FixResult]) -> dict[str, Any]:
    """رأس حمولة الدفعة — للقارئات الآلية."""
    return summarize_fix(results)


__all__ = [
    "batch_header",
    "fix_result_to_json",
    "fix_result_to_text",
    "fix_results_to_json",
    "fix_results_to_text",
    "fix_rules_table_text",
    "fix_summary_line",
    "severity_breakdown",
]
